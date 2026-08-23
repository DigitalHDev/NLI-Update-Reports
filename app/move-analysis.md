# Coordinate-change cases (`location-move`) — classification

Written 2026-08-22. Produced by `app/classify_moves.py` → `app/move-analysis.{tsv,json}`.
525 cases (all with MARC; every one's Kima place carries the same `MAZAL_ID` as the
incoming record, so these are never "wrong record" cases — the record is right, the
*point* or the *identity behind the point* is what differs).

## Method

Wikidata is used as the independent arbiter. For each case we resolve up to two
entities — NLI's (from `024 $2 wikidata`, falling back to a `haswbstatement:P8189=<NLI id>`
search) and Kima's (from `WD`, falling back to `P1566=<Kima Geoname_ID>`) — and pull
P625 coordinates, P31 classes, P2046 area / P2043 length, and labels. Plus the raw `034`
subfields, which turned out to hold two mechanical bugs of their own.

One caveat to keep in mind: Kima's coordinates usually *came from* Wikidata/GeoNames, so
"Wikidata is 0 km from Kima" is not an independent second witness; it says "NLI's point
disagrees with the entity NLI itself claims", which is still the useful statement.

## Result

| bucket | proposed action | n | your case |
|---|---|---:|---|
| `extended-feature` | apply-new (take NLI, per Sinai 2026-08-22) | 256 | **1** river / region — two legitimate points |
| `nli-coords-wrong` | keep-existing + report to NLI | 106 | **5** |
| `nli-034-dropped-zero` | keep-existing + report to NLI (mechanical fix) | 45 | **5**, new sub-type |
| `homonym` | apply-new (NLI self-consistent) | 35 | **4** |
| `homonym` | research | 23 | **2/3** both legitimate, which did NLI mean? |
| `no-wd` | research | 34 | other |
| `kima-coords-wrong` | apply-new (auto) | 9 | **4/5** |
| `kima-wd-wrong` | apply-new / research | 7 | **4** |
| `kima-geonames-wrong` | apply-new / research | 4 | **4** (GeoNames variant) |
| `wd-disagrees` | research | 3 | other |
| `nli-wd-wrong` | report to NLI | 2 | NLI's WD is wrong |
| `nli-034-antimeridian` | runner bug (Gil) | 1 | new |

By confidence: **320 high, 168 medium, 37 low.** By action: 305 apply-new (256 of them extended features — take NLI, per Sinai),
152 keep+report, 67 research, 1 runner bug.

### Recurring cases I can recognise beyond your five

**A. `034` fraction lost a leading zero (45 cases, all `gooearth`).** Fritzlar:
`$f 051.2005175 $g 051.836979` — south edge north of north edge, and one digit shorter.
Re-insert the `0` (`051.0836979`) and the centre lands on Fritzlar, 1 km from Kima. Detector:
box > 0.25° on one axis, one subfield's fraction one digit short, re-inserting `0` after the
point makes the box narrow **and** puts the centre within 20 km of Kima. This is a pure NLI
data bug, reportable with the exact corrected value (`fix034` column). Mainz, Versailles,
Hollabrunn, Liptovský Mikuláš … are in this pile.

**B. Box crosses the antimeridian (1 case, Siberia).** `$d 057.13 $e -168.99` → the
runner's `(d+e)/2` gives −56°, 6,376 km off. Runner-side bug; proper centre is 124°E.

**C. NLI picked the wrong homonym itself.** Phoenicia's `034` is Phoenicia, N.Y.; Goraj's
box is a different Goraj; Kassel's box is 1° south. These sit in `nli-coords-wrong` —
Wikidata agrees with Kima, NLI's point is alone. Report to NLI.

**D. Kima's GeoNames id points elsewhere (`kima-geonames-wrong`, and many of the
`homonym → apply-new`).** Linden (N.J.) → GeoNames 3377408 = Linden, Guyana; Geneva (N.Y.),
Boston Harbor, Monticello (Va.), East Bay (Calif.) all sit thousands of km off because
Kima holds a same-named place from another continent. Rule: NLI's own WD sits on NLI's
point **and** the heading has a qualifier **and** the move is ≥ 500 km → NLI is
authoritative, apply-new.

**E. Kima's WD is a near-synonym, not the place** — Stanislav → Ivano-Frankivsk,
Azerbaijan (Iran) → Atropatene, Etters-Berg (NLI) → Ettersburg the town vs the mountain.
Worth a human look, but the WD labels make the decision obvious in seconds.

### What I'd auto-resolve

- `extended-feature` **high** (200): rivers/regions where the move is within the feature's
  Wikidata extent (area / length) or NLI's own bounding box. Your 13 `river` + 16 `region`
  decisions all land here. Decided 2026-08-22: **take NLI** for the whole bucket.
- `nli-034-dropped-zero` (45): keep Kima; send NLI the list with corrected values.
- `kima-coords-wrong` high (9) and `homonym → apply-new` (35): apply NLI. Worth a 5-minute
  eyeball of the TSV, not a per-case review.
- `nli-coords-wrong` high (60): keep Kima, report to NLI.

### What still needs you

- `homonym → research` (23): both entities match the name and sit on their own point —
  Falkenberg, Channel Islands (Calif.), Thousand Islands (Indonesia), Miroslav-style
  disambiguation. The TSV gives both QIDs and labels side by side.
- `no-wd` (34): nothing to arbitrate with — Schopfloch, Berguent, Bököny (8,126 km!),
  Gâtine. Most of the > 1,000 km ones are almost certainly wrong Kima points, but there is
  no witness.
- `nli-coords-wrong` **medium** (46): only Kima's side has an entity; NLI's point is alone
  but unrefuted.

### Agreement with your 68 existing decisions

29/29 of your `river`/`region` → `extended-feature`. Your `keep-existing` (25) → mostly
`nli-coords-wrong` / `nli-034-dropped-zero` / `extended-feature`. Your `apply-new` (16) →
`homonym`/`kima-wd-wrong` (9), `extended-feature` (5, see above). Your `research` (8) →
`no-wd`/`homonym`/medium buckets. No decision of yours landed in a high-confidence bucket
pointing the opposite way, except Podhale (you kept Kima; NLI's WD point is NLI's) and
Yiftahel (you kept Kima although its WD is Hierapolis).

### Where are the duplicate מחוזות?

Not here. The tier collisions (Osh vs Osh oblast, Zlín vs Zlínský kraj …) are two *different
NLI records* sharing one Hebrew heading, so they surface as `dup-places-diff` /
`disambiguation.tsv`, never as `location-move` — every case in this file has the Kima place
already bound to the incoming record's own id. The tier *ambiguity* does leak in through one
door: `homonym → research` cases where Kima's Wikidata entity is the district and NLI's is
the town (or vice versa) under one heading — Mandya (India) vs Mandya district, Manica
(Mozambique : Province) vs Manica, Aisén (Chile : Province) vs Aysén Province, Zaporizhia.
Five or so cases; they belong with the disambiguation pile rather than the coordinates pile.

## Files

- `app/classify_moves.py` — the classifier; re-runnable offline (`.cache/wikidata.json`).
- `app/move-analysis.tsv` — one row per case: bucket, action, confidence, note, both
  QIDs + labels + coordinates + pairwise distances, `fix034`, your existing decision.
