"""Shared helpers: Sleeper calls, game clocks, win odds. Standard library only."""
import json, math, time, urllib.request

API = 'https://api.sleeper.app'
SD = 27.0


def get(path, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={'User-Agent': 'bsmb-scoreboard'})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:      # brief network trouble should not end a live run
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def now_ms():
    return int(time.time() * 1000)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, separators=(',', ':'), ensure_ascii=False)


def secs(clock):
    try:
        m, s = str(clock).split(':')
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def game_states(sc):
    """Per-team game state, worked out the same way the Scoreboard page does it."""
    out = {}
    for g in sc or []:
        md = g.get('metadata') or {}
        home, away = md.get('home_team'), md.get('away_team')
        if not home or not away:
            continue
        over = bool(md.get('is_over') or g.get('status') == 'complete' or md.get('status') == 'closed')
        started = bool(over or md.get('is_in_progress') or g.get('status') == 'in_game' or md.get('has_started'))
        try:
            q = int(float(md.get('quarter_num') or 0))
        except Exception:
            q = 0
        tr = str(md.get('time_remaining') or '')
        half = str(md.get('quarter') or '').upper().startswith('H')
        if not started:
            rem, lab = 1.0, ''
        elif over:
            rem, lab = 0.0, 'FINAL'
        elif half:
            rem, lab = 0.5, 'HALF'
        else:
            qq = max(1, min(q or 1, 5))
            rem = 0.02 if qq >= 5 else ((4 - qq) + min(900, secs(tr)) / 900.0) / 4.0
            lab = ('OT' if qq >= 5 else 'Q%d' % qq) + ((' ' + tr) if tr else '')
        o = {'k': away + '@' + home, 'home': home, 'away': away,
             'hs': int(float(md.get('home_score') or 0)), 'as': int(float(md.get('away_score') or 0)),
             'st': 2 if over else 1 if started else 0, 'q': q, 'half': half, 'secs': secs(tr),
             'rem': rem, 'lab': lab, 'kick': g.get('start_time') or 0}
        o['score'] = ('%s %d, %s %d' % (away, o['as'], home, o['hs'])) if started else ''
        out[home] = out[away] = o
    return out


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def side(t, players, G):
    """One owner's lineup: points so far, expected finish, and what is still to come."""
    pp = t.get('players_points') or {}
    pts = exp = rw = tw = 0.0
    left = 0
    for pid in t.get('starters') or []:
        if not pid or pid == '0':
            continue
        p = players.get(pid) or {}
        cur, pr = float(pp.get(pid) or 0), float(p.get('pr') or 0)
        g = G.get(p.get('t'))
        rem = g['rem'] if g else (0.0 if G else 1.0)
        pts += cur; exp += cur + pr * rem; rw += pr * rem; tw += pr
        if g and g['st'] < 2:
            left += 1
    return {'pts': round(pts, 2), 'exp': exp, 'rw': rw, 'tw': tw, 'left': left}


def win_prob(A, B, aw=50.0):
    """Chance the first owner wins, by the Scoreboard page's own formula."""
    tw, rw = A['tw'] + B['tw'], A['rw'] + B['rw']
    if not tw:
        return aw / 100.0
    avg = rw / tw
    if avg <= 0.001:
        return 1.0 if A['pts'] > B['pts'] else 0.0 if A['pts'] < B['pts'] else 0.5
    return phi((A['exp'] - B['exp']) / (SD * math.sqrt(2) * math.sqrt(avg)))
