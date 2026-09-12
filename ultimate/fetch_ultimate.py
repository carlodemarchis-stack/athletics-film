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

EP   = "https://graphql-prod-4888.edge.aws.worldathletics.org/graphql"
KEY  = "da2-ekwnowppnnahhp33zt7yzri77m"      # see fetch_records.py for how to refresh these
COMP = 7212925                                # eventId_WA of the 2026 Ultimate Championship
RESULTS_URL = f"https://worldathletics.org/competition/calendar-results/results/{COMP}"
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

def photos(ids):
    if not ids: return {}
    q = """query($ids:[Int]){getAthleteActionPictureByIds(ids:$ids){id primaryMediaId}}"""
    rows = gql(q, {"ids": sorted(set(ids))})["getAthleteActionPictureByIds"] or []
    return {str(r["id"]): r["primaryMediaId"] for r in rows if r.get("primaryMediaId")}

def profiles(people):
    """Podium athletes get their profile page read for the box: age, personal best in this
    event, and a photo. The photo is worth two goes — the action-picture API has one for
    some athletes and the profile for others, and neither has one for everybody."""
    out = {}
    for wa, slug, disc in people:
        try:
            c = next_data(f"https://worldathletics.org/athletes/{slug}")["props"]["pageProps"]["competitor"]
        except Exception as e:
            print(f"  ! profile {slug}: {e}"); continue
        bd = c.get("basicData") or {}
        pbs = ((c.get("personalBests") or {}).get("results")) or []
        sbs = ((c.get("seasonsBests") or {}).get("results")) or []
        pick = lambda rows: next((r for r in rows if r.get("discipline") == disc), None)
        pb, sb = pick(pbs), pick(sbs)
        # two image slots on a competitor, and they are not the same picture: the first is the
        # action shot the results API also serves, the second a portrait. Keep whichever exist.
        out[str(wa)] = dict(born=bd.get("birthDate"), country=bd.get("countryFullName"),
            media=c.get("primaryMediaId") or None, face=c.get("primaryMediaId2") or None,
            pb=(pb or {}).get("mark"), pbVenue=(pb or {}).get("venue"), pbDate=(pb or {}).get("date"),
            sb=(sb or {}).get("mark"),
            honours=[h.get("categoryName") for h in (c.get("honours") or [])][:4])
        time.sleep(.25)
    return out

def main():
    tt = timetable()
    print(f"timetable: {len(tt)} phases across {len({p['dayNum'] for p in tt})} days")
    res, days = results(max(p['dayNum'] for p in tt))
    n = sum(len(r['rows']) for e in res for r in e['races'])
    print(f"results:   {len(res)} events, {n} rows, days published {days}")
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
            if r["wa"] and r["slug"]: podium.append((r["wa"], r["slug"], disc))
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
