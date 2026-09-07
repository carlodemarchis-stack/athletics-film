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
    d = gql("{getRecordsDisciplineList{gender disciplineTypes{disciplines{eventId name}}}}")
    out = {}
    for g in d["getRecordsDisciplineList"]:
        for t in g["disciplineTypes"]:
            for x in t["disciplines"]:
                if x["name"] in EVENTS:
                    out[(g["gender"], x["name"])] = int(x["eventId"])
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
        "country competitor{name}}}}" % pid)["getRecordsDetailByProgression"]


def main():
    idx = discipline_index()
    cards = []
    for (gender, name), eid in sorted(idx.items()):
        pid = progression_id(eid)
        if not pid:
            print(f"  !! no World Records progression for {gender} {name}", file=sys.stderr)
            continue
        p = progression(pid)
        cards.append({"gender": gender, "discipline": name, "eventId": eid,
                      "progressionId": pid, "environment": p["environment"],
                      "disciplineCode": p["discipline"]["disciplineCode"],
                      "entries": p["entries"]})
        print(f"  {gender:5} {name:20} pid={pid:<6} {len(p['entries']):3} records")
        time.sleep(0.15)
    path = os.path.join(HERE, "data", "progressions.json")
    with open(path, "w") as f:
        json.dump({"fetched": time.strftime("%Y-%m-%d"), "cards": cards}, f)
    print(f"\n{len(cards)} cards -> {path}")


if __name__ == "__main__":
    main()
