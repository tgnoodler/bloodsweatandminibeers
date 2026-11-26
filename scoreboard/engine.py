"""The Rundown engine.

Feed it a snapshot of the week (NFL scores, the league's matchups, Sleeper's player stats) and it works out what just
happened: touchdowns, starters stuck at zero and getting off it, Ices, lead changes and swings. Each call to tick()
compares the snapshot with what it saw last time and returns the new Rundown entries, worded the way the Scoreboard
page expects them.

It keeps no clock of its own and makes no network calls, so it can be tested by replaying made-up snapshots.
"""
from sleeper import game_states, side, win_prob

RANK = {'outlook': 1, 'advisory': 2, 'watch': 3, 'warning': 4}
CONFIRM_WAIT = 90 * 1000        # let the final stats settle this long before calling an Ice
LATE_GAP = 10 * 60 * 1000       # after a gap this long, entries are logged without a game clock
MILESTONE = {3: 'hat trick', 4: 'grand slam', 5: 'fistful', 6: 'six-pack'}
TD = {'pass': ('throws a touchdown', 'Passing', '40+ yard pass'),
      'rec': ('catches a touchdown', 'Receiving', '40+ yard catch'),
      'rush': ('runs one in', 'Rushing', '40+ yard run'),
      'ret': ('returns one for a touchdown', 'Return', 'Return'),
      'def': ('scores', 'Defense', 'Defense')}
HURT = ('Out', 'IR', 'Doubtful')


def num(v):
    """0 -> '0', -2.0 -> '-2.0', 1.5 -> '1.5': the way finishes are written in the Rundown."""
    v = round(float(v), 2)
    return '0' if v == 0 else str(v)


def trim(v):
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else str(v)


class Engine:
    def __init__(self, week, W, state=None, feed=None):
        self.week, self.W = week, W
        ok = bool(state) and state.get('week') == week
        self.s = state if ok else {'week': week, 'td': {}, 'own_td': {}, 'tdw': 0, 'flags': {},
                                   'iced': [], 'lead': {}, 'fav': {}, 'last': 0}
        self.ev = list((feed or {}).get('ev') or []) if (feed or {}).get('week') == week else []
        self.hist = {}          # matchup -> [(t, pct for the first owner)], last few minutes only
        self.inj_at = {}        # player -> when we last asked about an injury
        self.status = {}

    # ---- output ----
    def feed(self):
        return {'v': 2, 'week': self.week, 'ev': self.ev,
                'tds': sum(1 for e in self.ev if e['kind'] == 'td'), 'iced': self.s['iced']}

    # ---- one pass ----
    def tick(self, now, sc, ms, stats, injury=None):
        s, W = self.s, self.W
        players, owners = W.get('players') or {}, W.get('owners') or {}
        G = game_states(sc)
        games = list({g['k']: g for g in G.values()}.values())
        if not games or not ms:
            return []
        first_kick, last_kick = min(g['kick'] for g in games), max(g['kick'] for g in games)
        late = (not s.get('last')) or (now - s['last'] > LATE_GAP)
        by = {str(x.get('player_id')): x for x in (stats or [])}
        new = []

        def add(kind, owner, pid, text, t=None, **kw):
            e = {'t': (t if t is not None else now) + len(new), 'kind': kind, 'owner': owner, 'id': pid, 'text': text}
            e.update(kw)
            new.append(e)
            return e

        def name(pid):
            p = players.get(pid) or {}
            if p.get('n'):
                return p['n']
            pl = (by.get(pid) or {}).get('player') or {}
            n = ((pl.get('first_name') or '') + ' ' + (pl.get('last_name') or '')).strip()
            return n or (pid if pid.isdigit() else pid + ' DEF')

        def team(pid):
            return (players.get(pid) or {}).get('t') or (by.get(pid) or {}).get('team') or (None if pid.isdigit() else pid)

        def posn(pid):
            return ((W.get('pos') or {}).get(pid) or ((by.get(pid) or {}).get('player') or {}).get('position')
                    or ('' if pid.isdigit() else 'DEF'))

        # ---------- touchdowns ----------
        carries = {}
        for x in stats or []:
            if ((x.get('player') or {}).get('position')) == 'RB' and x.get('team'):
                carries.setdefault(x['team'], {})[str(x.get('player_id'))] = (x.get('stats') or {}).get('rush_att') or 0
        found = []
        for t in ms:
            owner = owners.get(str(t.get('roster_id')))
            if not owner:
                continue
            for pid in t.get('starters') or []:
                if not pid or pid == '0':
                    continue
                x = by.get(pid) or {}
                st = x.get('stats') or {}
                if posn(pid) == 'DEF':
                    cur, c40 = {'def': int((st.get('def_td') or 0) + (st.get('def_st_td') or 0))}, {}
                else:
                    cur = {'rush': int(st.get('rush_td') or 0), 'rec': int(st.get('rec_td') or 0),
                           'ret': int(st.get('st_td') or 0), 'pass': int(st.get('pass_td') or 0)}
                    c40 = {k: int(st.get(k + '_td_40p') or 0) for k in ('rush', 'rec', 'pass')}
                key = owner + '|' + pid
                old = s['td'].get(key)
                g = G.get(team(pid))
                # never seen before and his game is already under way: these happened before we were watching
                missed = late or (old is None and bool(g) and g['st'] > 0)
                old = old or {'c': {}, 'c40': {}}
                had = sum(old['c'].values())
                opened = False
                for typ in cur:
                    d = cur[typ] - old['c'].get(typ, 0)
                    if d < 0:       # a score taken off the board
                        self._retract_td(owner, pid, typ, -d)
                        had += d
                    for i in range(max(0, d)):
                        had += 1
                        first = bool(st.get('first_td')) and not old.get('ft') and typ != 'pass' and not opened
                        opened = opened or first
                        found.append({'owner': owner, 'pid': pid, 'typ': typ, 'missed': missed, 'k': had, 'g': g,
                                      'long': (c40.get(typ, 0) - old['c40'].get(typ, 0)) > i, 'first': first,
                                      'at': x.get('updated_at') or x.get('last_modified')})
                s['td'][key] = {'c': cur, 'c40': c40, 'ft': bool(old.get('ft') or opened)}
        per_owner = {}
        for f in found:
            per_owner[f['owner']] = per_owner.get(f['owner'], 0) + 1
        own_td = s.setdefault('own_td', {})
        first_scorer_of_week = s.get('tdw', 0) == 0
        # each touchdown is the owner's 1st, 2nd, 3rd of the week; a throw and its catch on one roster share a number
        seq = {}
        for f in found:
            seq[f['owner']] = seq.get(f['owner'], own_td.get(f['owner'], 0)) + 1
            f['n'] = seq[f['owner']]
        for f in found:
            if f['typ'] == 'pass' and not f['missed']:
                mate = [x for x in found if x['owner'] == f['owner'] and x['typ'] == 'rec' and x['g'] is f['g'] and not x.get('paired')]
                if mate:
                    mate[0]['paired'] = 1
                    f['n'] = mate[0]['n'] = max(f['n'], mate[0]['n'])
        for f in found:
            owner, pid, typ, g, missed = f['owner'], f['pid'], f['typ'], f['g'], f['missed']
            verb, d, d40 = TD[typ]
            p, fl = name(pid), []
            scorer = typ != 'pass'
            live = bool(g) and not missed
            if typ == 'def':
                fl.append('defense')
            if f['long']:
                fl.append('40+ yards')
            if f['first']:
                fl.append('first score of the game')
            if scorer and live and first_scorer_of_week:
                fl.append('first of the week')
                first_scorer_of_week = False
            if f['k'] in MILESTONE and typ != 'def':
                fl.append(MILESTONE[f['k']])
            if typ == 'rush' and live and posn(pid) == 'RB':
                mine = (carries.get(team(pid)) or {}).get(pid, 0)
                if any(a > mine for q, a in (carries.get(team(pid)) or {}).items() if q != pid):
                    fl.append('vulture')
            if live and own_td.get(owner, 0) == 0 and per_owner[owner] == 1 and g['q'] >= 4:
                fl.append('off the schneid')
            if live and g['q'] >= 4 and abs(g['hs'] - g['as']) >= 22:
                fl.append('garbage time')
            text = '%s %s for %s%s.' % (p, verb, owner, ''.join(', ' + x for x in fl))
            if live:
                text += ' %s, %s.' % (g['score'], g['lab'])
            when = None
            if missed and f['at']:
                when = min(now, int(f['at']))
            add('td', owner, pid, text, t=when, n=f['n'], p=p,
                d=(d40 if f['long'] else d), sc=(g['score'] if live else ''), g=(g['lab'] if live else ''))
        for o, n in per_owner.items():
            own_td[o] = own_td.get(o, 0) + n
        s['tdw'] = s.get('tdw', 0) + len(found)

        # ---------- starters at zero ----------
        flags, iced = s['flags'], s['iced']
        seen = set()

        def is_iced(owner, fid):
            return any(x['owner'] == owner and x['id'] == fid for x in iced)

        def confirm(owner, fid, p, pts, why):
            iced.append({'owner': owner, 'id': fid, 'p': p, 'pts': pts})
            what = '%s finished at %s' % (p, num(pts)) if p else 'an empty slot finished at 0.0'
            add('confirmed', owner, fid, '%s is Iced. %s.' % (owner, what), p=p, pts=pts, g=why)
            flags.pop(owner + '|' + fid, None)

        def clear(owner, pid, f, pts, g):
            flags.pop(owner + '|' + pid, None)
            if not f.get('live'):       # only ever seen at zero after the final: nothing to announce
                return
            p = name(pid)
            add('cleared', owner, pid, '%s climbs off zero for %s.' % (p, owner), p=p, pts=(0 if f['pts'] == 0 else f['pts']), g='')
            if 'warning' in f['said'] or 'injury' in f['said']:
                add('averted', owner, pid, '%s gets off zero for %s. Ice averted.' % (p, owner), p=p, pts=pts, g=g['lab'])
            flags.pop(owner + '|' + pid, None)

        for t in ms:
            owner = owners.get(str(t.get('roster_id')))
            if not owner:
                continue
            pp = t.get('players_points') or {}
            for slot, pid in enumerate(t.get('starters') or []):
                empty = (not pid) or pid == '0'
                fid = ('empty-%s-%d' % (owner, slot)) if empty else pid
                key = owner + '|' + fid
                seen.add(key)
                if empty:       # counts once nobody can be put in it any more
                    if now >= last_kick and not is_iced(owner, fid):
                        confirm(owner, fid, '', 0.0, 'EMPTY')
                    continue
                pts = round(float(pp.get(pid) or 0), 2)
                g = G.get(team(pid))
                f = flags.get(key)
                if g is None:   # his team is off this week
                    if now >= first_kick and not is_iced(owner, fid):
                        confirm(owner, fid, name(pid), 0, 'BYE')
                    continue
                if g['st'] == 0:
                    flags.pop(key, None)
                    continue
                if g['st'] == 1:
                    if g['half'] or g['q'] == 2:
                        phase = 'advisory'
                    elif g['q'] <= 1:
                        phase = 'outlook' if g['secs'] <= 450 else None
                    else:
                        phase = 'watch' if g['q'] == 3 else 'warning'
                    if pts <= 0:
                        if not phase:
                            continue
                        if f is None:
                            f = flags[key] = {'lvl': phase, 'pts': pts, 'said': [], 'tm': team(pid)}
                        f['pts'] = pts
                        f['live'] = 1
                        f.pop('final_at', None)
                        if RANK[phase] > RANK[f['lvl']]:
                            f['lvl'] = phase
                        p = name(pid)
                        if f['lvl'] == 'watch' and 'watch' not in f['said']:
                            f['said'].append('watch')
                            add('watch', owner, pid, '%s still at zero for %s, %s.' % (p, owner, g['lab']), p=p, pts=(0 if pts == 0 else pts), g=g['lab'])
                        if f['lvl'] == 'warning' and 'warning' not in f['said']:
                            f['said'].append('warning')
                            add('warning', owner, pid, 'Warning: %s is at zero for %s with the game nearly done.' % (p, owner), p=p, pts=(0 if pts == 0 else pts), g=g['lab'])
                    elif f:
                        clear(owner, pid, f, pts, g)
                    continue
                # his game is over
                if pts <= 0:
                    if is_iced(owner, fid):
                        continue
                    if f is None:
                        f = flags[key] = {'lvl': 'warning', 'pts': pts, 'said': [], 'tm': team(pid)}
                    f['pts'] = pts
                    f.setdefault('final_at', now)
                    if now - f['final_at'] >= CONFIRM_WAIT:
                        confirm(owner, fid, name(pid), (0 if pts == 0 else pts), 'FINAL')
                else:
                    if f:
                        clear(owner, pid, f, pts, g)
                    if is_iced(owner, fid):     # a stat correction after the final
                        was = [x for x in iced if x['owner'] == owner and x['id'] == fid][0]
                        iced.remove(was)
                        p = name(pid)
                        add('overturned', owner, pid, '%s was Iced when %s finished at %s. A stat correction took it back.' % (owner, p, num(was['pts'])), p=p)
                        add('averted', owner, pid, 'Stat correction: %s now has %s. %s is not Iced.' % (p, trim(pts), owner), p=p, pts=pts, g='', fix=1)
        # a lineup change takes its flags, and any Ice called on it, with it
        if len(ms) >= len(owners):
            for key in [k for k in flags if k not in seen]:
                flags.pop(key)
            for x in [x for x in iced if (x['owner'] + '|' + x['id']) not in seen]:
                iced.remove(x)
                self.ev = [e for e in self.ev if not (e['kind'] == 'confirmed' and e['owner'] == x['owner'] and e['id'] == x['id'])]
                new[:] = [e for e in new if not (e['kind'] == 'confirmed' and e['owner'] == x['owner'] and e['id'] == x['id'])]
        # hurt and at zero
        if injury:
            asked = 0
            for key, f in list(flags.items()):
                owner, pid = key.split('|', 1)
                g = G.get(f.get('tm'))
                if asked >= 4 or 'injury' in f['said'] or not g or g['st'] != 1 or now - self.inj_at.get(pid, 0) < 180000:
                    continue
                self.inj_at[pid] = now
                asked += 1
                try:
                    info = injury(pid) or {}
                except Exception:
                    info = {}
                if info.get('injury_status') in HURT:
                    f['said'].append('injury')
                    p = name(pid)
                    add('injury', owner, pid, '%s is hurt. %s is on the hook for an Ice.' % (p, owner), p=p, pts=(0 if f['pts'] == 0 else f['pts']), g=g['lab'])

        # ---------- leads and swings ----------
        by_owner = {owners.get(str(t.get('roster_id'))): t for t in ms}
        for gm in W.get('games') or []:
            ta, tb = by_owner.get(gm['a']), by_owner.get(gm['b'])
            if not ta or not tb:
                continue
            A, B = side(ta, players, G), side(tb, players, G)
            p = win_prob(A, B, gm.get('aw', 50))
            pct = int(round(p * 100))
            key = gm['a'] + '|' + gm['b']
            h = self.hist.setdefault(key, [])
            old = [v for (tt, v) in h if now - tt >= 110000]
            was = old[-1] if old else (h[0][1] if h else int(round(gm.get('aw', 50))))
            lead = s['lead'].get(key)
            cur = 'a' if A['pts'] > B['pts'] else 'b' if B['pts'] > A['pts'] else lead
            said = False
            tw, rw = A['tw'] + B['tw'], A['rw'] + B['rw']
            if cur != lead:
                if lead is not None and not late:
                    X, Y, x, y, px, wx = ((gm['a'], gm['b'], A, B, pct, was) if cur == 'a' else (gm['b'], gm['a'], B, A, 100 - pct, 100 - was))
                    score = '%.2f to %.2f' % (x['pts'], y['pts'])
                    if y['left'] == 0:
                        add('ender', X, '', '%s passes %s, %s. %s is out of players.' % (X, Y, score, Y), vs=Y, sc=score, pct=px, was=wx, note='%s is out of players' % Y)
                    else:
                        add('lead', X, '', '%s takes the lead over %s, %s. %s is %d%% to win.' % (X, Y, score, X, px), vs=Y, sc=score, pct=px, was=wx)
                    said = True
                s['lead'][key] = cur
            aw = gm.get('aw', 50)
            fav = s['fav'].get(key, 'a' if aw >= 60 else 'b' if aw <= 40 else None)
            cand = 'a' if p >= 0.6 else 'b' if p <= 0.4 else None
            if cand and cand != fav:
                under_way = tw > 0 and 0.001 < rw / tw < 0.999
                if under_way and not said and not late:
                    X, Y, x, y, px, wx = ((gm['a'], gm['b'], A, B, pct, was) if cand == 'a' else (gm['b'], gm['a'], B, A, 100 - pct, 100 - was))
                    text = '%s is now %d%% to beat %s' % (X, px, Y) + (', up from %d%%.' % wx if wx < px else '.')
                    add('swing', X, '', text, vs=Y, sc='%.2f to %.2f' % (x['pts'], y['pts']), pct=px, was=wx)
                fav = cand
            s['fav'][key] = fav
            h.append((now, pct))
            self.hist[key] = [(tt, v) for (tt, v) in h if now - tt <= 300000]

        # ---------- wrap up ----------
        live = any(g['st'] == 1 for g in games)
        warn = [f for f in flags.values() if f['lvl'] == 'warning' or 'injury' in f['said']]
        witch = any(f['lvl'] == 'warning' and (G.get(f.get('tm')) or {}).get('st') == 1
                    and ((G[f['tm']]['q'] >= 5) or G[f['tm']]['secs'] <= 300) for f in flags.values())
        self.status = {'week': self.week, 'confirmed': len(iced), 'warnings': len(warn), 'in_play': live, 'live': live,
                       'witching': ['late'] if witch else [], 'built': now}
        s['last'] = now
        new.sort(key=lambda e: e['t'])
        self.ev = list(reversed(new)) + self.ev
        self.ev.sort(key=lambda e: -e['t'])
        return new

    def _retract_td(self, owner, pid, typ, n):
        d = TD[typ][1]
        for _ in range(n):
            for i, e in enumerate(self.ev):
                if e['kind'] == 'td' and e['owner'] == owner and e['id'] == pid and (e.get('d') == d or e.get('d') == TD[typ][2]):
                    del self.ev[i]
                    self.s['own_td'][owner] = max(0, self.s.get('own_td', {}).get(owner, 1) - 1)
                    self.s['tdw'] = max(0, self.s.get('tdw', 1) - 1)
                    break
