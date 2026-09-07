#!/usr/bin/env python3
"""Pull World Athletics world-record progressions into data/progressions.json.

Three hops through the public worldathletics.org GraphQL API:
  getRecordsDisciplineList  -> eventId per discipline/sex
  getRecordsDetailByDiscipline(eventId) -> progressionListId of the World Records row
  getRecordsDetailByProgression(progressionId) -> every record ever set
"""
import json, os, sys, time, urllib.request

EP = "https://graphql-prod-4881.edge.aws.worldathletics.org/graphql"
KEY = "da2-wbnmtmvlpbhifh3uc2xaxsue5i"          # shipped in worldathletics.org's public JS bundle
HERE = os.path.dirname(os.path.abspath(__file__))

# the deck: core outdoor championship events, men + women
EVENTS = [
    "100 Metres", "200 Metres", "400 Metres", "800 Metres", "1500 Metres",
    "5000 Metres", "10,000 Metres", "Marathon",
    "110 Metres Hurdles", "100 Metres Hurdles", "400 Metres Hurdles",
    "High Jump", "Pole Vault", "Long Jump", "Triple Jump",
    "Shot Put", "Discus Throw", "Hammer Throw", "Javelin Throw",
    "Decathlon", "Heptathlon", "4x100 Metres Relay", "4x400 Metres Relay",
]


def gql(query):
    req = urllib.request.Request(
        EP, data=json.dumps({"query": query}).encode(),
        headers={"x-api-key": KEY, "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req))
    if d.get("errors"):
        raise RuntimeError(d["errors"][0]["message"])
    return d["data"]


def discipline_index():
    """In the order World Athletics themselves list them — discipline group, then discipline."""
    d = gql("{getRecordsDisciplineList{gender disciplineTypes{name disciplines{eventId name}}}}")
    out = []
    for g in d["getRecordsDisciplineList"]:
        rank = 0
        for t in g["disciplineTypes"]:
            for x in t["disciplines"]:
                if x["name"] in EVENTS:
                    out.append({"gender": g["gender"], "discipline": x["name"],
                                "eventId": int(x["eventId"]), "group": t["name"], "order": rank})
                    rank += 1
    return out


def progression_id(event_id):
    d = gql("{getRecordsDetailByDiscipline(eventId:%d){ageCategory items{progressionListId category}}}" % event_id)
    for blk in d["getRecordsDetailByDiscipline"] or []:
        if blk["ageCategory"] != "SENIOR":
            continue
        for it in blk["items"]:
            if it["category"] == "World Records" and it["progressionListId"]:
                return it["progressionListId"]
    return None


def progression(pid):
    return gql(
        "{getRecordsDetailByProgression(progressionId:%d){gender environment ageCategory "
        "discipline{name disciplineCode} entries{performance equal pending wind date venue "
        "country competitor{id name urlSlug}}}}" % pid)["getRecordsDetailByProgression"]


def competition_of(entry):
    """The meet a record was set at. The progression payload doesn't carry it, so look it up
    in the athlete's own results for that year and match on date + mark."""
    cid = (entry.get("competitor") or {}).get("id")
    if not cid:
        return None                                     # relay teams have no competitor id
    year = int(entry["date"].split()[-1])
    try:
        d = gql('{getSingleCompetitorResultsDate(id:%d,resultsByYear:%d,resultsByYearOrderBy:"date")'
                '{resultsByDate{date competition mark}}}' % (cid, year))
        rows = (d["getSingleCompetitorResultsDate"] or {}).get("resultsByDate") or []
    except Exception:
        return None
    same_day = [r for r in rows if r["date"] == entry["date"]]
    for r in same_day:
        if r["mark"] == entry["performance"]:
            return r["competition"]
    return same_day[0]["competition"] if len(same_day) == 1 else None


def main():
    idx = discipline_index()
    cards = []
    for e in idx:
        gender, name, eid = e["gender"], e["discipline"], e["eventId"]
        pid = progression_id(eid)
        if not pid:
            print(f"  !! no World Records progression for {gender} {name}", file=sys.stderr)
            continue
        p = progression(pid)
        meet = competition_of(p["entries"][0])          # the meet of the standing record
        cards.append({"gender": gender, "discipline": name, "eventId": eid,
                      "progressionId": pid, "environment": p["environment"],
                      "disciplineCode": p["discipline"]["disciplineCode"],
                      "group": e["group"], "order": e["order"],
                      "competition": meet,
                      "entries": p["entries"]})
        print(f"  {gender:5} {e['group']:15} {name:20} #{e['order']:<3} {len(p['entries']):3} records")
        time.sleep(0.15)
    path = os.path.join(HERE, "data", "progressions.json")
    with open(path, "w") as f:
        json.dump({"fetched": time.strftime("%Y-%m-%d"), "cards": cards}, f)
    print(f"\n{len(cards)} cards -> {path}")


if __name__ == "__main__":
    main()
