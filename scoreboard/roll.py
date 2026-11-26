#!/usr/bin/env python3
"""Keeps a Scoreboard on the right week.

The Scoreboard (sunday.html) and the home page (index.html) carry the week's
matchups, lineups, projections and kickoff times inside the page. The live
scores come straight from Sleeper in the browser, but only for the week the
page was built for.

The regular build owns sunday.html and rewrites it on every run, so this never
touches it. Instead it keeps scoreboard.html:

  - sunday.html is on the current week   -> scoreboard.html just forwards to it
  - sunday.html is still on last week    -> scoreboard.html is a copy of it with
    within 12 hours of the first kickoff    this week's data rebuilt from Sleeper

The home page is rolled the same way in place. Scoreboard links on every page
except sunday.html and radar.html, which the regular build keeps rewriting,
point at scoreboard.html. Pages built here are marked "cloud": true and are kept
fresh when rosters or kickoff times change.

Run from the repo root:  python3 scoreboard/roll.py [--force]
"""
import json, math, re, sys, time, urllib.request

LEAD_MS = 12 * 3600 * 1000          # roll this long before the week's first kickoff
API = 'https://api.sleeper.app'


def get(path):
    req = urllib.request.Request(API + path, headers={'User-Agent': 'bsmb-scoreboard'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


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


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def build(H, week, ms, sc, sc_next, players_db, proj):
    own, sd = H['owners'], H.get('sd', 27)
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
    pairs = {}
    for t in ms:
        if t.get('matchup_id') is not None:
            pairs.setdefault(t['matchup_id'], []).append(t['roster_id'])
    games = []
    for pair in sorted(sorted(p) for p in pairs.values() if len(p) == 2):
        x, y = pair
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
              built=int(time.time() * 1000), cloud=True)
    if H['week'] != week:
        H2.update(wire=[], tds=0, iced=[])
    starts = [g['start_time'] for g in sc_next if g.get('start_time')]
    if starts:
        H2['next_kick'] = min(starts)
    lean = [{'roster_id': t['roster_id'], 'starters': t.get('starters') or [],
             'players_points': {p: ((t.get('players_points') or {}).get(p) or 0)
                                for p in t.get('starters') or [] if p and p != '0'}} for t in ms]
    seed_sc = [{'status': g.get('status'), 'start_time': g.get('start_time'), 'metadata': g.get('metadata')} for g in sc]
    return H2, lean, seed_sc


def cards(s, games):
    """Rewrite the six matchup cards in the page for this week's pairings."""
    arts = re.findall(r'<article class="fgt" data-i="\d+".*?</article>', s, flags=re.S)
    if not arts:
        return s
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


GUARD_AT = 'function gotWire(j){var list=j&&j.ev?j.ev:j;if(!list||!list.length)return;'
GUARD = ('/*bsmb-wk*/var _k=0;for(var _t in (H.kick||{}))if(!_k||H.kick[_t]<_k)_k=H.kick[_t];'
         'if(_k&&Math.max(list[0].t||0,list[list.length-1].t||0)<_k-432e5)return;')
FORWARD = ('<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="robots" content="noindex">'
           '<meta http-equiv="refresh" content="0;url=sunday.html"><title>Scoreboard</title></head>'
           '<body><a href="sunday.html">Scoreboard</a><script>location.replace("sunday.html"+location.hash)</script></body></html>')


def guard_wire(s):
    """Make the page ignore a wire.json left over from an earlier week."""
    if '/*bsmb-wk*/' in s or GUARD_AT not in s:
        return s
    return s.replace(GUARD_AT, GUARD_AT + GUARD, 1)


def render(s, H, week, data):
    """Return the page `s` with its week data rebuilt for `week`."""
    ms, sc, sc_next, players_db, proj = data
    H2, lean, seed_sc = build(H, week, ms, sc, sc_next, players_db, proj)
    a, b, _ = grab(s, 'window.HUB')
    s = s[:a] + json.dumps(H2, separators=(',', ':'), ensure_ascii=False) + s[b:]
    seed = grab(s, 'window.HUBSEED')
    if seed:
        a2, b2, SE = seed
        try:
            rs = json.load(open('radar_status.json'))
        except Exception:
            rs = SE.get('rs') or {}
        s = s[:a2] + json.dumps({'rs': rs, 'sc': seed_sc, 'ms': lean}, separators=(',', ':'), ensure_ascii=False) + s[b2:]
    s = cards(s, H2['games'])
    for old in range(H['week'], week):
        s = s.replace('Scoreboard, Week %d' % old, 'Scoreboard, Week %d' % week)
        s = s.replace('<b class="ttl">Scoreboard</b><em>Week %d</em>' % old, '<b class="ttl">Scoreboard</b><em>Week %d</em>' % week)
    return guard_wire(s), H2


def read(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ''


def main():
    force = '--force' in sys.argv
    state = get('/v1/state/nfl')
    if state.get('season_type') != 'regular':
        print('not the regular season, nothing to do'); return
    week, season = int(state['week']), state['season']
    sun, idx, cur = read('sunday.html'), read('index.html'), read('scoreboard.html')
    gs, gi, gc = grab(sun, 'window.HUB'), grab(idx, 'window.HUB'), grab(cur, 'window.HUB')
    if not gs:
        print('sunday.html has no scoreboard data'); return
    Hs = gs[2]
    if Hs.get('season') != season:
        print('season mismatch, nothing to do'); return
    sc = get('/scores/nfl/regular/%s/%d' % (season, week))
    starts = [g['start_time'] for g in sc if g.get('start_time')]
    if not starts:
        print('no schedule for week', week); return
    due = int(time.time() * 1000) >= min(starts) - LEAD_MS
    ms = get('/v1/league/%s/matchups/%d' % (Hs['league'], week))
    ids = {p for t in ms for p in (t.get('players') or [])}
    kick = {tm: g['start_time'] for g in sc for tm in ((g.get('metadata') or {}).get('home_team'), (g.get('metadata') or {}).get('away_team')) if tm}
    fresh = lambda H: H and H.get('week') == week and ids == set(H.get('players') or {}) and kick == (H.get('kick') or {})
    n_games = len([1 for v in _pairs(ms).values() if len(v) == 2])
    cards_ok = lambda s: len(re.findall(r'<article class="fgt" data-i="\d+"', s)) in (0, n_games)

    sun_behind = Hs['week'] < week and due
    want_board = sun_behind and cards_ok(sun) and (force or not fresh(gc and gc[2]))
    Hi = gi[2] if gi else None
    want_home = bool(Hi) and cards_ok(idx) and (
        (Hi['week'] < week and due) or (Hi['week'] == week and Hi.get('cloud') and (force or not fresh(Hi))))
    print('week', week, '| sunday.html on', Hs['week'], '| home on', Hi and Hi['week'],
          '| board', 'rebuild' if want_board else ('keep' if sun_behind else 'forward'), '| home', 'rebuild' if want_home else 'keep')

    data = None
    if want_board or want_home:
        try:
            sc_next = get('/scores/nfl/regular/%s/%d' % (season, week + 1))
        except Exception:
            sc_next = []
        players_db = get('/v1/players/nfl')
        proj = {x['player_id']: ((x.get('stats') or {}).get('pts_ppr') or 0)
                for x in get('/projections/nfl/%s/%d?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K&position[]=DEF' % (season, week))}
        data = (ms, sc, sc_next, players_db, proj)

    if not sun_behind:
        if cur != FORWARD:
            open('scoreboard.html', 'w').write(FORWARD); print('scoreboard.html -> forwards to sunday.html')
    elif want_board:
        page, H2 = render(sun, Hs, week, data)
        page = page.replace('href="sunday.html"', 'href="scoreboard.html"')
        open('scoreboard.html', 'w').write(page)
        print('scoreboard.html -> week', week, [(g['a'], g['b']) for g in H2['games']])

    out = idx
    if want_home:
        out, H2 = render(out, Hi, week, data)
        print('index.html -> week', week)
    if gi:
        out = guard_wire(out).replace('href="sunday.html"', 'href="scoreboard.html"')
    if out != idx:
        open('index.html', 'w').write(out)
    repoint()


def repoint():
    """Send every Scoreboard link the regular build does not keep rewriting to scoreboard.html."""
    import glob
    skip = {'sunday.html', 'radar.html', 'scoreboard.html'}
    n = 0
    for f in glob.glob('**/*.html', recursive=True):
        if f in skip:
            continue
        t = read(f)
        u = t.replace('href="sunday.html"', 'href="scoreboard.html"').replace('href="../sunday.html"', 'href="../scoreboard.html"')
        u = u.replace('url=sunday.html"', 'url=scoreboard.html"').replace('location.replace("sunday.html")', 'location.replace("scoreboard.html")')
        if u != t:
            open(f, 'w').write(u); n += 1
    if n:
        print('Scoreboard links repointed in', n, 'pages')


def _pairs(ms):
    out = {}
    for t in ms:
        if t.get('matchup_id') is not None:
            out.setdefault(t['matchup_id'], []).append(t['roster_id'])
    return out


if __name__ == '__main__':
    try:
        main()
    except Exception as e:      # never fail the job over a Sleeper hiccup
        print('skipped:', repr(e))
