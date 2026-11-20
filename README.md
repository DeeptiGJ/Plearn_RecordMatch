# Verified Findings: `plearun_cli.py`

    python3 plearun_cli.py REPORT RECORDS_DIR [--trace] > findings.json     # offline, stdlib only
    make test                                                                # offline

## Quick start
Needs Python 3.9+ only.

    python plearun_cli.py reports/report_fictional_02.txt records > findings.json
    python plearun_cli.py reports/report_fictional_02.txt records --trace   # explains every decision on stderr
    make test                                                                # runs all tests

## Tools used
Claude (Anthropic chat assistant) helped me plan the design, draft the code module by module, and write tests.
I reviewed, ran and can explain every module.

## How it works
`loaders` (CSV with BOM/marker/CRLF/cp1252, nested JSON, WebVTT) -> `timeparse` (epoch s/ms, ISO with zone, zone-less,
time-of-day, VTT-relative: never mixed) -> `clocks` (offsets from anchors) -> `claims` (regex clauses, no LLM) ->
`judge` (rules) -> `verify` (hard gate) -> JSON. One bad file, row or claim never stops the run.

**Row numbers** (one function, `models.row_number`): 1-based data rows. CSV: marker line, header and blank lines are
not counted. VTT: 1-based cue order. JSON: order of record objects (objects in a list carrying a timestamp key).
`raw` text of a row = the physical CSV record / cue payload / exact JSON object span. Every `match`/`conflict` quote must be
an exact substring of it, else the finding is downgraded to `not_settled`.

## Three hardest decisions
1. **Clocks.** Offsets come only from *anchors*: a unit id or plate appearing once (per event type) in two clocks; >= 2 agreeing
   anchors, median offset, uncertainty carried, propagated from the dispatch clock. Otherwise the clock stays unaligned and is never
   compared. Cameras are separate clocks. A zone-less stamp is never assumed to be in a zone, and a gap that is a whole number of
   quarter-hours is not allowed to become a conflict.
2. **Asymmetric evidence.** `conflict` needs a machine record (camera/dispatch), a usable clock, one unambiguous event, and a gap bigger
   than tolerance + uncertainty. Notes/transcripts can support an event-time `match` only by stating the same time themselves, never a
   conflict, and never settle a measured speed (cameras have no plate, so a speed needs an aligned, unambiguous reading).
3. **Claim splitting.** A sentence is split at a comma only when both sides carry their own time/speed/duration; unmeasurable
   claims ("only car in the lane") are `not_checkable`.

## What it gets wrong
Claim extraction is regex-based (unusual phrasing is missed or `not_settled`); locations ("mile marker 4", "Harbor Gas lot") and counts are
not verified; the event vocabulary is small; camera clocks can only be aligned if a record gives them an anchor (a plate column);
human text that merely repeats the officer's own claim can yield a (non-independent) `match`.

## What breaks first on real records
Zone-less stamps from a different zone, sparse/ambiguous anchors (everything correctly becomes `not_settled`), day rollover around
midnight when the report has no date, different row-numbering expectations, and memory on files far beyond a few hundred MB
(files are read whole). The optional LLM path (`mock_llm.py`) is intentionally not built: it earns no points and the core is rule-based.
