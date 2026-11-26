#!/usr/bin/env python3
"""The Weekly Report, from the cloud.

When a week is over this makes sure its report card exists (recap/wkN.html and the picture, recap/wkN.png) and builds
report.html, the Weekly Report page, on the newest card there is. The home computer normally draws the card itself a
little after Monday's game; this only draws one if that has not happened five hours after the last kickoff. The
regular build's own page, recap.html, has been stuck a week or two behind, and it rewrites that file on every run,
which is why the cloud page lives at report.html instead.

Run from the repo root:  python3 scoreboard/report.py
"""
import glob, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sleeper import get, now_ms, read_json

HERE = 'scoreboard/'
MARK = '<!--cloud-->'
WAIT_MS = 5 * 3600 * 1000
slug = lambda n: n.lower().replace(' ', '-')


def weeks_with_cards():
    return sorted(int(re.search(r'wk(\d+)\.png$', f).group(1)) for f in glob.glob('recap/wk*.png'))


def card(template, week, ms, owners, iced):
    """Last week's card with this week's numbers in it."""
    tot = sorted(((round(float(t.get('points') or 0), 2), owners[str(t['roster_id'])]) for t in ms), reverse=True)
    (p1, o1), (p2, o2), (p3, o3) = tot[:3]
    spot = lambda n, o, p, first: ('<div class="p %s"><div class="n">%d</div><div class="ph" style="background-image:url(f-%s.jpg)"></div><b>%s</b><i>%.2f</i></div>'
                                   % ('first' if first else '', n, slug(o), o, p))
    pod = '<div class="pod">' + spot(2, o2, p2, False) + spot(1, o1, p1, True) + spot(3, o3, p3, False) + '</div>'
    m = round(p1 - p2, 2)
    say = '%s took the high score and the $50 over %s by %s%s.' % (
        o1, o2, ('%.1f' % m) if m >= 10 else ('%.2f' % m),
        ', and it was never close' if m >= 15 else ', the narrowest of margins' if m < 1 else '')
    if iced:
        rows = ''.join('<div class="r"><div class="ph" style="background-image:url(f-%s.jpg)"></div><div><b>%s</b><span>%s, %.1f</span></div><span class="tg">Owes one</span></div>'
                       % (slug(x['owner']), x['owner'], x.get('p') or 'Empty slot', float(x.get('pts') or 0)) for x in iced)
    else:
        rows = '<div class="none">Nobody was Iced this week.</div>'
    s = template.replace(MARK, '')
    s = re.sub(r'<span>Week \d+ report &middot; (\d+)</span>', lambda mm: '<span>Week %d report &middot; %s</span>' % (week, mm.group(1)), s, count=1)
    s = re.sub(r'<h1>Week \d+</h1>', '<h1>Week %d</h1>' % week, s, count=1)
    s = re.sub(r'<div class="pod">.*?</i></div></div>', lambda mm: pod, s, count=1, flags=re.S)
    s = re.sub(r'<p class="say">.*?</p>', lambda mm: '<p class="say">%s</p>' % say, s, count=1, flags=re.S)
    s = re.sub(r'(<div class="ice"><h2>Ice report</h2>).*?(</div><div class="ft">)', lambda mm: mm.group(1) + rows + mm.group(2), s, count=1, flags=re.S)
    s = re.sub(r"<script>if\('serviceWorker'.*?</script>", '', s, flags=re.S)
    return s.replace('</body>', MARK + '</body>', 1)


def draw(html_path, png_path):
    """Take the card's picture with headless Chrome: 540 wide at double density, as tall as the card."""
    exe = next((shutil.which(x) for x in ('google-chrome', 'chromium', 'chromium-browser', 'chrome') if shutil.which(x)), None)
    if not exe:
        print('no Chrome here; picture not drawn'); return False
    src = open(html_path).read()
    base = ['--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--virtual-time-budget=8000']
    with tempfile.TemporaryDirectory(dir='recap') as d:        # next to the card, so its photos resolve
        probe = os.path.join(d, 'probe.html')
        open(probe, 'w').write(src.replace('</body>', "<script>addEventListener('load',function(){document.title='H'+document.documentElement.scrollHeight})</script></body>"))
        fixed = src.replace('url(f-', 'url(../f-')
        open(probe, 'w').write(open(probe).read().replace('url(f-', 'url(../f-'))
        out = subprocess.run([exe] + base + ['--dump-dom', 'file://' + os.path.abspath(probe)], capture_output=True, text=True, timeout=120).stdout
        m = re.search(r'<title>H(\d+)</title>', out)
        h = int(m.group(1)) if m else 762
        page = os.path.join(d, 'card.html')
        open(page, 'w').write(fixed)
        tmp = os.path.join(d, 'card.png')
        subprocess.run([exe] + base + ['--force-device-scale-factor=2', '--window-size=540,%d' % h, '--screenshot=' + os.path.abspath(tmp),
                                       'file://' + os.path.abspath(page)], capture_output=True, text=True, timeout=120)
        if not os.path.exists(tmp) or os.path.getsize(tmp) < 20000:
            print('picture did not come out; leaving it for the next run'); return False
        shutil.move(tmp, png_path)
    return True


def page(s, n):
    """recap.html, moved on to week n."""
    m = re.search(r'\bW=(\d+),', s)
    if not m:
        return None
    cur = int(m.group(1))
    if cur < n:
        s = s.replace('>Week %d</h1>' % cur, '>Week %d</h1>' % n)
        s = s.replace('src="recap/wk%d.png" alt="Week %d report"' % (cur, cur), 'src="recap/wk%d.png" alt="Week %d report"' % (n, n))
        s = s.replace('href="recap/wk%d.png" download="bsmb-week-%d.png"' % (cur, cur), 'href="recap/wk%d.png" download="bsmb-week-%d.png"' % (n, n))
        links = ''.join('<a href="#wk%d" data-w="%d"%s>Week %d</a>' % (w, w, ' class="on"' if w == n else '', w) for w in range(n, cur, -1))
        s = s.replace('<a href="#wk%d" data-w="%d" class="on">Week %d</a>' % (cur, cur, cur), links + '<a href="#wk%d" data-w="%d">Week %d</a>' % (cur, cur, cur))
        s = re.sub(r'\bW=%d,' % cur, 'W=%d,' % n, s, count=1)
    s = s.replace('href="sunday.html"', 'href="scoreboard.html"')
    if '/sw.js' not in s:
        s = s.replace('</body>', "<script>if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){})}</script></body>", 1)
    return s


def main():
    W = read_json(HERE + 'week.json') or {}
    week, season = W.get('week'), W.get('season')
    if week:
        sc = get('/scores/nfl/regular/%s/%d' % (season, week))
        over = bool(sc) and all((g.get('status') == 'complete' or (g.get('metadata') or {}).get('is_over')) for g in sc)
        html, png = 'recap/wk%d.html' % week, 'recap/wk%d.png' % week
        ours = os.path.exists(html) and MARK in open(html).read()
        late = over and now_ms() >= max(g['start_time'] for g in sc) + WAIT_MS
        if late and (ours or not os.path.exists(png)):
            done = weeks_with_cards()
            src = 'recap/wk%d.html' % max([w for w in done if w != week] or [0])
            feed = read_json(HERE + 'wire.json') or {}
            if os.path.exists(src) and feed.get('week') == week:
                new = card(open(src).read(), week, get('/v1/league/%s/matchups/%d' % (W['league'], week)), W['owners'], feed.get('iced') or [])
                if not os.path.exists(html) or open(html).read() != new or not os.path.exists(png):
                    open(html, 'w').write(new)
                    print('weekly report card for week', week, 'drawn' if draw(html, png) else 'written, picture pending')
    cards = weeks_with_cards()
    recap = open('recap.html').read() if os.path.exists('recap.html') else ''
    if cards and recap:
        out = page(recap, cards[-1])
        if out and (not os.path.exists('report.html') or open('report.html').read() != out):
            open('report.html', 'w').write(out)
            print('report.html -> week', cards[-1])


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('weekly report skipped:', repr(e))
