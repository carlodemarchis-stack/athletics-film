#!/usr/bin/env python3
"""World Athletics Ultimate Championship 2026 — timetable, results and athlete photos.

Three sources, because no single one has everything:

  1. the timetable, from the public GraphQL — every phase of all three days, with the
     flags that say whether a start list or a result has been published yet
  2. the results, scraped from the server-rendered calendar-results page — the GraphQL
     query that returns them (getLivePhaseSummary) is Unauthorized on every public key
  3. athlete photos, from the same GraphQL, keyed by the WA id that only appears at the
     end of a competitor's urlSlug (NOT iaafId, which is a different id space entirely)

Start lists for events that have not been run are not available anywhere public yet.
"""
import json, os, re, sys, time, urllib.request

EP   = "https://graphql-prod-4891.edge.aws.worldathletics.org/graphql"
KEY  = "da2-jxuw7sextrh5dkbefsbitcuqoa"      # see fetch_records.py for how to refresh these
COMP = 7212925                                # eventId_WA of the 2026 Ultimate Championship
RESULTS_URL = f"https://worldathletics.org/competition/calendar-results/results/{COMP}"
PF_URL = f"https://media.aws.iaaf.org/competitiondocuments/photofinish/{COMP}/"
PF_CODE = {"100 Metres": "100", "200 Metres": "200", "400 Metres": "400", "800 Metres": "800",
           "1500 Metres": "1500", "5000 Metres": "5000", "100 Metres Hurdles": "100H",
           "110 Metres Hurdles": "110H", "400 Metres Hurdles": "400H",
           "4x100 Metres Relay": "4X1", "4x400 Metres Relay": "4X4"}
UA   = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))

def gql(query, variables=None, tries=4):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for a in range(tries):
        try:
            req = urllib.request.Request(EP, data=body,
                headers={"x-api-key": KEY, "Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if d.get("errors") and d.get("data") is None:
                raise RuntimeError(d["errors"][0].get("message", "?")[:120])
            return d["data"]
        except urllib.error.URLError:                 # the sandbox drops DNS now and then
            if a == tries - 1: raise
            time.sleep(2 + a * 2)

def next_data(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    m = re.search(r'__NEXT_DATA__[^>]*>(\{.*?\})</script>', html, re.S)
    if not m: raise RuntimeError("no __NEXT_DATA__ at " + url)
    return json.loads(m.group(1))

def timetable():
    # the API's eventPhase is a leaner type than the Phase the website ships in its page
    # data: no dayNum and no isTrack/isField flags, so the day comes off the date and the
    # discipline type comes from the page's own discipline list instead.
    q = """query($e:Int){getEventTimetable(eventId:$e){
        id phaseCode phaseName status sexCode sexName phaseDateAndTime
        discipline{ _id name typeCode typeName order isTrack isField isRoad isWind isRelay isCombined }
        isStartlistPublished isResultPublished isPhaseSummaryPublished
        phaseOrder phaseSessionName unitName unitTypeName phaseNameUrlSlug}}"""
    rows = gql(q, {"e": COMP})["getEventTimetable"]
    days = sorted({(r.get("phaseDateAndTime") or "")[:10] for r in rows if r.get("phaseDateAndTime")})
    for r in rows:
        d = (r.get("phaseDateAndTime") or "")[:10]
        r["dayNum"] = days.index(d) + 1 if d in days else None
        r["date"] = d
    return rows

def results(ndays):
    # the page shows ONE day at a time and defaults to the first, and its own day list only ever
    # names the days up to the one asked for — so walk the days the timetable knows about.
    # Without this the deck stopped at day 1 while the meet was still running.
    out, seen, days = [], {}, []
    for n in range(1, ndays + 1):
        try:
            pp = next_data(f"{RESULTS_URL}?day={n}")["props"]["pageProps"]["calendarEventsResults"]
        except Exception as e:
            print(f"  ! day {n}: {e}"); continue
        got = day_events(pp)
        if not got: continue
        days = [d["date"] for d in (pp.get("options") or {}).get("days", [])] or days
        for ev in got:
            k = (ev["sex"], ev["event"])
            if k in seen:                       # semifinals one day, the final the next
                have = {(r["name"], r["n"]) for r in seen[k]["races"]}
                seen[k]["races"] += [r for r in ev["races"] if (r["name"], r["n"]) not in have]
            else:
                seen[k] = ev; out.append(ev)
    return out, days

def topup(res, tt):
    """Whatever the day pages have not caught up with, straight from the API.

    The calendar page is the only place with athlete url slugs, so it stays the primary source —
    but it lags: both 200m finals and the women's triple jump were still showing semifinals there
    hours after they were run and published. Any phase the timetable calls published and the day
    pages have not got is filled in here.
    """
    by = {(e["sex"], re.sub(r"^(Men's |Women's |Mixed )", "", e["event"])): e for e in res}
    added = 0
    for p in tt:
        if not p.get("isResultPublished"): continue
        sex, disc = p["sexCode"], p["discipline"]["name"]
        fin = isFinal(p["phaseName"])
        ev = by.get((sex, disc))
        if ev and any(isFinal(r["name"]) == fin for r in ev["races"]): continue
        q = """query($e:Int,$d:String,$s:String,$p:String){
          getEventPhaseByDiscipline(eventId:$e, disciplineCode:$d, sexCode:$s, phaseCode:$p){
            units{ unitCode results{ competitorName competitorId_WA resultCountryCode
              resultMark resultRank resultWind record qualified } } }}"""
        try:
            ph = gql(q, {"e": COMP, "d": slugify(disc), "s": sex,
                         "p": "final" if fin else "semifinal"}) or {}
            ph = ph.get("getEventPhaseByDiscipline") or {}
        except Exception as ex:
            print(f"  ! topup {sex} {disc}: {ex}"); continue
        races = []
        for n, u in enumerate(ph.get("units") or [], 1):
            rows = []
            for x in (u.get("results") or []):
                rank = x.get("resultRank")
                rows.append(dict(place=f"{rank}." if rank else None, name=x.get("competitorName"),
                    wa=x.get("competitorId_WA"), slug=None, nat=x.get("resultCountryCode"),
                    mark=x.get("resultMark"), wind=x.get("resultWind"),
                    record=x.get("record") or "", qualified=x.get("qualified"),
                    remark=None if rank else x.get("resultMark"), points=None))
            if rows: races.append(dict(name="Final" if fin else "Semifinal - Heat", n=n,
                                       wind=rows[0].get("wind"), rows=rows))
        if not races: continue
        if not ev:
            who = {"M": "Men's ", "W": "Women's ", "X": "Mixed "}.get(sex, "")
            ev = dict(event=who + disc, sex=sex, relay=bool(p["discipline"].get("isRelay")),
                      withWind=bool(p["discipline"].get("isWind")), races=[])
            res.append(ev); by[(sex, disc)] = ev
        ev["races"] += races
        added += sum(len(r["rows"]) for r in races)
        print(f"  + {sex} {disc} {p['phaseName']}: {sum(len(r['rows']) for r in races)} rows from the API")
    return added

def day_events(pp):
    out = []
    for title in pp.get("eventTitles") or []:
        for e in title.get("events") or []:
            races = []
            for r in e.get("races") or []:
                rows = []
                for x in r.get("results") or []:
                    c = x.get("competitor") or {}
                    m = re.search(r'-(\d+)$', c.get("urlSlug") or "")
                    rows.append(dict(place=x.get("place"), name=c.get("name"),
                        wa=int(m.group(1)) if m else None, slug=c.get("urlSlug"),
                        nat=x.get("nationality"), mark=x.get("mark"), wind=x.get("wind"),
                        record=x.get("records") or "", qualified=x.get("qualified"),
                        remark=x.get("remark"), points=x.get("points")))
                races.append(dict(name=r.get("race"), n=r.get("raceNumber"),
                                  wind=r.get("wind"), rows=rows))
            out.append(dict(event=e.get("event"), sex=e.get("gender"),
                            relay=e.get("isRelay"), withWind=e.get("withWind"), races=races))
    return out

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def isFinal(name):
    n = (name or "").lower()
    return "final" in n and "semi" not in n

def details(res, tt):
    """What the day pages leave out: the record a mark set, and every attempt of a field final.

    getEventPhaseByDiscipline wants the URL slug for the discipline but the letter code for the
    sex — "hammer-throw" with "M" — and anything else comes back null or throws inside their
    lambda. Attempts arrive out of order, so they are sorted by their own index.
    """
    field = {(p["sexCode"], p["discipline"]["name"]) for p in tt if p["discipline"].get("isField")}
    recs = atts = 0
    q = """query($e:Int,$d:String,$s:String,$p:String){
      getEventPhaseByDiscipline(eventId:$e, disciplineCode:$d, sexCode:$s, phaseCode:$p){
        units{ results{ competitorName record reactionTime }
          series{ competitorName attempts{ competitionIntermediateOrder intermediateMark } } } }}"""
    for e in res:
        disc = re.sub(r"^(Men's |Women's |Mixed )", "", e["event"])
        for r in e["races"]:
            phase = "final" if isFinal(r["name"]) else "semifinal"
            try:
                ph = gql(q, {"e": COMP, "d": slugify(disc), "s": e["sex"], "p": phase})
                ph = (ph or {}).get("getEventPhaseByDiscipline") or {}
            except Exception as ex:
                print(f"  ! detail {e['event']}: {ex}"); continue
            rec, by = {}, {}
            for u in (ph.get("units") or []):
                for x in (u.get("results") or []):
                    rec[(x.get("competitorName") or "").strip()] = (x.get("record"), x.get("reactionTime"))
                for x in (u.get("series") or []):
                    a = sorted(x.get("attempts") or [], key=lambda v: v.get("competitionIntermediateOrder") or 0)
                    by[(x.get("competitorName") or "").strip()] = [v.get("intermediateMark") for v in a]
            for row in r["rows"]:
                who = (row.get("name") or "").strip()
                if who in rec:
                    mark, rt = rec[who]
                    if mark: row["record"] = mark; recs += 1
                    if rt: row["rt"] = rt
                if (e["sex"], disc) in field and by.get(who):
                    row["att"] = by[who]; atts += 1
    return recs, atts

def photofinish(res):
    """Seiko's finish-line image for every track race that has one.

    They are not in any API and not named like the other competition documents: they live at
    photofinish/<competition>/<SEX>_<CODE>_<phase>_<n>.jpg, 7000px wide and 2-4MB each, so they
    are fetched once and kept in the repo at a size a card can actually use.
    """
    from PIL import Image                       # as tools/build_event_bg.py does
    Image.MAX_IMAGE_PIXELS = None               # a finish-line image can run to 95 megapixels
    out = os.path.join(HERE, "img", "pf")
    os.makedirs(out, exist_ok=True)
    got = 0
    for e in res:
        code = PF_CODE.get(re.sub(r"^(Men's |Women's |Mixed )", "", e["event"]))
        if not code: continue
        for r in e["races"]:
            ph = "f" if ("final" in (r["name"] or "").lower()
                         and "semi" not in (r["name"] or "").lower()) else "sf"
            name = f'{e["sex"]}_{code}_{ph}_{r["n"] or 1}'
            dst = os.path.join(out, name + ".webp")
            if os.path.exists(dst): r["pf"] = name + ".webp"; got += 1; continue
            tmp = os.path.join(out, name + ".jpg")
            try:
                req = urllib.request.Request(PF_URL + name + ".jpg", headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as fh, open(tmp, "wb") as w:
                    w.write(fh.read())
            except Exception:
                continue                        # a race with no photo finish, or not yet posted
            im = Image.open(tmp).convert("RGB")
            im.thumbnail((1600, 1600), Image.LANCZOS)
            im.save(dst, quality=80, method=6)
            os.remove(tmp)
            r["pf"] = name + ".webp"; got += 1
            print(f"  + photo finish {name} {im.size[0]}x{im.size[1]} "
                  f"{os.path.getsize(dst)//1024}KB")
    return got

def photos(ids):
    if not ids: return {}
    q = """query($ids:[Int]){getAthleteActionPictureByIds(ids:$ids){id primaryMediaId}}"""
    rows = gql(q, {"ids": sorted(set(ids))})["getAthleteActionPictureByIds"] or []
    return {str(r["id"]): r["primaryMediaId"] for r in rows if r.get("primaryMediaId")}

def profiles(people):
    """Podium athletes get a profile for the box: age, personal best in this event, and a photo.
    The photo is worth two goes — the action-picture API has one for some athletes and the
    profile for others, and neither has one for everybody.

    This used to read the athlete's own page. The API answers with the same object keyed by id,
    which needs no url slug — results filled in from the API have none — and does not get
    rate-limited into an error page halfway down a podium.
    """
    Q = """query($id:Int){getSingleCompetitor(id:$id){
      basicData{ birthDate countryFullName }
      primaryMediaId primaryMediaId2
      personalBests{ results{ discipline mark venue date } }
      seasonsBests{ results{ discipline mark } }
      honours{ categoryName } }}"""
    out, seen = {}, {}
    for wa, slug, disc in people:
        try:
            if wa not in seen:                 # an athlete can stand on two podiums
                seen[wa] = (gql(Q, {"id": int(wa)}) or {}).get("getSingleCompetitor")
            c = seen[wa]
            if not c: raise ValueError("no competitor")
        except Exception as e:
            print(f"  ! profile {wa}: {e}"); continue
        bd = c.get("basicData") or {}
        pbs = ((c.get("personalBests") or {}).get("results")) or []
        sbs = ((c.get("seasonsBests") or {}).get("results")) or []
        pick = lambda rows: next((r for r in rows if r.get("discipline") == disc), None)
        pb, sb = pick(pbs), pick(sbs)
        # two image slots on a competitor, and they are not the same picture: the first is the
        # action shot the results API also serves, the second a portrait. Keep whichever exist.
        # the bests are per event, not per athlete: Bednarek's 100m box was showing his 200m PB
        rec = out.setdefault(str(wa), dict(born=bd.get("birthDate"), country=bd.get("countryFullName"),
            media=c.get("primaryMediaId") or None, face=c.get("primaryMediaId2") or None,
            honours=[h.get("categoryName") for h in (c.get("honours") or [])][:4], marks={}))
        rec["marks"][disc] = dict(pb=(pb or {}).get("mark"), sb=(sb or {}).get("mark"),
                                  pbVenue=(pb or {}).get("venue"), pbDate=(pb or {}).get("date"))
    return out

def main():
    tt = timetable()
    print(f"timetable: {len(tt)} phases across {len({p['dayNum'] for p in tt})} days")
    res, days = results(max(p['dayNum'] for p in tt))
    n = sum(len(r['rows']) for e in res for r in e['races'])
    print(f"results:   {len(res)} events, {n} rows, days published {days}")
    if topup(res, tt):
        n = sum(len(r['rows']) for e in res for r in e['races'])
        print(f"topped up: {len(res)} events, {n} rows")
    nrec, natt = details(res, tt)
    print(f"detail:    {nrec} marks carry a record, {natt} have their series")
    print(f"photo finish: {photofinish(res)} races have one")
    pics = photos([r["wa"] for e in res for ra in e["races"] for r in ra["rows"] if r["wa"]])
    print(f"photos:    {len(pics)} athletes have one")
    # only the podium gets a profile read — that is what the box on the card shows
    podium = []
    for e in res:
        fin = next((r for r in e["races"] if "final" in (r["name"] or "").lower()
                    and "semi" not in (r["name"] or "").lower()), None)
        if not fin: continue
        disc = e["event"].split("'s ", 1)[-1] if "'s " in e["event"] else e["event"]
        for r in fin["rows"][:3]:
            if r["wa"]: podium.append((r["wa"], r["slug"], disc))
    # A profile read can fail wholesale — worldathletics.org rate-limits, and a blocked request
    # returns an error page with no __NEXT_DATA__. Never let that wipe profiles already on disk.
    prev = {}
    dst = os.path.join(HERE, "data", "ultimate.json")
    if os.path.exists(dst):
        try: prev = json.load(open(dst)).get("profiles") or {}
        except Exception: pass
    fresh = profiles(podium)
    prof = dict(prev); prof.update(fresh)
    print(f"profiles:  {len(fresh)} read, {len(prof)} held"
          + ("  (kept %d from the last run)" % (len(prof) - len(fresh)) if len(prof) > len(fresh) else ""))
    # the profile's primaryMediaId is a list of media-document ids, not a filename, and getMedia
    # will not resolve them — so only a real filename from the action API is ever a photo URL
    for wa, m in ((k, v.get("media")) for k, v in prof.items()):
        if isinstance(m, str) and m and wa not in pics: pics[wa] = m
    out = dict(fetched=time.strftime("%Y-%m-%d %H:%M"), competitionId=COMP,
               daysPublished=days, timetable=tt, results=res, photos=pics, profiles=prof,
               photoBase="https://assets.aws.worldathletics.org/")
    json.dump(out, open(dst, "w"), ensure_ascii=False)
    print("->", dst, f"({os.path.getsize(dst)//1024}KB)")

if __name__ == "__main__":
    main()
