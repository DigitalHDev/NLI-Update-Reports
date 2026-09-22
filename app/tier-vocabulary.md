# Administrative-tier vocabulary: how NLI and Kima render it in Hebrew, and a fix

Written 2026-08-23. Numbers from the Kima dump `20250126KimaPlacesCSVx.csv` (Kima's primary
Hebrew is NLI's `151 $9 heb`, so the dump is a census of NLI's own Hebrew practice), the
weekly `places_*.json` MARC (843 records with a Roman `: tier` qualifier), and the 14
`already-disambiguated-in-kima` pairs from `dup-classification.tsv`.

## 1. What NLI does

The Roman `151` is built on the LC pattern `Name (Country : Tier)` and is precise —
102 distinct *administrative* tier words in the dump, 49 of them recurring 3+ times
(re-verified 2026-09-22; an earlier draft said 45, which was a partial count — the raw
figure is 177 qualifier strings, the rest being feature types, date ranges and one-offs)
(Province 512, Landkreis 181, District 170, Town 109,
Region 71, Okres 64, State 61, Powiat 60, County 52, Voivodeship 45, Dept. 42, Township 37,
Kreis 35, Canton 29, Județ 21, Politischer Bezirk 17, Regierungsbezirk 16, Raion, Oblast,
Bezirk, Stadtkreis, Shahristān, Amphoe, Rrethi, Obshtina, Kabupaten …).

The Hebrew `151` collapses that into **two words**:

| Roman tier | Hebrew | rows |
|---|---|---:|
| Province | פרובינציה | 499 (+11 מחוז) |
| Landkreis, District, Okres, Powiat, County, Dept., Voivodeship, Kreis, Department, Județ, Politischer Bezirk, Regierungsbezirk, Prefecture, Raion, Bezirk, Oblast, Stadtkreis, Rrethi, Amphoe, Občina, Division, Shire, Arrondissement … | **מחוז** | ≈ 900 |
| State | מדינה | 56 |
| Region | אזור | 68 |
| Canton | קנטון | 27 |

Three further irregularities, all NLI's:

1. **No tier at all** in 89 of 1,978 Hebrew headings whose Roman has one (re-verified
   2026-09-22; an earlier draft said 231, which no reading of the data reproduces) — `Stanisławów
   (Poland : Voivodeship)` → `סטניסלבוב (פולין)`; `Edison (N.J. : Township)` → `אדיסון (ניו
   ג'רזי)`. These are the ones that collide *exactly* with the town heading.
2. **Prefix vs qualifier form.** `מחוז X (country)` in 2,808 headings — and 154 headings
   carry the word *twice*, `מחוז דמין (גרמניה : מחוז)` — (Landkreis 77, Okres 33,
   Powiat 24 …) versus `X (country : מחוז)` in 889. Both for the same Roman tiers. A prefix
   heading and a qualifier heading for the same name do not collide as strings but are the
   same ambiguity to a reader (`מחוז מינסק (בלארוס)` = raion, `מינסק (בלארוס:אובלסט)` = oblast).
3. **Same word across levels inside one country.** Poland: Voivodeship → מחוז *and* Powiat →
   מחוז. Germany: seven distinct Roman tiers → all מחוז (Regierungsbezirk, Landkreis, Kreis,
   Stadtkreis, Bezirk, Amt, Landesbezirk), and ten countries collapse 3+ tiers this way. Czechia: Okres → מחוז
   (but Kraj → אזור, not מחוז — an earlier draft had this wrong). That is the direct cause of the `tier-pair` collisions
   (Bydgoszcz, Koszalin, Piotrków, Aachen, Cottbus, Potsdam, Weimar, Pardubice, Liberec, Zlín).

Root cause, restated: **NLI enforces uniqueness on the Roman heading only**, so nothing
forces the Hebrew to carry the distinction.

## 2. What Kima did on top of that

The 2025-01 dump has **zero** duplicate Hebrew primaries — Kima enforces uniqueness. When
the runner hit the collisions above, places were created (ids 90xxx, 2025–26) with ad-hoc
Hebrew that no longer matches NLI *or* each other:

| Roman tier | Kima new heading | NLI elsewhere |
|---|---|---|
| Voivodeship (Piotrków, Koszalin) | `פרובינציה` | מחוז (36 rows) |
| Okres (Pardubice) | `מחוז משנה` | מחוז (62 rows) |
| Regierungsbezirk (Aachen) | `מחוז שלטוני` | מחוז (11) / מחוז שלטוני (4, older Kima rows) |
| oblast / voblasts (Osh, Minsk, Hrodna) | `אובלסט` | מחוז (5) |
| kraj (Liberec, Zlín) | `מחוז` | — |
| Sub-District (Tulkarem) | `תת-מחוז` | — |
| Bashkia (Vlorë) | `עיריה` | עירייה (Obshtina, Kunta) |
| Landkreis / Stadtkreis (Weimar) | `מחוז` both, distinguished by spelling ויימאר/וימאר | — |
| Powiat / gubernia (Suwałki) | `מחוז` both, distinguished by `,` vs `:` | — |

So Kima now runs three regimes at once: NLI's flattened מחוז (the bulk), NLI's פרובינציה
island, and the ad-hoc 2025–26 words. And because the runner copies NLI's Hebrew into
`PrimaryHebFull` on every update, every one of these 14 places is reported as a duplicate
**every week** — they are the `already-disambiguated-in-kima` bucket.

## 3. Proposed fix

### 3a. One closed table, semantic levels, native word only where levels run out

The principle: the Hebrew qualifier must distinguish every Roman tier that exists *within
one country*. Two-level semantic words cover nearly every country; a transliterated native
term is used only where a country has a third level or an era distinction.

| level | Hebrew | Roman tiers mapped |
|---|---|---|
| first-level unit | **מחוז** | Voivodeship, Kraj, Oblast/Voblasts, Județ, Province-as-level-1 where no "Province" word exists (Rrethi, Amphoe …), Regierungsbezirk*, Bezirk (GDR)*, Prefecture, Department/Dept., Division, Shire |
| second-level unit | **נפה** | Powiat, Okres, Landkreis, Kreis, Politischer Bezirk, Raion/Raionul, District (when under a מחוז), County, Arrondissement, Opština/Občina |
| urban unit equal to a נפה | **עיר-נפה** | Stadtkreis, kreisfreie Stadt, city-county |
| historical imperial unit | **פלך** | Gubernia (already 17 rows in NLI — keep) |
| keep as is | פרובינציה / מדינה / אזור / קנטון / מועצה אזורית / עירייה | Province / State / Region / Canton / Mo'atsah azorit / Municipality, Obshtina, Bashkia, Kunta |
| sub-district (Mandate) | **תת-מחוז** | Sub-District — keep, it is already NLI-style |

\* Germany has three levels (Regierungsbezirk > Landkreis > Gemeinde, plus Stadtkreis
beside Landkreis, plus GDR Bezirk 1952–90). Use: Regierungsbezirk → **מחוז ממשל**
(the 4 older Kima rows already say מחוז שלטוני — pick one, I'd take מחוז ממשל as it is the
Hebrew Wikipedia term), Bezirk (GDR) → **מחוז (מזרח גרמניה)**, Landkreis → נפה,
Stadtkreis → עיר-נפה.

Do **not** transliterate (אובלסט, פוביאט, אוקרס): it is exact but reads as foreign, and it is
unnecessary once מחוז / נפה are reserved for level 1 / level 2. The only place a native word
stays is פלך, which is established Hebrew historiography.

### 3b. One form: qualifier, not prefix

Write `X (country : tier)`, never `מחוז X (country)`. Reason: the qualifier form sorts and
collides with the town heading in a visible way, the prefix form hides the relationship and
is what produced `מחוז מינסק` vs `מינסק (:אובלסט)`. (Geographic features keep their natural
prefix — `נהר`, `אגם`, `הר`, `אזור` for Region — those are part of the name, not a tier.)

### 3c. Where the fix has to live

Kima mirrors NLI's Hebrew, so a Kima-only rename is undone by the next feed unless one of:

1. **NLI adopts the table** — the A2 ask in REVIEW-PLAN. The 14 already-disambiguated pairs
   plus the 9 pending ones are the worked examples; the table above is the concrete proposal.
   This is the only fix that stops the problem recurring.
2. **Runner rule (Gil)**: when Kima's `PrimaryHebFull` differs from NLI's *only by a tier
   qualifier* (strip `(… : word)` on both sides and compare), keep Kima's heading, store NLI's
   as a variant, and do not raise a duplicate. That stops the weekly re-reporting of the 14
   and makes Kima-side disambiguation stable while NLI decides. Worth an issue alongside #2–#7.

### 3d. Scope of the Kima clean-up

Do **not** mass-rename the ~900 מחוז rows: they are NLI's headings, unique today, and renaming
them creates exactly the churn 3c describes. Rename only where two Kima places share a base
name and country — the 14 + 9 cases — and apply the table to *new* collisions from now on.
Keep every replaced heading as a Hebrew variant, so search still finds the old form.

## 4. The remaining tier headings, under the table

### Pending pairs (only one side in Kima, or pseudo-disambiguated)

| pair | A (incoming) | B (in Kima) |
|---|---|---|
| Cottbus | Landkreis → `קוטבוס (גרמניה : נפה)` | Bezirk → `קוטבוס (גרמניה : מחוז, מזרח גרמניה)` (today `קוטבוס (גרמניה : מחוז)`) |
| Bydgoszcz | Powiat → `בידגושץ' (פולין : נפה)` | Voivodeship → `בידגושץ' (פולין : מחוז)` (keep) |
| Potsdam | Stadtkreis → `פוטסדם (גרמניה : עיר-נפה)` | Bezirk → `פוטסדם (גרמניה : מחוז, מזרח גרמניה)` |
| Weimar | Landkreis → `ויימאר (גרמניה : נפה)` | Stadtkreis → `ויימאר (גרמניה : עיר-נפה)` — and one spelling, ויימאר, matching the city |
| Suwałki | Powiat → `סובאלק (פולין : נפה)` | Gubernia → `סובאלק (פולין : פלך)` |
| Russian Far East | federal okrug → `המזרח הרחוק (רוסיה : מחוז פדרלי)` | region → `המזרח הרחוק הרוסי (רוסיה)` (keep) |

### Normalise the 14 already-disambiguated to the same table

Piotrków, Koszalin `פרובינציה` → `מחוז`; Pardubice `מחוז משנה` → `נפה`; Aachen `מחוז שלטוני`
→ `מחוז ממשל`; Osh / Minsk / Hrodna `אובלסט` → `מחוז`, and their raion twins `מחוז X` →
`X (בלארוס : נפה)`; Liberec / Zlín `מחוז` — keep; Tulkarem `תת-מחוז` — keep; Vlorë
`עיריה` → `עירייה` (spelling used elsewhere); Ishigaki `אי` — keep (feature, not tier);
Elba/Alba, Bobigny/Bouvignies — not tier cases, fine as they are.

### The four tier ambiguities that surfaced in the coordinate pile

| case | what Wikidata says | action |
|---|---|---|
| Mandya (India) | NLI WD = city Q10790951, Kima WD = Mandya district Q2768290; heading has no tier | Kima is the district (coords, WD) but the NLI record is the city: **repoint Kima's WD + coords to the city** (apply-new); the district, if wanted, is a separate NLI record |
| Manica (Mozambique : Province) | heading says Province; NLI WD Q383170 is the *town*, Kima WD Q622792 the province | NLI's WD is wrong → report; keep Kima |
| Aisén (Chile : Province) | heading says Province; NLI WD Q3651 is the *region*, Kima Q201126 the province | NLI's WD is wrong → report; keep Kima |
| Zaporizhia (Ukraine) | NLI record's own WD is the Luhansk village Q4186983; Kima has the city (GeoNames 687700) | your earlier note stands: NLI's identity is suspect; research, likely report |

All of this is in `dup-classification.tsv` (`suggestA` / `suggestB` columns carry the
mechanical first guess; the table in §3a is what they should be normalised to).
