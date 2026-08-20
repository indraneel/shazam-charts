#!/usr/bin/env python3
"""Rebuild the data block inside world-top200-rundown.html from git history.

Every commit that touched world-top200.csv is one daily snapshot of the Shazam
World Top 200. This walks that history, parses each revision of the CSV, and
rewrites the <script id="chart-data"> block in place, so the page stays a single
self-contained file. Re-run it after new snapshots land:

    python3 viz/build_rundown.py

The repo is often cloned shallow; run `git fetch --unshallow` first or you will
only capture the handful of commits the clone actually has.
"""

import csv
import io
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CSV_FILE = "world-top200.csv"
SOURCE_URL = "https://www.shazam.com/services/charts/csv/top-200/world"
PAGE = os.path.join(HERE, "world-top200-rundown.html")

# printable ASCII '#'(35)..'~'(126) minus backslash -> 91 symbols that need no
# escaping inside a JSON string. Two symbols encode one song id (91^2 = 8281).
ALPHA = "".join(chr(c) for c in range(35, 127) if c != 92)
RADIX = len(ALPHA)

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
DATE_RE = re.compile(r'^\s*"?(?:\w+day),\s*(\d{1,2})\s+(\w+)\s+(\d{4})')


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout


def parse_revision(blob):
    """Return (chart_date, [(rank, artist, title), ...]) or None if unparseable."""
    lines = blob.replace("﻿", "").splitlines()
    chart_date = None
    for line in lines[:6]:
        m = DATE_RE.match(line)
        if m:
            day, mon, yr = m.groups()
            if mon not in MONTHS:
                return None
            chart_date = "%04d-%02d-%02d" % (int(yr), MONTHS[mon], int(day))
            break
    if chart_date is None:
        return None

    header = next((i for i, l in enumerate(lines[:8])
                   if l.strip().lower().startswith("rank,")), None)
    if header is None:
        return None

    rows = []
    for r in csv.reader(io.StringIO("\n".join(lines[header + 1:]))):
        if len(r) < 3 or not r[0].strip():
            continue
        try:
            rank = int(r[0].strip())
        except ValueError:
            continue
        rows.append((rank, r[1].strip(), r[2].strip()))
    if not rows:
        return None
    rows.sort(key=lambda x: x[0])
    return chart_date, rows


def collect():
    log = git("log", "--follow", "--format=%H", "--reverse", "--", CSV_FILE).split()
    if not log:
        sys.exit("No commits touch %s -- wrong repo?" % CSV_FILE)

    snapshots = OrderedDict()   # chart_date -> rows; later commits win a repeated date
    skipped = 0
    for sha in log:
        try:
            blob = git("show", "%s:%s" % (sha, CSV_FILE))
        except subprocess.CalledProcessError:
            skipped += 1
            continue
        parsed = parse_revision(blob)
        if parsed is None:
            skipped += 1
            continue
        snapshots[parsed[0]] = parsed[1]

    if skipped:
        print("  skipped %d unparseable revision(s)" % skipped, file=sys.stderr)
    if len(log) < 100:
        print("  WARNING: only %d commits found. Shallow clone? "
              "Run: git fetch --unshallow" % len(log), file=sys.stderr)
    return snapshots


def build_payload(snapshots):
    dates = sorted(snapshots)
    width = len(snapshots[dates[0]])

    ids, order = {}, []

    def song_id(artist, title):
        key = (artist, title)
        if key not in ids:
            ids[key] = len(order)
            order.append([artist, title])
        return ids[key]

    days, dup_days, ragged = [], [], []
    for i, d in enumerate(dates):
        rows = snapshots[d]
        if len(rows) != width:
            ragged.append((d, len(rows)))
        seq = [song_id(a, t) for (_, a, t) in rows]
        if len(set(seq)) != len(seq):
            dup_days.append(i)          # upstream listed one title twice that day
        days.append(seq)

    if ragged:
        sys.exit("Snapshots disagree on row count (expected %d): %s"
                 % (width, ragged[:5]))
    if len(order) >= RADIX * RADIX:
        sys.exit("%d distinct songs exceeds the 2-symbol encoding limit (%d)"
                 % (len(order), RADIX * RADIX))

    encoded = ["".join(ALPHA[i // RADIX] + ALPHA[i % RADIX] for i in day) for day in days]

    d0 = date.fromisoformat(dates[0])
    offsets = [(date.fromisoformat(d) - d0).days for d in dates]

    payload = {
        "chart": "Shazam World Top 200",
        "sourceFile": CSV_FILE,
        "sourceUrl": SOURCE_URL,
        "alphabet": ALPHA,
        "startDate": dates[0],
        "dayOffsets": offsets,
        "dupDays": dup_days,
        "songs": order,
        "days": encoded,
    }
    return payload, dates, days


def verify(payload, dates, days, snapshots):
    """Decode the payload back and compare against what we parsed from git."""
    code = {c: i for i, c in enumerate(payload["alphabet"])}
    radix = len(payload["alphabet"])
    for i, enc in enumerate(payload["days"]):
        decoded = [code[enc[j]] * radix + code[enc[j + 1]] for j in range(0, len(enc), 2)]
        if decoded != days[i]:
            sys.exit("Round-trip failed: id mismatch on %s" % dates[i])
        got = [tuple(payload["songs"][x]) for x in decoded]
        want = [(a, t) for (_, a, t) in snapshots[dates[i]]]
        if got != want:
            sys.exit("Round-trip failed: song mismatch on %s" % dates[i])

    d0 = date.fromisoformat(payload["startDate"])
    for off, d in zip(payload["dayOffsets"], dates):
        if str(date.fromordinal(d0.toordinal() + off)) != d:
            sys.exit("Round-trip failed: date mismatch on %s" % d)


def inject(payload):
    with open(PAGE, encoding="utf-8") as fh:
        html = fh.read()

    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    # '<' never appears in JSON syntax, only inside string values, so escaping it
    # wholesale is safe and guarantees no stray '</script' closes the block early.
    blob = blob.replace("<", "\\u003c")

    pattern = re.compile(
        r'(<script id="chart-data" type="application/json">).*?(</script>)', re.S)
    if not pattern.search(html):
        sys.exit("Could not find the chart-data script block in %s" % PAGE)
    html = pattern.sub(lambda m: m.group(1) + blob + m.group(2), html, count=1)

    with open(PAGE, "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(blob)


def main():
    print("Reading %s from git history..." % CSV_FILE, file=sys.stderr)
    snapshots = collect()
    payload, dates, days = build_payload(snapshots)
    verify(payload, dates, days, snapshots)

    gaps = []
    d0 = date.fromisoformat(dates[0])
    have = set(payload["dayOffsets"])
    for off in range(max(payload["dayOffsets"]) + 1):
        if off not in have:
            gaps.append(str(date.fromordinal(d0.toordinal() + off)))

    size = inject(payload)
    print("  %d snapshots  %s .. %s" % (len(dates), dates[0], dates[-1]), file=sys.stderr)
    print("  %d distinct songs, %d bytes of embedded data" % (len(payload["songs"]), size),
          file=sys.stderr)
    if gaps:
        print("  %d calendar day(s) with no snapshot: %s%s"
              % (len(gaps), ", ".join(gaps[:6]), " ..." if len(gaps) > 6 else ""),
              file=sys.stderr)
    if payload["dupDays"]:
        print("  %d day(s) where the source lists one title twice"
              % len(payload["dupDays"]), file=sys.stderr)
    print("Wrote %s" % os.path.relpath(PAGE, REPO), file=sys.stderr)


if __name__ == "__main__":
    main()
