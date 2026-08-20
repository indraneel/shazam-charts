# Porting the rundown to the other five charts

How to extend `viz/world-top200-rundown.html` + `viz/build_rundown.py` to cover
`usa-top200.csv`, `india-top200.csv`, `newark-top50.csv`, `usa-discovery.json`,
and `india-discovery.json`.

Everything below was measured against the full history at commit `7eef694`, not
assumed. Where a number appears, it came from a run over all ~4,900 revisions.

---

## 1. The finding that shrinks the job

**All six files are the same CSV format.** The `.json` extension on the two
discovery files is wrong — they are byte-for-byte the same shape as the others:
UTF-8 BOM, a blank line, a quoted date line, a `Rank,Artist,Title` header, then
quoted rows.

This is not a guess. `build_rundown.py`'s `collect()`, `build_payload()` and
`verify()` were run unmodified against all six files — only the module constant
`CSV_FILE` was reassigned — and all six parsed and round-tripped clean:

| file | snapshots | unparseable | rows/day | header variants |
|---|---|---|---|---|
| `world-top200.csv` | 824 | 0 | 200 | `Rank,Artist,Title` only |
| `usa-top200.csv` | 823 | 0 | 200 | `Rank,Artist,Title` only |
| `india-top200.csv` | 822 | 0 | 200 | `Rank,Artist,Title` only |
| `newark-top50.csv` | 822 | 0 | 50 | `Rank,Artist,Title` only |
| `usa-discovery.json` | 822 | 0 | 10 | `Rank,Artist,Title` only |
| `india-discovery.json` | 822 | 0 | 10 | `Rank,Artist,Title` only |

No ragged snapshots, no rank sequence that isn't exactly `1..N`, no format drift
across two years. **Do not write a second parser.** The parsing layer is already
chart-agnostic and proven; the work is in the registry, the page chrome, and the
size-specific rendering.

## 2. Measured data facts

| file | days | rows | distinct songs | dup-days | payload | missing days |
|---|---|---|---|---|---|---|
| `world-top200.csv` | 824 | 200 | 4,199 | 3 | 532,931 B | 6 |
| `usa-top200.csv` | 823 | 200 | 4,831 | 2 | 551,904 B | 7 |
| `india-top200.csv` | 822 | 200 | 3,997 | **63** | 568,722 B | 8 |
| `newark-top50.csv` | 822 | 50 | 1,474 | 0 | 151,065 B | 8 |
| `usa-discovery.json` | 822 | 10 | 597 | 0 | 48,337 B | 8 |
| `india-discovery.json` | 822 | 10 | 501 | 0 | 51,916 B | 8 |
| **total** | | | | | **1.82 MiB** | |

All six span `2024-05-12 .. 2026-08-19`. Every chart's distinct-song count is
comfortably under the 8,281 cap of the two-symbol base-91 encoding.

Source URLs (from `.github/workflows/flat.yml`):

```
world-top200.csv       https://www.shazam.com/services/charts/csv/top-200/world
usa-top200.csv         https://www.shazam.com/services/charts/csv/top-200/united-states
india-top200.csv       https://www.shazam.com/services/charts/csv/top-200/india
newark-top50.csv       https://www.shazam.com/services/charts/csv/top-50/united-states/newark
usa-discovery.json     https://www.shazam.com/services/charts/csv/discovery/united-states
india-discovery.json   https://www.shazam.com/services/charts/csv/discovery/india
```

The six zero-byte files in the repo root (`world-top200.json`,
`usa-US-top200.json`, `usa-US-rising.json`, `india-IN-top200.json`,
`india-IN-rising.json`, `trenton-5105496-top200.json`) are dead — the Flat job
writes nothing to them. Ignore them.

## 3. Architecture — one page with a chart switcher

**Recommended.** All six inline is 1.82 MiB, 11.4% of the 16 MiB artifact
budget, so there is no size reason to split. One page gives the thing six pages
cannot: reading India's churn against the USA's on the same day.

The alternative — six standalone pages generated from a shared template — is
lower risk but leaves six near-identical HTML files to drift apart. Take it only
if §7.2 (the date-alignment work) turns out worse than expected.

Payload shape for the single-page build:

```jsonc
{
  "alphabet": "…",            // identical for every chart, hoist it
  "timeline": ["2024-05-12", …],   // master date list, 824 entries
  "charts": [
    { "slug": "world", "label": "World", "rows": 200,
      "sourceFile": "world-top200.csv", "sourceUrl": "…",
      "dayIndex": [0, 1, 2, …],   // position in `timeline` for each of this chart's days
      "dupDays": [...], "songs": [[artist,title], …], "days": ["…", …] }
  ]
}
```

Keep `songs` **per chart** — see §7.1. Decode lazily: build the `Int16Array`s for
a chart the first time it is selected, not for all six at load.

## 4. Changes to `build_rundown.py`

`collect()`, `parse_revision()`, `build_payload()` and `verify()` need **no
logic changes**. What changes:

1. Replace the three module constants (`CSV_FILE`, `SOURCE_URL`, `PAGE` — near
   the top, search for `CSV_FILE =`) with a `CHARTS` registry of dicts carrying
   `slug`, `label`, `file`, `url`.
2. Thread the file through instead of reading the global — `collect(chart_file)`
   rather than `collect()`.
3. `build_payload()` currently returns one chart's payload; wrap it in a loop and
   assemble the `charts` array, hoisting `alphabet` and computing the master
   `timeline` as the sorted union of every chart's dates.
4. `inject()` targets `<script id="chart-data" type="application/json">` — that
   stays, it just receives the combined payload.
5. Give it a CLI: `python3 viz/build_rundown.py [slug …]`, defaulting to all six,
   so a single chart can be rebuilt without re-walking 4,900 revisions.

Keep the `verify()` round-trip gate. It is what caught nothing so far precisely
because it runs; do not drop it for speed.

Runtime is ~30 s per chart (one `git show` per revision), so ~3 min for all six.
If that becomes annoying, batch the blob reads through `git cat-file --batch`
instead of one `git show` per commit.

## 5. Changes to the page runtime

The runtime is already almost entirely driven by `SIZE`
(`var SIZE = DATA.days[0].length / 2`), so most of it works at 200, 50 or 10 rows
untouched. Exactly four places assume a 200-row chart. Search for the token, the
line numbers are as of `7eef694` and will drift:

| what | search for | why it breaks |
|---|---|---|
| top-10 emphasis | `rank <= 10` (L524) | on a 10-row discovery chart **every** row is emphasised, so the emphasis says nothing |
| tier hairlines | `rank === 11 \|\| rank === 51 \|\| rank === 101` (L525) | never fire at 10 rows; only the first fires at 50 |
| sparkline guides | `[1, 100, SIZE]` (L679) | at `SIZE = 10` the `100` guide is drawn far off-canvas |
| table min-width | `min-width:560px` (L196) | sized for five columns of 200-row data; a 10-row chart needs less |

Make the first three a function of `SIZE` — e.g. emphasise the top decile
(`Math.max(3, Math.round(SIZE / 20))`), place tier rules only at boundaries below
`SIZE`, and pick guides from `[1, …].filter(r => r < SIZE)` plus `SIZE`.

Then add the two things a multi-chart page needs and the current one has no
concept of:

- **A chart switcher.** A segmented control beside the speed control is the
  obvious home; it already reads as a control strip. Six labels is a lot for one
  row on mobile — consider a `<select>` below 720px.
- **A "no snapshot for this date" row state.** With a shared timeline, a chart
  will occasionally have no data for the active date (§7.2). The page currently
  cannot express that; it needs an empty state rather than showing stale rows.

## 6. Changes to the copy

Every identity string is hardcoded and must become data-driven from the active
chart: `<title>` (L7), `.eyebrow` (L288), `<h1>` (L289), the `.lede` paragraph
(L290) and the `#provenance` footer line. The lede names "World Top 200" and
`world-top200.csv` in prose.

Note the two discovery charts are **not** rankings of the biggest tracks — they
are Shazam's discovery/rising list. Calling them a "Top 10" would be wrong.
Label them "Discovery" and say what they are.

## 7. The traps

### 7.1 A shared song dictionary will not fit the encoding

Tempting, since world/usa/newark overlap heavily. It does not work:

```
sum of per-chart distinct : 15,599
union (deduped)           : 10,276
2-symbol base-91 cap      :  8,281      -> EXCEEDS by 1,995
```

A shared dictionary would force three symbols per song id, growing every day
string by 50%. **Keep dictionaries per chart** — each is well under the cap.

### 7.2 Never switch charts by day index — switch by date

The charts do not share a date set. World has 824 days; the others have 823 or
822, and the gaps fall on different dates:

```
usa-top200.csv        lacks 2025-03-10
india-top200.csv      lacks 2025-03-10, 2025-04-08
newark-top50.csv      lacks 2025-03-10, 2025-04-08
usa-discovery.json    lacks 2025-03-10, 2025-04-08
india-discovery.json  lacks 2025-03-10, 2025-04-08
```

Consequence, measured: **522 of 823 index positions point at a different date in
world vs usa.** Switching charts while preserving the raw index would silently
jump the viewer up to two days. Resolve the active *date* into the new chart's
index instead.

Convenient property: world's date set is a strict superset of all five others,
and the union of all six is exactly world's 824 dates. So the master timeline is
world's, and 822 dates are present in all six.

### 7.3 India has 63 duplicate-title days, not 3

The `dupDays` mechanism exists because the source occasionally lists one title at
two ranks. World has 3 such days and it is a curiosity; **India has 63**, so the
"keep the best rank" rule in `rankMap()` and the `Set` guard in `absorb()` do
real work there. Do not simplify them away, and re-check the counts after any
change to `build_payload()`.

### 7.4 Ten-row charts change what the design is

A 200-row rundown is a wall of motion; a 10-row discovery chart is nearly static
and a third of the daily rows are new entries. The per-day tallies
(`new / climbed / slipped / held`) that read well out of 200 read thin out of 10.
Consider showing the tallies as a share rather than a count on small charts, and
expect the flash animation to carry much more of the page.

### 7.5 The repo is cloned shallow

A fresh clone has ~50 commits and the build will silently produce a 50-day
timeline. `build_rundown.py` warns when it sees fewer than 100 commits — keep
that check. Run `git fetch --unshallow` first.

## 8. Verification — the gates that must pass

The world chart shipped only after these. Repeat all of them per chart; the first
one is the one that matters most.

1. **Row-by-row comparison against git.** Re-read every revision independently
   (a second parser, not the build script's), index by the date in each blob's
   own header line, and compare all days × all ranks against the embedded
   payload. World passed at 824 × 200.
   *Watch out:* match the header line with the date regex, not a substring test —
   `'9 March 2025' in raw` also matches `19 March 2025`, which produced a false
   mismatch during the world build.
2. **Flash colours actually paint.** Step one day, sample
   `getComputedStyle(tr).backgroundColor` across ~12 animation frames, and assert
   all three wash colours appear with decaying alpha. A `MutationObserver` on the
   style attribute does **not** work — the set and the clear happen in the same
   task, so the callback only ever sees the cleared value.
3. **Transport.** Paused stays paused; step ±1; scrub jumps; 5× advances ~10
   days/sec; keyboard (`←`/`→`, shift, `Home`/`End`, `Esc`); playback clamps and
   auto-pauses at the end; pressing play at the end replays from day 1.
4. **Layout.** Zero horizontal overflow at 360/390/430/768/1280 px, and the
   sticky deck under ~30% of viewport height on mobile.
5. **Chart switching** (new): switching charts preserves the displayed *date*,
   and a chart with no snapshot for that date shows the empty state.

## 9. Design constraints to preserve

- **The rise/slip palette was computed, not chosen.** Light `#2a78d6` / `#0ca30c`
  / `#a01f28`, dark `#3987e5` / `#1faf5c` / `#c4362f`. Red-vs-green is the
  classic colourblind failure; these steps were picked by running the `dataviz`
  skill's `validate_palette.js` until they passed (deutan ΔE 15.4 light / 10.6
  dark against a ≥8 target, contrast ≥3:1 on both surfaces). **If you change a
  colour, re-run the validator** against the actual surface — do not eyeball it.
- **State never rests on colour alone.** Every row also carries an arrow and a
  delta (`▲ 12`, `▼ 3`, `NEW`, `RE`). Keep that.
- **Three theme states, not two.** Tokens are defined on bare `:root`, redefined
  under `@media (prefers-color-scheme: dark)` guarded by
  `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`.
  Never declare a colour only inside a media or `[data-theme]` block.
- **`overflow` on the table wrapper makes it the sticky container.** This already
  caused a real bug: `overflow-x:auto` on `.tablewrap` plus
  `top: var(--deck-h)` on the sticky `<th>` rendered the header 152 px *down*,
  over row 3. The wrapper now only gets `overflow-x` below 720 px, where the
  header is `position: static`. Keep that arrangement.
- **Peak and days-on-chart are counted as of the displayed date**, not across the
  whole archive, so scrubbing backwards stays honest. `statsThrough()` rebuilds
  from day 0 on a backward jump. Preserve that semantic per chart.

## 10. Suggested order

1. Registry + CLI in `build_rundown.py`; emit the combined payload. Verify with
   §8.1 on all six before touching the page.
2. Make the four size-specific spots `SIZE`-driven (§5); confirm the world page
   still renders identically.
3. Add the chart switcher, date-preserving switching (§7.2) and the empty state.
4. Data-drive the copy (§6).
5. Run §8 end to end, then republish.
