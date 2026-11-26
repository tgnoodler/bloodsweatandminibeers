"""Replays a made-up game day through the engine and checks the Rundown it writes.  python3 scoreboard/test_engine.py"""
import copy, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from engine import Engine

engine.LATE_GAP = 10 ** 12     # the made-up day skips ahead in big steps; a real run ticks every 20 seconds

MIN = 60000
K = 1_000_000_000_000           # kickoff of the early game
W = {'owners': {'1': 'Ann', '2': 'Bob', '3': 'Cy', '4': 'Dee'},
     'players': {'q1': {'n': 'Quinn One', 't': 'AAA', 'pr': 18}, 'r1': {'n': 'Rex Lead', 't': 'AAA', 'pr': 12},
                 'r2': {'n': 'Ray Backup', 't': 'AAA', 'pr': 4}, 'w1': {'n': 'Wes Wide', 't': 'AAA', 'pr': 10},
                 'w2': {'n': 'Zed Zero', 't': 'BBB', 'pr': 8}, 'k1': {'n': 'Kit Kicker', 't': 'BBB', 'pr': 8},
                 'BBB': {'n': 'BBB DEF', 't': 'BBB', 'pr': 6}, 'x1': {'n': 'Late Guy', 't': 'CCC', 'pr': 15},
                 'x2': {'n': 'Other Late', 't': 'DDD', 'pr': 15}, 'x3': {'n': 'Sub Guy', 't': 'CCC', 'pr': 7}, 'bye1': {'n': 'Bye Guy', 't': 'ZZZ', 'pr': 9}},
     'pos': {'q1': 'QB', 'r1': 'RB', 'r2': 'RB', 'w1': 'WR', 'w2': 'WR', 'k1': 'K', 'BBB': 'DEF', 'x1': 'WR', 'x2': 'WR', 'x3': 'WR', 'bye1': 'RB'},
     'games': [{'a': 'Ann', 'b': 'Bob', 'aw': 55, 'ap': 40, 'bp': 30}, {'a': 'Cy', 'b': 'Dee', 'aw': 50, 'ap': 20, 'bp': 20}]}


def game(home, away, kick, q=0, clock='15:00', hs=0, as_=0, over=False, half=False):
    started = q > 0 or over
    return {'status': 'complete' if over else 'in_game' if started else 'pre_game', 'start_time': kick,
            'metadata': {'home_team': home, 'away_team': away, 'home_score': hs, 'away_score': as_, 'quarter_num': q,
                         'time_remaining': clock, 'is_over': over, 'has_started': started, 'is_in_progress': started and not over,
                         'quarter': 'H' if half else str(q)}}


def roster(rid, starters, pts):
    return {'roster_id': rid, 'starters': starters, 'players': starters, 'players_points': dict(pts)}


def stat(pid, team, pos, **st):
    return {'player_id': pid, 'team': team, 'stats': st, 'player': {'position': pos, 'first_name': pid, 'last_name': ''}}


E = Engine(12, W)
log = []


def tick(minute, sc, ms, stats, injury=None):
    new = E.tick(K + minute * MIN, sc, ms, stats, injury)
    for e in new:
        log.append(e)
        print('  +%3d  %-10s %s' % (minute, e['kind'], e['text']))
    return new


late_kick = K + 200 * MIN
def sched(early, late=None):
    return [early, late or game('DDD', 'CCC', late_kick)]

ann = ['q1', 'r2', 'w1']; bob = ['r1', 'w2', 'BBB']; cy = ['x1', 'bye1']; dee = ['x2', '0']
def lineups(a, b, c=None, d=None, cy_=None):
    return [roster(1, ann, a), roster(2, bob, b), roster(3, cy_ or cy, c or {}), roster(4, dee, d or {})]

print('before kickoff')
tick(-20, sched(game('BBB', 'AAA', K)), lineups({}, {}), [])
assert not log
print('kickoff: a starter whose team is off this week is an Ice straight away')
n = tick(1, sched(game('BBB', 'AAA', K, 1, '14:00')), lineups({}, {}), [])
assert [e['kind'] for e in n] == ['confirmed'] and n[0]['g'] == 'BYE' and n[0]['owner'] == 'Cy'
print('first touchdown: a 45-yard catch, thrown by a starter on the same team')
st = [stat('q1', 'AAA', 'QB', pass_td=1, pass_td_40p=1), stat('w1', 'AAA', 'WR', rec_td=1, rec_td_40p=1, first_td=1), stat('r1', 'AAA', 'RB', rush_att=6), stat('r2', 'AAA', 'RB', rush_att=1)]
n = tick(6, sched(game('BBB', 'AAA', K, 1, '9:30', 0, 6)), lineups({'q1': 5.8, 'w1': 11.5}, {'r1': 2.1}), st)
td = [e for e in n if e['kind'] == 'td']
assert len(td) == 2 and all(e['n'] == 2 for e in td)
catch = [e for e in td if e['id'] == 'w1'][0]; throw = [e for e in td if e['id'] == 'q1'][0]
assert catch['text'] == 'Wes Wide catches a touchdown for Ann, 40+ yards, first score of the game, first of the week. AAA 6, BBB 0, Q1 9:30.', catch['text']
assert throw['text'] == 'Quinn One throws a touchdown for Ann, 40+ yards. AAA 6, BBB 0, Q1 9:30.', throw['text']
assert catch['d'] == '40+ yard catch' and catch['sc'] == 'AAA 6, BBB 0' and catch['g'] == 'Q1 9:30'
print('late first quarter: starters still at zero go on the radar quietly; the backup back vultures one')
st2 = [stat('q1', 'AAA', 'QB', pass_td=1, pass_td_40p=1), stat('w1', 'AAA', 'WR', rec_td=1, rec_td_40p=1, first_td=1), stat('r1', 'AAA', 'RB', rush_att=9), stat('r2', 'AAA', 'RB', rush_att=2, rush_td=1)]
n = tick(20, sched(game('BBB', 'AAA', K, 1, '4:00', 0, 13)), lineups({'q1': 6.5, 'w1': 11.5, 'r2': 6.3}, {'r1': 4.4}), st2)
assert [e['kind'] for e in n] == ['td'] and n[0]['text'] == 'Ray Backup runs one in for Ann, vulture. AAA 13, BBB 0, Q1 4:00.', n[0]['text']
assert set(E.s['flags']) == {'Bob|w2', 'Bob|BBB'}
print('second quarter: the defense gets on the board, which clears it')
n = tick(40, sched(game('BBB', 'AAA', K, 2, '8:00', 0, 13)), lineups({'q1': 8, 'w1': 11.5, 'r2': 6.3}, {'r1': 5, 'BBB': 1.0}), st2)
assert [(e['kind'], e['id']) for e in n] == [('cleared', 'BBB')] and n[0]['text'] == 'BBB DEF climbs off zero for Bob.'
print('halftime, then the third quarter: still at zero is an Ice watch')
tick(60, sched(game('BBB', 'AAA', K, 2, '0:00', 0, 13, half=True)), lineups({'q1': 9, 'w1': 11.5, 'r2': 6.3}, {'r1': 6, 'BBB': 1.0}), st2)
n = tick(75, sched(game('BBB', 'AAA', K, 3, '15:00', 0, 13)), lineups({'q1': 9, 'w1': 11.5, 'r2': 6.3}, {'r1': 6, 'BBB': 1.0}), st2)
assert [e['kind'] for e in n] == ['watch'] and n[0]['text'] == 'Zed Zero still at zero for Bob, Q3 15:00.'
print('fourth quarter: warning, a lead change, and the quarterback piles on in garbage time')
st3 = [stat('q1', 'AAA', 'QB', pass_td=3, pass_td_40p=1), stat('w1', 'AAA', 'WR', rec_td=1, rec_td_40p=1, first_td=1), stat('r1', 'AAA', 'RB', rush_att=20, rush_td=2), stat('r2', 'AAA', 'RB', rush_att=3, rush_td=1)]
n = tick(100, sched(game('BBB', 'AAA', K, 3, '2:00', 0, 34)), lineups({'q1': 17, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0}), st3)
kinds = [e['kind'] for e in n]
assert kinds.count('td') == 4 and 'lead' in kinds, kinds
lead = [e for e in n if e['kind'] == 'lead'][0]
assert lead['text'].startswith('Bob takes the lead over Ann, 39.00 to 34.80. Bob is ') and lead['vs'] == 'Ann'
assert any('hat trick' in e['text'] for e in n if e['id'] == 'q1')
n = tick(110, sched(game('BBB', 'AAA', K, 4, '14:50', 0, 34)), lineups({'q1': 17, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0}), st3)
assert [e['kind'] for e in n] == ['warning'] and n[0]['text'] == 'Warning: Zed Zero is at zero for Bob with the game nearly done.' and n[0]['g'] == 'Q4 14:50'
st4 = copy.deepcopy(st3); st4[0]['stats']['pass_td'] = 4
n = tick(120, sched(game('BBB', 'AAA', K, 4, '9:00', 0, 41)), lineups({'q1': 21, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0}), st4)
assert n[0]['text'] == 'Quinn One throws a touchdown for Ann, grand slam, garbage time. AAA 41, BBB 0, Q4 9:00.', n[0]['text']
assert E.status['warnings'] == 1 and E.status['in_play'] and E.status['confirmed'] == 1
print('the final: nothing is called until the stats have had a minute to settle')
fin = sched(game('BBB', 'AAA', K, 4, '0:00', 0, 41, over=True))
n = tick(150, fin, lineups({'q1': 21, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0}), st4)
assert not n
n = tick(152, fin, lineups({'q1': 21, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0}), st4)
assert [e['kind'] for e in n] == ['confirmed'] and n[0]['text'] == 'Bob is Iced. Zed Zero finished at 0.' and n[0]['g'] == 'FINAL'
print('a stat correction gives him a catch: the Ice comes off')
n = tick(160, fin, lineups({'q1': 21, 'w1': 11.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0, 'w2': 1.5}), st4)
assert [e['kind'] for e in n] == ['overturned', 'averted'], [e['kind'] for e in n]
assert n[0]['text'] == 'Bob was Iced when Zed Zero finished at 0. A stat correction took it back.'
assert n[1]['text'] == 'Stat correction: Zed Zero now has 1.5. Bob is not Iced.' and n[1].get('fix')
assert [x['owner'] for x in E.s['iced']] == ['Cy']
print('Ann gets a late stat correction and passes Bob, who has nobody left')
n = tick(170, fin, lineups({'q1': 21, 'w1': 14.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0, 'w2': 1.5}), st4)
assert [e['kind'] for e in n] == ['ender'] and n[0]['text'] == 'Ann passes Bob, 41.80 to 40.50. Bob is out of players.', n[0]['text']
print('Cy swaps the bye-week starter out before the late game: that Ice is withdrawn')
n = tick(180, fin, lineups({'q1': 21, 'w1': 14.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0, 'w2': 1.5}, cy_=['x1', 'x3']), st4)
assert not E.s['iced'] and not any(e['kind'] == 'confirmed' and e['owner'] == 'Cy' for e in E.ev)
print('the last game kicks off: the empty slot is an Ice; a hurt starter at zero is flagged')
lg = game('DDD', 'CCC', late_kick, 1, '5:00')
n = tick(215, sched(fin[0], lg), lineups({'q1': 21, 'w1': 14.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0, 'w2': 1.5}, cy_=['x1', 'x3'], c={'x3': 3.0}), st4,
         injury=lambda pid: {'injury_status': 'Out'} if pid == 'x1' else {})
kinds = sorted(e['kind'] for e in n)
assert {'confirmed', 'injury'} <= set(kinds), kinds
assert [e for e in n if e['kind'] == 'confirmed'][0]['text'] == 'Dee is Iced. an empty slot finished at 0.0.'
assert [e for e in n if e['kind'] == 'injury'][0]['text'] == 'Late Guy is hurt. Cy is on the hook for an Ice.'
print('a second engine picks up from the saved state and does not repeat anything')
E2 = Engine(12, W, copy.deepcopy(E.s), copy.deepcopy(E.feed()))
again = E2.tick(K + 216 * MIN, sched(fin[0], lg), lineups({'q1': 21, 'w1': 14.5, 'r2': 6.3}, {'r1': 38, 'BBB': 1.0, 'w2': 1.5}, cy_=['x1', 'x3'], c={'x3': 3.0}), st4)
assert not again, again
f = E.feed()
assert f['tds'] == sum(1 for e in f['ev'] if e['kind'] == 'td') == 8 and f['ev'][0]['t'] >= f['ev'][-1]['t']
print('\nall checks passed:', len(log), 'entries written,', f['tds'], 'touchdowns,', len(f['iced']), 'Iced')
