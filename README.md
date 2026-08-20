# shazam-charts

Daily snapshots of Shazam charts, each stored as successive git revisions of the
same file (collected by [Flat Data](https://githubnext.com/projects/flat-data/)).

| File | Chart |
|---|---|
| `world-top200.csv` | World Top 200 |
| `usa-top200.csv` | United States Top 200 |
| `india-top200.csv` | India Top 200 |
| `newark-top50.csv` | Newark Top 50 |
| `usa-discovery.json` | United States discovery |
| `india-discovery.json` | India discovery |

Each file only ever holds *today's* chart — the history lives in the commit log,
so `git log -- world-top200.csv` is the real dataset.

## viz/ — Top 200 Rundown

`viz/world-top200-rundown.html` replays every daily snapshot of the world chart
as an animated rundown: the full 200-row table, stepping one day at a time, with
rows flashing blue as tracks enter, green as they climb, and red as they slip.
Play/pause, a back/forward stepper, a draggable timeline scrubber, and 0.5×–5×
speed. Click any row to track a song and see its rank trajectory across the
whole archive.

It is a single self-contained file — open it directly in a browser, no server or
build step needed. The chart data is embedded in it.

### Refreshing it

The page carries its own copy of the data, so it needs regenerating after new
snapshots land:

```sh
git fetch --unshallow      # only if this clone is shallow; the history IS the data
python3 viz/build_rundown.py
```

That walks every commit touching `world-top200.csv`, parses each revision, and
rewrites the embedded data block in place. It verifies the encoded payload
decodes back to exactly what it read before writing, and reports any days with
no snapshot. No dependencies beyond Python 3 and git.
