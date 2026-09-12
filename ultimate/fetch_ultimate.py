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

def results():
    pp = next_data(RESULTS_URL)["props"]["pageProps"]["calendarEventsResults"]
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
    return out, [d["date"] for d in (pp.get("options") or {}).get("days", [])]

def photos(ids):
    if not ids: return {}
    q = """query($ids:[Int]){getAthleteActionPictureByIds(ids:$ids){id primaryMediaId}}"""
    rows = gql(q, {"ids": sorted(set(ids))})["getAthleteActionPictureByIds"] or []
    return {str(r["id"]): r["primaryMediaId"] for r in rows if r.get("primaryMediaId")}

def main():
    tt = timetable()
    print(f"timetable: {len(tt)} phases across {len({p['dayNum'] for p in tt})} days")
    res, days = results()
    n = sum(len(r['rows']) for e in res for r in e['races'])
    print(f"results:   {len(res)} events, {n} rows, days published {days}")
    pics = photos([r["wa"] for e in res for ra in e["races"] for r in ra["rows"] if r["wa"]])
    print(f"photos:    {len(pics)} athletes have one")
    out = dict(fetched=time.strftime("%Y-%m-%d %H:%M"), competitionId=COMP,
               daysPublished=days, timetable=tt, results=res, photos=pics,
               photoBase="https://assets.aws.worldathletics.org/")
    p = os.path.join(HERE, "data", "ultimate.json")
    json.dump(out, open(p, "w"), ensure_ascii=False)
    print("->", p, f"({os.path.getsize(p)//1024}KB)")

if __name__ == "__main__":
    main()
