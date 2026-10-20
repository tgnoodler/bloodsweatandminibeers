"""Folds the Ghost Desk saves posted to ntfy.sh into desk.json so they outlive ntfy's 12-hour cache.
Run by .github/workflows/ghost-desk.yml; safe to run by hand from the repo root: python3 ghost/persist.py"""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOPIC = json.load(open(os.path.join(HERE, 'topic.json')))['topic']
PATH = os.path.join(HERE, 'desk.json')
data = json.load(open(PATH)) if os.path.exists(PATH) else {'updated': 0, 'weeks': {}}
weeks = data.setdefault('weeks', {}); before = json.dumps(weeks, sort_keys=True)

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
    wk = str(v.get('week', ''))[:3]; sid = str(v.get('id', ''))[:12]
    if not wk.isdigit() or not sid: continue
    cur = weeks.setdefault(wk, {}).get(sid)
    if cur and int(cur.get('t', 0)) >= t: continue
    weeks[wk][sid] = {'name': str(v.get('name', ''))[:40], 'pick': v.get('pick') if isinstance(v.get('pick'), int) else None,
                      'title': str(v.get('title', ''))[:140], 'deck': str(v.get('deck', ''))[:220], 'image': str(v.get('image', ''))[:300],
                      'draft': str(v.get('draft', ''))[:3000], 'taken': bool(v.get('taken')), 't': t}
if json.dumps(weeks, sort_keys=True) != before:
    data['updated'] = int(time.time())
    json.dump(data, open(PATH, 'w'), indent=1, sort_keys=True)
    print('desk.json updated')
else:
    print('no change')
