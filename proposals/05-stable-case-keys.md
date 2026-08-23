<!-- Title: Reports overwrite each other, so review decisions don't survive a re-run -->

@GilShalit — a mechanical problem rather than a data one, which is currently costing me
work on the review side.

## What happens

A re-run overwrites `failures-combined_*.json` and `manual-review-combined_*.json` in
place. A case that stopped failing simply vanishes from the file, and anything I had
attached to it — a decision, a note, a "reported to NLI, waiting" — is orphaned, because
the only handle I have on a case is the record id plus whatever the message said.

There is no record of *when* a case was first or last seen, so I cannot tell these apart:

- the case was genuinely resolved
- the case moved to the other track (failure → manual review, or back)
- the re-run has not reached that period yet
- the run was non-deterministic (see below)

Right now the repo has a re-run at the root covering 20240610–20250630 and a previous full
run in `backup/` reaching 2026-06-30, so the newest periods exist only in `backup/`. My app
carries a `stale` flag that conflates "superseded by the re-run" with "in a period the
re-run never reached" — 201 of my 213 duplicate cases are marked stale purely because they
are past the re-run cutoff, when they are actually the freshest evidence in the repo. That
is my bug to fix and I am fixing it, but the reports do not currently carry the
information I would need to fix it properly.

## Proposed change

1. **Give each case a stable key** — something like `(recordId, kimaPlaceId, category)`,
   whatever combination is stable across runs for you. It does not need to be pretty, only
   reproducible.
2. **Add `firstSeenRun` and `lastSeenRun`** (or run timestamps) per case.
3. **Don't delete rows on re-run.** Either append, or keep the row and mark it as no
   longer reproducing. A row that stopped failing is information I want; today it is
   silently destroyed.
4. **Emit a small manifest per run** — run id, timestamp, period range, code version,
   counts per category. `run-summary_*.json` may already be close to this; if so, adding
   the run id to each report row is most of what is needed.

Point 3 is the one that matters most to me. The others are conveniences.

## The related question

Re-running the same period does not reproduce the same output — comparing the current run
against `backup/` for 2025H1 I see roughly 20% of rows differing. Some of that is
legitimate (NLI's data changed between the runs), but I would like to know how much.

If it is all attributable to NLI changes, then "this row is gone" really does mean
something and stable keys would let me use it. If some of it is ordering or concurrency
inside the runner, that is worth knowing too — right now I have stopped using run-to-run
differences as evidence of anything, which throws away a signal that ought to be useful.
