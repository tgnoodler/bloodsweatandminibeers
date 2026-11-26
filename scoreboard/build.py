#!/usr/bin/env python3
"""Builds the cloud Scoreboard for the week.

The regular build on the home computer owns sunday.html and rewrites it on every run, so nothing here touches it.
This builds scoreboard.html from it instead: the same page, with

  - this week's matchups, lineups, projections and kickoff times, rebuilt from Sleeper
  - the Rundown read from scoreboard/wire.json and the Ice count from scoreboard/status.json, both written by
    the live engine (scoreboard/live.py), not from the home computer's wire.json and radar_status.json

The page moves to the new week 12 hours before its first kickoff. Until then it stays on last week's final.
The home page's scoreboard is kept in step the same way, in place. Every Scoreboard link on the site except the ones
on sunday.html and radar.html, which the regular build keeps rewriting, points at scoreboard.html, and sw.js sends
anyone who lands on the old address there.

Run from the repo root:  python3 scoreboard/build.py [--force]
"""
import glob, json, math, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sleeper import get, now_ms, phi, read_json, write_json, SD
import report as weekly

LEAD_MS = 12 * 3600 * 1000      # move to the new week this long before its first kickoff
BUILD = 4                       # bump to make the job rebuild pages it built earlier
HERE = 'scoreboard/'
PROJ = '/projections/nfl/%s/%d?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K&position[]=DEF'
SW_TAG = "<script>if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){})}</script>"
POLL_OLD = ("if(n>=due.w&&!busy.w){busy.w=1;due.w=n+45000;get(pre+'wire.json',gotWire).then(function(){busy.w=0})}",
            "if(n>=due.w&&!busy.w){busy.w=1;due.w=n+(live?60000:300000);tdFeed().then(function(){busy.w=0})}")
POLL_NEW = "if(n>=due.w&&!busy.w){busy.w=1;due.w=n+(live?20000:60000);get(pre+'scoreboard/wire.json',gotWire).then(function(){busy.w=0})}"


def grab(s, name):
    """Find `name={...}` in the page and return (start, end, parsed object)."""
    i = s.find(name + '=')
    if i < 0:
        return None
    j = s.find('{', i)
    depth, ins, esc = 0, False, False
    for k in range(j, len(s)):
        c = s[k]
        if ins:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': ins = False
        elif c == '"': ins = True
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return j, k + 1, json.loads(s[j:k + 1])
    return None


def read(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ''


def pairs(ms):
    out = {}
    for t in ms:
        if t.get('matchup_id') is not None:
            out.setdefault(t['matchup_id'], []).append(t['roster_id'])
    return [sorted(p) for p in out.values() if len(p) == 2]


def week_data(H, week, ms, sc, sc_next, players_db, proj):
    """The week's data in the shape the Scoreboard page carries it."""
    own, sd = H['owners'], H.get('sd', SD)
    players, pos = {}, {}
    for t in ms:
        for pid in t.get('players') or []:
            q = players_db.get(pid, {})
            if q.get('position') == 'DEF' or not pid.isdigit():
                players[pid] = {'n': pid + ' DEF', 't': pid, 'pr': round(proj.get(pid, 0), 1)}
                pos[pid] = 'DEF'
            else:
                name = q.get('full_name') or (q.get('first_name', '') + ' ' + q.get('last_name', '')).strip() or pid
                players[pid] = {'n': name, 't': q.get('team'), 'pr': round(proj.get(pid, 0), 1)}
                pos[pid] = q.get('position') or ''
    byid = {t['roster_id']: t for t in ms}
    exp = lambda t: sum(players[p]['pr'] for p in t.get('starters') or [] if p in players)
    games = []
    for x, y in sorted(pairs(ms)):
        ap, bp = round(exp(byid[x]), 2), round(exp(byid[y]), 2)
        games.append({'a': own[str(x)], 'b': own[str(y)],
                      'aw': round(phi((ap - bp) / (sd * math.sqrt(2))) * 100, 2), 'ap': ap, 'bp': bp})
    kick = {}
    for g in sc:
        m = g.get('metadata') or {}
        for tm in (m.get('home_team'), m.get('away_team')):
            if tm:
                kick[tm] = g['start_time']
    old = dict(H.get('hsl') or {}); old.update(H.get('heads') or {})
    heads = {}
    for pid in players:
        if (H.get('heads') or {}).get(pid):
            heads[pid] = H['heads'][pid]
        elif pos[pid] == 'DEF':
            heads[pid] = old.get(pid) or 'https://sleepercdn.com/images/team_logos/nfl/%s.png' % pid.lower()
        else:
            heads[pid] = 'https://sleepercdn.com/content/nfl/players/thumb/%s.jpg' % pid
    H2 = dict(H)
    H2.update(week=week, games=games, players=players, pos=pos, kick=kick, heads=heads,
              hsl={k: v for k, v in (H.get('hsl') or {}).items() if k in players and v},
              wire=[], tds=0, iced=[], built=now_ms(), cloud=True, cloudv=BUILD)
    starts = [g['start_time'] for g in sc_next if g.get('start_time')]
    if starts:
        H2['next_kick'] = min(starts)
    lean = [{'roster_id': t['roster_id'], 'starters': t.get('starters') or [],
             'players_points': {p: ((t.get('players_points') or {}).get(p) or 0)
                                for p in t.get('starters') or [] if p and p != '0'}} for t in ms]
    seed_sc = [{'status': g.get('status'), 'start_time': g.get('start_time'), 'metadata': g.get('metadata')} for g in sc]
    return H2, lean, seed_sc


def cards(s, games):
    """Rewrite the matchup cards in the page for this week's pairings."""
    arts = re.findall(r'<article class="fgt" data-i="\d+".*?</article>', s, flags=re.S)
    feed = {}
    for art in arts:
        for src, nm in re.findall(r'<img class="ph" src="([^"]+)"[^>]*>.*?<span class="nm"><i>([^<]+)</i>', art, flags=re.S):
            feed[nm] = src
    for art, g in zip(arts, games):
        srcs = re.findall(r'<img class="ph" src="([^"]+)"', art)
        nms = re.findall(r'<span class="nm"><i>([^<]+)</i>', art)
        new = art.replace('src="%s"' % srcs[0], 'src="@@A@@"', 1).replace('src="%s"' % srcs[1], 'src="@@B@@"', 1)
        new = new.replace('<span class="nm"><i>%s</i>' % nms[0], '<span class="nm"><i>@@NA@@</i>', 1)
        new = new.replace('<span class="nm"><i>%s</i>' % nms[1], '<span class="nm"><i>@@NB@@</i>', 1)
        new = (new.replace('@@A@@', feed[g['a']]).replace('@@B@@', feed[g['b']])
                  .replace('@@NA@@', g['a']).replace('@@NB@@', g['b']))
        aw = round(g['aw'])
        new = re.sub(r'<span class="wp a">\d+%</span>', '<span class="wp a">%d%%</span>' % aw, new)
        new = re.sub(r'<span class="wp b">\d+%</span>', '<span class="wp b">%d%%</span>' % (100 - aw), new)
        new = re.sub(r'style="--p:[\d.]+%"', 'style="--p:%s%%"' % g['aw'], new)
        s = s.replace(art, new, 1)
    return s


def wire_up(s):
    """Point the page at the cloud engine's Rundown and Ice status, and register the redirect for the old address."""
    s = re.sub(r"/\*bsmb-td\*/.*?(?=var due=\{m:0,s:0,w:0,t:0\})", '', s, flags=re.S)    # an earlier browser-side feed
    for old in POLL_OLD:
        s = s.replace(old, POLL_NEW)
    s = s.replace("get(pre+'radar_status.json',function(j){if(j){H.rs=j;paint()}})",
                  "get(pre+'scoreboard/status.json',function(j){if(j){H.rs=j;paint()}})")
    s = s.replace("fetch('recap/latest.json'", "fetch('scoreboard/latest.json'")
    s = s.replace('href="recap.html"', 'href="report.html"')
    if '/sw.js' not in s and '</body>' in s:
        s = s.replace('</body>', SW_TAG + '</body>', 1)
    return s


def render(s, H, week, data, status):
    """Return the page `s` with its week data rebuilt for `week`."""
    ms, sc, sc_next, players_db, proj = data
    H2, lean, seed_sc = week_data(H, week, ms, sc, sc_next, players_db, proj)
    a, b, _ = grab(s, 'window.HUB')
    s = s[:a] + json.dumps(H2, separators=(',', ':'), ensure_ascii=False) + s[b:]
    seed = grab(s, 'window.HUBSEED')
    if seed:
        a2, b2, _ = seed
        s = s[:a2] + json.dumps({'rs': status, 'sc': seed_sc, 'ms': lean}, separators=(',', ':'), ensure_ascii=False) + s[b2:]
    s = cards(s, H2['games'])
    for old in range(max(1, week - 3), week):
        s = s.replace('Scoreboard, Week %d' % old, 'Scoreboard, Week %d' % week)
        s = s.replace('<b class="ttl">Scoreboard</b><em>Week %d</em>' % old, '<b class="ttl">Scoreboard</b><em>Week %d</em>' % week)
    return wire_up(s), H2


def repoint():
    """Send Scoreboard links to scoreboard.html and register the redirect, on every page the regular build leaves alone."""
    skip = {'sunday.html', 'radar.html', 'scoreboard.html', 'recap.html', 'report.html'}
    n = 0
    for f in glob.glob('**/*.html', recursive=True):
        if f in skip or f.startswith('recap/wk'):      # the report cards are pictures' sources, not pages
            continue
        t = read(f)
        u = t.replace('href="sunday.html"', 'href="scoreboard.html"').replace('href="../sunday.html"', 'href="../scoreboard.html"')
        u = u.replace('url=sunday.html"', 'url=scoreboard.html"').replace('location.replace("sunday.html")', 'location.replace("scoreboard.html")')
        u = u.replace('href="recap.html"', 'href="report.html"').replace('href="../recap.html"', 'href="../report.html"')
        if '/sw.js' not in u and '</body>' in u:
            u = u.replace('</body>', SW_TAG + '</body>', 1)
        if u != t:
            open(f, 'w').write(u); n += 1
    if n:
        print('links and redirect updated on', n, 'pages')


def main(force=False):
    state = get('/v1/state/nfl')
    if state.get('season_type') != 'regular':
        print('not the regular season, nothing to do'); return
    week, season = int(state['week']), state['season']
    sun, idx, cur = read('sunday.html'), read('index.html'), read('scoreboard.html')
    gs, gi, gc = grab(sun, 'window.HUB'), grab(idx, 'window.HUB'), grab(cur, 'window.HUB')
    if not gs or gs[2].get('season') != season:
        print('sunday.html has no scoreboard data for this season'); return
    Hs, Hc, Hi = gs[2], (gc[2] if gc else None), (gi[2] if gi else None)
    sc = get('/scores/nfl/regular/%s/%d' % (season, week))
    starts = [g['start_time'] for g in sc if g.get('start_time')]
    if not starts:
        print('no schedule for week', week); return
    due = now_ms() >= min(starts) - LEAD_MS
    target = week if due else week - 1
    wk = read_json(HERE + 'week.json') or {}
    if not due:
        # between weeks: last week's final stays up. Only make sure there is a page at all.
        if Hc:
            report(Hc['week'], season); repoint(); print('week', week, 'not due yet; page stays on week', Hc['week']); return
        sc = get('/scores/nfl/regular/%s/%d' % (season, target))
    ms = get('/v1/league/%s/matchups/%d' % (Hs['league'], target))
    ids = {p for t in ms for p in (t.get('players') or [])}
    kick = {tm: g['start_time'] for g in sc for tm in ((g.get('metadata') or {}).get('home_team'), (g.get('metadata') or {}).get('away_team')) if tm}
    fresh = lambda H: bool(H) and H.get('week') == target and H.get('cloudv') == BUILD and ids == set(H.get('players') or {}) and kick == (H.get('kick') or {})
    n_games = len(pairs(ms))
    cards_ok = lambda s: len(re.findall(r'<article class="fgt" data-i="\d+"', s)) in (0, n_games)
    want_board = cards_ok(sun) and (force or not fresh(Hc))
    want_home = bool(Hi) and cards_ok(idx) and Hi.get('week', 0) <= target and (force or not fresh(Hi))
    want_week = force or not (wk.get('week') == target and ids == set(wk.get('players') or {}) and kick == (wk.get('kick') or {}))
    print('week', week, '| page week', target, '| board', 'rebuild' if want_board else 'keep', '| home', 'rebuild' if want_home else 'keep')

    # a new week starts with an empty Rundown
    feed = read_json(HERE + 'wire.json') or {}
    status = read_json(HERE + 'status.json') or {}
    if feed.get('week') != target:
        write_json(HERE + 'wire.json', {'v': 2, 'week': target, 'ev': [], 'tds': 0, 'iced': []})
        status = {'week': target, 'confirmed': 0, 'warnings': 0, 'in_play': False, 'live': False, 'witching': [], 'built': now_ms()}
        write_json(HERE + 'status.json', status)
        write_json(HERE + 'state.json', {'week': target, 'td': {}, 'own_td': {}, 'tdw': 0, 'flags': {}, 'iced': [], 'lead': {}, 'fav': {}, 'last': 0})
        print('Rundown reset for week', target)

    if want_board or want_home or want_week:
        try:
            sc_next = get('/scores/nfl/regular/%s/%d' % (season, target + 1))
        except Exception:
            sc_next = []
        players_db = get('/v1/players/nfl')
        proj = {x['player_id']: ((x.get('stats') or {}).get('pts_ppr') or 0) for x in get(PROJ % (season, target))}
        data = (ms, sc, sc_next, players_db, proj)
        H2 = None
        if want_board:
            page, H2 = render(sun, Hs, target, data, status)
            page = page.replace('href="sunday.html"', 'href="scoreboard.html"')
            open('scoreboard.html', 'w').write(page)
            print('scoreboard.html -> week', target, [(g['a'], g['b']) for g in H2['games']])
        if want_home:
            out, H2 = render(idx, Hi, target, data, status)
            open('index.html', 'w').write(out)
            print('index.html -> week', target)
        if H2 is None:
            H2 = week_data(Hs, target, *data)[0]
        write_json(HERE + 'week.json', {k: H2[k] for k in ('week', 'season', 'league', 'owners', 'players', 'pos', 'kick', 'games', 'built')})
    # the home page between rebuilds: keep it wired to the cloud files
    idx2 = read('index.html')
    if gi and wire_up(idx2) != idx2:
        open('index.html', 'w').write(wire_up(idx2))
    try:
        weekly.main()                               # the Weekly Report card and page
    except Exception as e:
        print('weekly report skipped:', repr(e))
    report(target, season, sc)
    repoint()


def report(week, season, sc=None):
    """Tell the page whether the weekly report picture for its week exists yet."""
    try:
        sc = sc if sc is not None else get('/scores/nfl/regular/%s/%d' % (season, week))
        over = bool(sc) and all((g.get('status') == 'complete' or (g.get('metadata') or {}).get('is_over')) for g in sc)
        png = 'recap/wk%d.png' % week
        new = {'week': week, 'final': bool(over and os.path.exists(png)), 'stamp': int(os.path.getmtime(png)) if os.path.exists(png) else 0}
        if read_json(HERE + 'latest.json') != new:
            write_json(HERE + 'latest.json', new)
    except Exception as e:
        print('weekly report check skipped:', repr(e))


if __name__ == '__main__':
    try:
        main('--force' in sys.argv)
    except Exception as e:      # never fail the job over a Sleeper hiccup
        print('skipped:', repr(e))
