# Athletics — World Record Film

An interactive athletics experience by [A guy with a scarf](https://aguywithascarf.com) (Carlo De Marchis).

One card per discipline: the complete world-record progression as a staircase through time —
step width is how long each record survived, and the flat tail is how long the current one has
stood. Underneath, the ghost race: every record mark ever set, run at once.

Live at **https://athletics.aguywithascarf.com**

## Data

All marks come from the World Athletics record-progression API. Refresh with:

```
python3 fetch_records.py
```

which rewrites `data/progressions.json` (43 events, men and women).
