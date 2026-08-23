# NLI place authorities with malformed `034` coordinates — 2026-08-22

Companion to `nli-malformed-coordinates-report_20260822.csv` (957 records, one row each;
values re-read from the live NLI MARC on 2026-08-22).

**Headline case:** `987012654573505171` Saint Privat en Périgord (France), batch `BMC 202401`.
Its geohack `034` is written as `01256.88 / 451335.04` (no hemisphere, no degree padding) and
its geonames `034` as `E01230 / N451339` (6 digits). The first one is shaped enough like a
decimal number that our pipeline passed it to the database, which rejected it as invalid
geography. Only 8 records in the file are from batch `BMC 202401`; the malformation is not
batch-specific — the largest contributors are `BEB 202509` (114), `css 202508` (99),
`css 202507` (87).

## Problem categories (`problem` column)

| category | count (incl. combinations) | example | what it should be |
|---|---|---|---|
| `dms-missing-leading-zero` | ~730 | `E254427 / N483246` | `E0254427 / N0483246` — MARC `hdddmmss` needs 3 degree digits |
| `incomplete-point (missing $e and/or $g)` | ~300 | `$d=W0752236 $f=N0425554`, no `$e`/`$g` | for a point, `$e=$d` and `$g=$f` |
| `contains-space` | ~125 | `E 0283321` | `E0283321` |
| `decimal-degrees` | ~35 | `E 43.8858 / N13.7831` | `E043.885800 / N013.783100` (or drop the space; see note) |
| `dms-with-decimal-seconds-unpadded` | ~15 | `E163059.4 / N475046.28` | `E0163059.4 / N0475046.28` |
| `hemisphere-letter-only` | 7 | `$d=W $e=E $f=N $g=S` | template never filled in |
| `hemisphere-after-digits` | 4 | `0164307E / 0522008N` | `E0164307 / N0522008` |
| `no-hemisphere` | 1–2 | `343008N`, `01256.88` | as above |
| `valid per MARC — rejected by our parser` | 18 | `W77.4874899 / N39.0437192` | nothing to fix on NLI's side |

`suggested_034` is filled only where the fix is mechanical (zero-padding a complete
short-DMS point). All other rows need a cataloguer's eye.

All 957 records are `live` on NLI. Our pipeline currently skips every one of them
("no valid 034"), so none of these places is being synchronised with Kima.
