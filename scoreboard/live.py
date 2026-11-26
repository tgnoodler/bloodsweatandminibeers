#!/usr/bin/env python3
"""Runs the Rundown engine live.

Started every ten minutes by .github/workflows/scoreboard-live.yml. If no game is on or about to start it makes one
pass, to catch stat corrections, and stops. Otherwise it stays up for the whole window: every 20 seconds it reads the
NFL scores, the league's lineups and Sleeper's player stats, hands them to the engine, and commits the Rundown
(scoreboard/wire.json), the Ice status (scoreboard/status.json) and its own memory (scoreboard/state.json) whenever
they change. Only one copy runs at a time; near GitHub's six-hour limit it starts its own replacement and steps aside.

Run from the repo root:  python3 scoreboard/live.py [--once] [--no-push]
"""
import copy, json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build
from engine import Engine
from sleeper import game_states, get, now_ms, read_json, write_json

HERE = 'scoreboard/'
FILES = [HERE + 'wire.json', HERE + 'status.json', HERE + 'state.json']
MAX_RUN = int(os.environ.get('LIVE_MAX_SECONDS', 5 * 3600 + 15 * 60))
SOON_MS = 75 * 60 * 1000        # stay up if a game kicks off within this long
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


def another_copy_running():
    """True if a different run of this workflow is already watching the games."""
    if not (REPO and TOKEN) or os.environ.get('TAKEOVER') == '1':
        return False
    try:
        me = str(os.environ.get('GITHUB_RUN_ID'))
        runs = api('GET', '/repos/%s/actions/workflows/%s/runs?per_page=20' % (REPO, WORKFLOW)).get('workflow_runs') or []
        return any(str(r.get('id')) != me and r.get('status') in ('in_progress', 'queued', 'requested', 'waiting', 'pending') for r in runs)
    except Exception as e:
        print('could not check for another copy:', repr(e))
        return False


def hand_over():
    if not (REPO and TOKEN):
        return
    try:
        api('POST', '/repos/%s/actions/workflows/%s/dispatches' % (REPO, WORKFLOW), {'ref': 'main', 'inputs': {'takeover': '1'}})
        print('started a replacement run')
    except Exception as e:
        print('could not start a replacement:', repr(e))


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
    if push:
        sh('git', 'config', 'user.name', 'scoreboard')
        sh('git', 'config', 'user.email', 'scoreboard@users.noreply.github.com')
    state = get('/v1/state/nfl')
    if state.get('season_type') != 'regular':
        print('not the regular season'); return
    season, week = state['season'], int(state['week'])
    if another_copy_running():
        print('another copy is already watching; nothing to do'); return
    build.main()                                    # make sure the page and week data are on the right week
    W = read_json(HERE + 'week.json') or {}
    if not W.get('week'):
        print('no week data yet'); return
    if W['week'] != week:                           # between weeks the page is still on last week: one pass for corrections
        print('page is on week', W['week'], 'until week', week, 'is close')
        week = W['week']
    E = Engine(week, W, read_json(HERE + 'state.json'), read_json(HERE + 'wire.json'))
    publish(['.'], 'Scoreboard week roll', push)
    injury = lambda pid: get('/v1/players/nfl/' + pid, tries=1)
    last_live = last_build = 0
    last_push = now_ms()
    passes = 0
    relay = False
    while True:
        now = now_ms()
        try:
            sc = get('/scores/nfl/regular/%s/%d' % (season, week))
            G = game_states(sc)
            games = list({g['k']: g for g in G.values()}.values())
            live = any(g['st'] == 1 for g in games)
            soon = any(g['st'] == 0 and 0 <= g['kick'] - now <= SOON_MS for g in games)
            under_way = bool(games) and now >= min(g['kick'] for g in games)
            if live:
                last_live = now
            waiting = soon and not live and not any(g['st'] == 0 and g['kick'] - now <= 3 * 60 * 1000 for g in games)
            if under_way and not (waiting and passes):
                ms = get('/v1/league/%s/matchups/%d' % (W['league'], week))
                known = set(W.get('players') or {})
                if any(p not in known for t in ms for p in (t.get('players') or [])) and now - last_build > 10 * 60 * 1000:
                    last_build = now                # someone was picked up: refresh names, teams and projections
                    build.main()
                    W = read_json(HERE + 'week.json') or W
                    E.W = W
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
        except Exception as e:                      # one bad pass must not end the watch
            print('pass skipped:', repr(e))
            live = soon = True
        cooling = last_live and now - last_live <= COOL_MS
        if once or not (live or soon or cooling):
            break
        if time.time() - started > MAX_RUN:
            relay = True
            break
        time.sleep(20 if (live or cooling) else 60)
    write_json(HERE + 'state.json', E.s)            # leave the clock where the next copy can pick it up
    publish(['.'], 'Rundown', push)
    if relay:                                       # only once everything is saved, so the next copy starts from it
        hand_over()
    print('done after', passes, 'passes')


if __name__ == '__main__':
    main()
