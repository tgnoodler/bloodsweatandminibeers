#!/usr/bin/env python3
"""Runs the Rundown engine live.

Started by .github/workflows/scoreboard-live.yml: on a schedule, by the Scoreboard week job, and whenever the home
computer pushes a build. GitHub starts scheduled runs hours late, so a run that finds a kickoff within 16 hours
stays up and carries the watch itself: it naps until game time, then every 20 seconds reads the NFL scores, the
league's lineups and Sleeper's player stats, hands them to the engine, and commits the Rundown
(scoreboard/wire.json), the Ice status (scoreboard/status.json) and its own memory (scoreboard/state.json) whenever
they change. Near GitHub's six-hour limit it starts its own replacement, checks that it came up, and steps aside.
Only the oldest run keeps the watch; any other steps aside. With nothing within 16 hours it makes one pass and stops.

Run from the repo root:  python3 scoreboard/live.py [--once] [--no-push]
"""
import copy, json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build
from engine import Engine
from sleeper import game_states, get, now_ms, read_json, write_json

HERE = 'scoreboard/'
FILES = [HERE + 'wire.json', HERE + 'status.json', HERE + 'state.json']
MAX_RUN = int(os.environ.get('LIVE_MAX_SECONDS') or 5 * 3600 + 15 * 60)
ALIVE_MS = 16 * 3600 * 1000     # stay up if a game kicks off within this long. GitHub starts scheduled runs hours late,
                                # so a run that is up has to carry the watch itself rather than count on the next one
OVERDUE_MS = 6 * 3600 * 1000    # and while a game is past its kickoff time but Sleeper has not marked it started
BUILD_EVERY_MS = 30 * 60 * 1000 # how often to check the page and the week's data while up
COOL_MS = 12 * 60 * 1000        # and this long after the last one ends, for the Ice calls
SETTLE = 40                     # seconds a push is given to finish building on the site before the next one
PUSH_EVERY_MS = 60 * 1000       # and the least time between our own pushes
BEAT_MS = 10 * 60 * 1000        # with nothing to report, still refresh the status this often while games are on
STATS = '/stats/nfl/%s/%d?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K&position[]=DEF'
REPO, TOKEN = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_TOKEN')
WORKFLOW = 'scoreboard-live.yml'


def sh(*cmd, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(' '.join(cmd) + ': ' + r.stderr.strip()[-300:])
    return r


def api(method, path, body=None):
    req = urllib.request.Request('https://api.github.com' + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
                                          'User-Agent': 'bsmb-scoreboard'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def active_runs():
    """Every run of this workflow that is running or about to."""
    runs = []
    for st in ('in_progress', 'queued'):
        runs += api('GET', '/repos/%s/actions/workflows/%s/runs?status=%s&per_page=50' % (REPO, WORKFLOW, st)).get('workflow_runs') or []
    return runs


def older_copy_running():
    """True if a run that started before this one is still going. The oldest one keeps the watch."""
    if not (REPO and TOKEN and os.environ.get('GITHUB_RUN_ID')):
        return False
    try:
        me = int(os.environ['GITHUB_RUN_ID'])
        return any(int(r.get('id') or 0) < me for r in active_runs())
    except Exception as e:
        print('could not check for another copy:', repr(e))
        return False


def hand_over():
    """Start the next copy and make sure it really started. GitHub's own schedule cannot be trusted to do it in time."""
    if not (REPO and TOKEN):
        return
    me = int(os.environ.get('GITHUB_RUN_ID') or 0)
    for attempt in range(4):
        try:
            api('POST', '/repos/%s/actions/workflows/%s/dispatches' % (REPO, WORKFLOW), {'ref': 'main', 'inputs': {'takeover': '1'}})
            for _ in range(8):
                time.sleep(6)
                if any(int(r.get('id') or 0) > me for r in active_runs()):
                    print('handed over to a new run'); return
        except Exception as e:
            print('handover attempt', attempt + 1, 'failed:', repr(e))
        time.sleep(5)
    print('could not hand over; the next scheduled or push-triggered run will pick the watch up')


def plan(now, games, ahead, last_live):
    """Should this run stay up, and how long until the next look? Returns (stay, seconds, why)."""
    if any(g['st'] == 1 for g in games):
        return True, 20, 'a game is on'
    if last_live and now - last_live <= COOL_MS:
        return True, 20, 'a game just ended'
    kicks = [g['kick'] for g in games if g['st'] == 0] + list(ahead or [])
    if any(0 <= now - k <= OVERDUE_MS for k in kicks):
        return True, 20, 'kickoff time has passed and the game has not shown as started yet'
    ahead_ms = [k - now for k in kicks if k > now]
    if not ahead_ms or min(ahead_ms) > ALIVE_MS:
        return False, 0, 'no kickoff within %d hours' % (ALIVE_MS // 3600000)
    nxt = min(ahead_ms)
    return True, (20 if nxt <= 10 * 60000 else 60 if nxt <= 75 * 60000 else 300), 'next kickoff in %d minutes' % (nxt // 60000)


OWN = ['scoreboard', 'scoreboard.html', 'report.html', 'sw.js']     # written only by the cloud build


def publish(paths, msg, push=True):
    """Commit the given paths if they changed and push, riding over the home computer's own pushes."""
    if not push or not sh('git', 'status', '--porcelain', '--', *paths).stdout.strip():
        return False
    sh('git', 'add', '--', *paths)
    sh('git', 'commit', '-q', '-m', msg)
    for i in range(5):
        if sh('git', 'pull', '--rebase', '-q', 'origin', 'main').returncode:
            # Someone else changed one of the same files. Ours are whole snapshots, so take theirs for everything
            # and lay our own files back on top. Anything outside OWN is left exactly as it is upstream.
            sh('git', 'rebase', '--abort')
            mine = {}
            for f in sh('git', 'ls-files', '--', *[x for x in OWN if os.path.exists(x)]).stdout.split():
                try:
                    mine[f] = open(f, 'rb').read()
                except Exception:
                    pass
            sh('git', 'fetch', '-q', 'origin', 'main')
            sh('git', 'reset', '-q', '--hard', 'origin/main')
            for f, data in mine.items():
                os.makedirs(os.path.dirname(f) or '.', exist_ok=True)
                open(f, 'wb').write(data)
            sh('git', 'add', '--', *[x for x in OWN if os.path.exists(x)])
            sh('git', 'commit', '-q', '-m', msg)
        # Each push starts a site build, and a newer push cancels one still running. Give the last push, ours or the
        # home computer's, time to finish building before sending the next, or the site could stop updating.
        try:
            age = time.time() - int(sh('git', 'log', '-1', '--format=%ct', 'origin/main').stdout.strip() or 0)
            if 0 <= age < SETTLE:
                time.sleep(SETTLE - age)
                continue                        # look again before pushing: something may have landed while we waited
        except Exception:
            pass
        if sh('git', 'push', '-q', 'origin', 'HEAD:main').returncode == 0:
            return True
        time.sleep(2 + 2 * i)
    print('push failed; will try again with the next change')
    return False


def strip(d, *keys):
    return {k: v for k, v in (d or {}).items() if k not in keys}


def main():
    once, push = '--once' in sys.argv, '--no-push' not in sys.argv
    started = time.time()
    takeover = os.environ.get('TAKEOVER') == '1'
    if push:
        sh('git', 'config', 'user.name', 'scoreboard')
        sh('git', 'config', 'user.email', 'scoreboard@users.noreply.github.com')
    if not takeover and older_copy_running():
        print('an older run is already watching; nothing to do'); return
    injury = lambda pid: get('/v1/players/nfl/' + pid, tries=1)
    E, W, season, ahead = None, {}, None, []
    last_live = last_build = last_guard = 0
    last_push = now_ms()
    passes, relay, why = 0, False, 'starting'
    while True:
        now = now_ms()
        stay, nap = True, 60
        try:
            if now - last_build >= BUILD_EVERY_MS:      # the page, the week's data, and which week we are watching
                last_build = now
                build.main()
                W2 = read_json(HERE + 'week.json') or {}
                if W2.get('week') and (E is None or W2['week'] != E.week):
                    W, season = W2, W2['season']
                    E = Engine(W['week'], W, read_json(HERE + 'state.json'), read_json(HERE + 'wire.json'))
                    print('watching week', E.week)
                elif E is not None and W2.get('week') == E.week:
                    W = W2
                    E.W = W
                ahead = []
                cur = get('/v1/state/nfl')
                if E is not None and cur.get('season_type') == 'regular' and int(cur['week']) != E.week:
                    ahead = [g['start_time'] for g in get('/scores/nfl/regular/%s/%d' % (cur['season'], int(cur['week']))) if g.get('start_time')]
                publish(['.'], 'Scoreboard week roll', push)
            if E is None:
                print('no week data yet'); break
            week = E.week
            sc = get('/scores/nfl/regular/%s/%d' % (season, week))
            G = game_states(sc)
            games = list({g['k']: g for g in G.values()}.values())
            live = any(g['st'] == 1 for g in games)
            if live:
                last_live = now
            if games and now >= min(g['kick'] for g in games):
                ms = get('/v1/league/%s/matchups/%d' % (W['league'], week))
                known = set(W.get('players') or {})
                if any(p not in known for t in ms for p in (t.get('players') or [])) and now - last_build > 10 * 60 * 1000:
                    last_build = 0                  # someone was picked up: refresh names, teams and projections next pass
                stats = get(STATS % (season, week))
                keep = copy.deepcopy((E.s, E.ev))
                try:
                    new = E.tick(now, sc, ms, stats, injury)
                except Exception:
                    E.s, E.ev = keep                 # a pass that fails half way must not leave half its work behind
                    raise
                for e in new:
                    print(time.strftime('%H:%M:%S'), e['kind'], '|', e['text'])
                if E.feed() != read_json(HERE + 'wire.json'):
                    write_json(HERE + 'wire.json', E.feed())
                if strip(E.status, 'built') != strip(read_json(HERE + 'status.json'), 'built'):
                    write_json(HERE + 'status.json', E.status)
                if strip(E.s, 'last') != strip(read_json(HERE + 'state.json'), 'last'):
                    write_json(HERE + 'state.json', E.s)
                passes += 1
                if live and now - last_push >= BEAT_MS:     # a quiet stretch: prove we are still watching
                    E.status['built'] = now
                    write_json(HERE + 'status.json', E.status)
                    write_json(HERE + 'state.json', E.s)
                    print(time.strftime('%H:%M:%S'), 'still watching:', sum(1 for g in games if g['st'] == 1), 'live,', len(E.ev), 'entries')
                if now - last_push >= PUSH_EVERY_MS and publish(['.'], 'Rundown', push):
                    last_push = now_ms()
            stay, nap, now_why = plan(now, games, ahead, last_live)
            if now_why != why:
                why = now_why
                print(time.strftime('%H:%M:%S'), why)
        except Exception as e:                      # one bad pass must not end the watch
            print('pass skipped:', repr(e))
        if once or not stay:
            break
        if time.time() - started > MAX_RUN:
            relay = True
            break
        if now - last_guard >= 5 * 60 * 1000 and (not takeover or time.time() - started > 180):
            last_guard = now
            if older_copy_running():
                print('an older run is watching; stepping aside'); break
        time.sleep(nap)
    if E is not None:
        write_json(HERE + 'state.json', E.s)        # leave the clock where the next copy can pick it up
        publish(['.'], 'Rundown', push)
    if relay:                                       # only once everything is saved, so the next copy starts from it
        hand_over()
    print('done after', passes, 'passes:', why)


if __name__ == '__main__':
    main()
