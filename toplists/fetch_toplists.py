#!/usr/bin/env python3
"""Pull the World Athletics all-time toplists into toplists/data/toplists.json.

The deck and its order come from the same GraphQL call the record progressions use, so the
two films hold the same events in the same sequence. The lists themselves are scraped: the
toplist pages are server-rendered HTML, and getTopList is not authorised for the public key.

Every mark ever, not one per athlete (bestResultsOnly=false), wind-legal, electronically
timed, down to rank 20 — and never cutting a tie, so a card can hold 21, 23, even 30 rows.
"""
import html, json, os, re, sys, time, urllib.request

EP = "https://graphql-prod-4891.edge.aws.worldathletics.org/graphql"
KEY = "da2-jxuw7sextrh5dkbefsbitcuqoa"          # shipped in worldathletics.org's public JS bundle
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"}

DEPTH = 50                                       # everyone ranked 50th or better, ties included

# the same deck as the record film
EVENTS = [
    "100 Metres", "200 Metres", "400 Metres", "800 Metres", "1500 Metres",
    "5000 Metres", "10,000 Metres", "Marathon",
    "110 Metres Hurdles", "100 Metres Hurdles", "400 Metres Hurdles",
    "High Jump", "Pole Vault", "Long Jump", "Triple Jump",
    "Shot Put", "Discus Throw", "Hammer Throw", "Javelin Throw",
    "Decathlon", "Heptathlon", "4x100 Metres Relay", "4x400 Metres Relay",
]
EXCLUDE = {("women", "Decathlon"), ("men", "Heptathlon")}

# discipline -> the toplist URL's own group/slug pair
SLUG = {
    "100 Metres": "sprints/100-metres", "200 Metres": "sprints/200-metres",
    "400 Metres": "sprints/400-metres", "800 Metres": "middlelong/800-metres",
    "1500 Metres": "middlelong/1500-metres", "5000 Metres": "middlelong/5000-metres",
    "10,000 Metres": "middlelong/10000-metres", "Marathon": "road-running/marathon",
    "110 Metres Hurdles": "hurdles/110-metres-hurdles",
    "100 Metres Hurdles": "hurdles/100-metres-hurdles",
    "400 Metres Hurdles": "hurdles/400-metres-hurdles",
    "High Jump": "jumps/high-jump", "Pole Vault": "jumps/pole-vault",
    "Long Jump": "jumps/long-jump", "Triple Jump": "jumps/triple-jump",
    "Shot Put": "throws/shot-put", "Discus Throw": "throws/discus-throw",
    "Hammer Throw": "throws/hammer-throw", "Javelin Throw": "throws/javelin-throw",
    "Decathlon": "combined-events/decathlon", "Heptathlon": "combined-events/heptathlon",
    "4x100 Metres Relay": "relays/4x100-metres-relay",
    "4x400 Metres Relay": "relays/4x400-metres-relay",
}

QS = ("?regionType=world&timing=electronic&windReading=regular&page={page}"
      "&bestResultsOnly={best}&firstDay=1900-01-01&lastDay={last}"
      "&maxResultsByCountry=all&ageCategory=senior")


def gql(query, tries=4):
    req = urllib.request.Request(EP, data=json.dumps({"query": query}).encode(),
                                 headers={"x-api-key": KEY, "Content-Type": "application/json"})
    for n in range(tries):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=30))
            break
        except urllib.error.URLError:
            if n == tries - 1:
                raise
            time.sleep(2 * (n + 1))
    if d.get("errors"):
        raise RuntimeError(d["errors"][0]["message"])
    return d["data"]


def discipline_index():
    """In World Athletics' own order — discipline group, then discipline."""
    d = gql("{getRecordsDisciplineList{gender disciplineTypes{name disciplines{eventId name}}}}")
    out = []
    for g in d["getRecordsDisciplineList"]:
        rank = 0
        for t in g["disciplineTypes"]:
            for x in t["disciplines"]:
                if x["name"] in EVENTS and (g["gender"], x["name"]) not in EXCLUDE:
                    out.append({"gender": g["gender"], "discipline": x["name"],
                                "eventId": int(x["eventId"]), "group": t["name"], "order": rank})
                    rank += 1
    return out


def clean(s):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', s)).split())


def fetch(path, gender, last_day, page_no, best, tries=3):
    url = f"https://worldathletics.org/records/all-time-toplists/{path}/all/{gender}/senior" \
          + QS.format(last=last_day, page=page_no, best="true" if best else "false")
    for n in range(tries):
        try:
            return url, urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                               timeout=45).read().decode("utf-8", "replace")
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(2 * (n + 1))


def toplist(path, gender, last_day, best=False):
    """A page holds 100 rows. A deep cut through a field event can tie its way past that,
    so keep turning pages until one ends below the cut.

    best=False is every mark ever set. best=True is one row per athlete, their best — the
    same fifty ranks read as fifty people instead of fifty performances."""
    rows, url, page_no = [], None, 1
    while True:
        url1, page = fetch(path, gender, last_day, page_no, best)
        if page_no == 1:
            url = url1
        got = parse_rows(page)
        rows += got
        if len(got) < 100 or (got and got[-1]["rank"] > DEPTH) or page_no >= 4:
            break
        page_no += 1
        time.sleep(.45)
    return [r for r in rows if r["rank"] <= DEPTH], url


def parse_rows(page):
    rows = []
    for tr in re.findall(r'<tr>(.*?)</tr>', page, re.S):
        if 'data-th="Rank"' not in tr:
            continue
        cell = {m.group(1): m.group(2) for m in
                re.finditer(r'<td data-th="([^"]*)"[^>]*>(.*?)</td>', tr, re.S)}
        rank = re.sub(r'\D', '', clean(cell.get("Rank", "")))
        if not rank:
            continue
        who = cell.get("Competitor", "")
        # two link shapes in the same table: /athletes/athlete=14209691 and
        # /athletes/united-states/cooper-lutkenhaus-15152457
        aid = re.search(r'href="/athletes/[^"]*?(\d{6,})', who)
        venue = clean(cell.get("Venue", ""))
        rows.append({
            "rank": int(rank),
            "mark": clean(cell.get("Mark", "")),
            "wind": clean(cell.get("WIND", "")) or None,
            "name": clean(who),
            "id": int(aid.group(1)) if aid else None,
            "dob": clean(cell.get("DOB", "")) or None,
            "nat": clean(cell.get("Nat", "")),
            "pos": clean(cell.get("Pos", "")) or None,
            "venue": venue,
            "date": clean(cell.get("Date", "")),
            "score": clean(cell.get("Results Score", "")) or None,
            "indoor": venue.endswith("(i)"),
        })
    return rows


def main():
    last_day = time.strftime("%Y-%m-%d")
    cards = []
    for e in discipline_index():
        path = SLUG.get(e["discipline"])
        if not path:
            print(f"  !! no toplist slug for {e['discipline']}", file=sys.stderr)
            continue
        rows, url = toplist(path, e["gender"], last_day)
        if not rows:
            print(f"  !! empty list: {e['gender']} {e['discipline']}", file=sys.stderr)
            continue
        time.sleep(.45)
        once, _ = toplist(path, e["gender"], last_day, best=True)
        people = len({r["name"] for r in rows})
        print(f"  {e['gender']:5} {e['discipline']:20} {len(rows):3} marks by {people:2}"
              f"  |{len(once):4} performers   {rows[0]['mark']} … {rows[-1]['mark']}")
        cards.append({**e, "slug": path.split("/")[1], "source": url,
                      "rows": rows, "once": once})
        time.sleep(.45)

    out = {"fetched": last_day, "depth": DEPTH, "cards": cards}
    dest = os.path.join(HERE, "data", "toplists.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{len(cards)} cards, {sum(len(c['rows']) for c in cards)} performances, "
          f"{sum(len(c['once']) for c in cards)} performers -> {dest}")


if __name__ == "__main__":
    main()
