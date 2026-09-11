#!/usr/bin/env python3
"""Rebuild the per-event social backgrounds from img/CREDITS.md.

The extension's receiver cover-crops agwas:bg to 9:16, blurs it and blends it toward
near-black before writing its own type over it — so these are the bare photograph,
tinted to the site palette, and never the lettered cards in img/og/.

Source of truth is CREDITS.md: it names the Commons file for each event, so the whole
set is reproducible from the repo alone. Re-run after editing that table.
"""
import io, json, os, re, sys, time, urllib.parse, urllib.request
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(HERE, 'img', 'event')
API  = 'https://commons.wikimedia.org/w/api.php'
UA   = {'User-Agent': 'agwas-athletics-film/1.0 (carlodemarchis@gmail.com)'}
W, H = 1200, 675
SHADOW, HIGH = (13, 8, 6), (226, 144, 63)          # --bg0 through to a warm highlight
LUT = []
for c in range(3):
    LUT += [int(SHADOW[c] + (HIGH[c] - SHADOW[c]) * (i / 255)) for i in range(256)]

slug = lambda s: re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def rows():
    md = open(os.path.join(HERE, 'img', 'CREDITS.md'), encoding='utf-8').read()
    for line in md.splitlines():
        m = re.match(r'\|\s*([^|]+?)\s*\|[^|]*\|[^|]*\|\s*\[([^\]]+)\]', line)
        if m and m.group(1) != 'Event':
            yield m.group(1), m.group(2)

def fetch(title):
    p = dict(action='query', titles='File:' + title, prop='imageinfo',
             iiprop='url', iiurlwidth='1600', format='json')
    req = urllib.request.Request(API + '?' + urllib.parse.urlencode(p), headers=UA)
    pg = list(json.load(urllib.request.urlopen(req, timeout=60))['query']['pages'].values())[0]
    ii = pg['imageinfo'][0]
    src = ii.get('thumburl') or ii['url']
    return urllib.request.urlopen(urllib.request.Request(src, headers=UA), timeout=90).read()

def treat(raw):
    im = Image.open(io.BytesIO(raw)).convert('RGB')
    sw, sh = im.size
    s = max(W / sw, H / sh)
    im = im.resize((max(W, int(sw * s)), max(H, int(sh * s))), Image.LANCZOS)
    w, h = im.size
    top = int(h * 0.10) if h > H else 0
    im = im.crop(((w - W) // 2, top, (w - W) // 2 + W, top + H))
    g = im.convert('L')
    return Image.merge('RGB', [g.point(LUT[i * 256:(i + 1) * 256]) for i in range(3)])

def main():
    os.makedirs(OUT, exist_ok=True)
    n = 0
    for event, title in rows():
        dst = os.path.join(OUT, slug(event) + '.jpg')
        if '--force' not in sys.argv and os.path.exists(dst):
            print(f'  = {event}'); n += 1; continue
        try:
            treat(fetch(title)).save(dst, quality=88, optimize=True)
            print(f'  + {event:20} {os.path.getsize(dst)//1024:4}KB')
            n += 1
        except Exception as e:
            print(f'  ! {event}: {e}')
        time.sleep(.3)
    # the whole-sport stats cards have no event of their own
    generic = os.path.join(OUT, 'marathon.jpg')
    if os.path.exists(generic):
        Image.open(generic).save(os.path.join(OUT, '_all.jpg'), quality=88, optimize=True)
    print(f'{n} event backgrounds in img/event/')

if __name__ == '__main__':
    main()
