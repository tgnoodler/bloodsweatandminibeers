"""Folds the Peanut Night votes posted to ntfy.sh into votes.json so they outlive ntfy's 12-hour cache.
Run by .github/workflows/peanut-votes.yml; safe to run by hand from the repo root: python3 peanut/persist.py"""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOPIC = json.load(open(os.path.join(HERE, 'topic.json')))['topic']
PATH = os.path.join(HERE, 'votes.json')
data = json.load(open(PATH)) if os.path.exists(PATH) else {'updated': 0, 'votes': {}}
votes = data.setdefault('votes', {}); before = json.dumps(votes, sort_keys=True)

raw = urllib.request.urlopen(f'https://ntfy.sh/{TOPIC}/json?poll=1&since=all', timeout=30).read().decode('utf-8', 'replace')
msgs = []
for line in raw.splitlines():
    try: m = json.loads(line)
    except ValueError: continue
    if m.get('event') != 'message': continue
    try: v = json.loads(m.get('message', ''))
    except ValueError: continue
    if isinstance(v, dict): msgs.append((int(m.get('time', 0)), v))
for t, v in sorted(msgs, key=lambda x: x[0]):
    name = str(v.get('name', '')).strip()[:40]
    if not name: continue
    cur = next((n for n in votes if n.lower() == name.lower()), None)
    if cur and int(votes[cur].get('t', 0)) >= t: continue
    if cur: del votes[cur]
    if v.get('remove'): continue
    votes[name] = {'games': [str(g)[:12] for g in (v.get('games') or [])][:40], 'note': str(v.get('note', ''))[:140], 't': t}
if json.dumps(votes, sort_keys=True) != before:
    data['updated'] = int(time.time())
    json.dump(data, open(PATH, 'w'), indent=1, sort_keys=True)
    print(f'votes.json updated: {len(votes)} names')
else:
    print('no change')
