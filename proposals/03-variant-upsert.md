<!-- Title: Variant duplicate-key failures: 145 of 171 are collisions inside a single record -->

@GilShalit — the variant duplicate-key failures (`Cannot insert duplicate key row in object
'dbo.Variants'`) look like the place duplicates but are a different problem, and most of
them are not duplications at all.

For each of the 171 cases I resolved which Kima place currently owns the colliding variant
string and compared its `MAZAL_ID` against the record being imported:

| | n | meaning |
|---|---:|---|
| same NLI id | **145** | the variant already belongs to *this very record* |
| no Kima owner resolved | 26 | needs a look — see below |
| a **different** NLI id | **0** | — |

Not one case is a collision between two different NLI records. In the 145 the runner is
trying to insert a variant string that the record's own Kima place already holds — the
record supplies the same string twice (typically the same form reached through two
different MARC fields, or a repeat across `4xx`), or it was already imported on an earlier
run.

## Proposed change

Upsert variants rather than insert: if the (place, variant string) pair already exists,
skip it silently. That removes 145 report rows and, more importantly, stops an entire
record's import failing on a harmless repeat — the exception aborts the transaction, so I
assume the rest of that record's changes are lost too.

Worth normalising before the comparison: NFC Unicode normalisation at minimum. Some of
these strings are visually identical but differ in composition, and if the DB collation
treats them as equal while the code treats them as distinct (or vice versa) the dedup will
misfire in one direction or the other.

## The remaining 26

These are ones where I could not resolve a Kima owner for the variant string at all — my
resolution goes through the Kima API and may simply be failing, or the string may be held
by a place I did not find. I do not think they are the same problem as the 145, and I
would leave them in the report for now; I will look at them separately and open something
specific if there is a pattern.

Method and per-case output: `app/analyze_dups.py`, `app/dup-analysis.tsv` (column
`verdict`, values `same-id` / `kima-unresolved`).
