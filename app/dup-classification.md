# Duplicate-heading pile — classification and recommended actions

Written 2026-08-22. Produced by `app/classify_dups.py` → `app/dup-classification.{tsv,json}`,
from `app/dup-analysis.json` (213 reported duplications; the 145 `same-id` rows are
collisions inside one record and are excluded here). 68 cases remain.

Pair = **A**, the record the feed announced, vs **B**, the record bound to the Kima place
that owns the same Hebrew heading. Wikidata (QID from `024`, else `haswbstatement:P8189`)
supplies P31 class, coordinates and labels for both.

## Result

| bucket | n | action | who |
|---|---:|---|---|
| `heading-drift` | 25 | update Kima's Hebrew heading to NLI's, keep old as variant | Kima, mechanical |
| `already-disambiguated-in-kima` | 14 | nothing to bind; NLI's flat Hebrew stays a variant of A | none |
| `kima-id-suppressed` | 7 | repoint Kima place to A (successor), adopt A's names/coords, keep old as variants | Kima, mechanical |
| `unresolved` | 6 | look up by hand (no Kima owner found) | Sinai |
| `distinct-homonym` | 8 | give the Hebrew the distinction the Roman already carries | Sinai → NLI |
| `tier-pair` | 3 | Hebrew tier word (town / נפה / מחוז) | Sinai → NLI |
| `same-entity` | 3 | report duplicate to NLI | NLI |
| `pseudo-disambiguated-in-kima` | 2 | Kima headings differ only in spelling/punctuation — still ambiguous | Kima |

### What each bucket is

**`heading-drift` (25).** Kima already holds A's id; only the Hebrew heading spelling differs
(נורקופינג (שוודיה) / (שבדיה); ראוניון / ריוניון; אריתריאה / אריתראה). No second
record is involved, so the "duplicate variant" the runner reported is the record colliding
with itself after a heading rename. Mechanical: adopt NLI's heading, keep Kima's as a variant.
Caveat: the runner did not say *which* place the variant collided with; in all 25 the place
holding A's id exists, so the self-collision reading is the likely one.

**`already-disambiguated-in-kima` (14).** Kima holds **both** A and B, and the A-place
already carries a tier-qualified heading — `אוש (קירגיזסטן:אובלסט)` vs `אוש (קירגיזסטן)`,
`זלין (צ'כיה:מחוז)` vs `זלין (צ'כיה)`, `אלבה (אי, איטליה)` vs `אלבה (איטליה)`. The
report fires only because NLI's own Hebrew `151` for A equals the heading Kima uses for B.
Nothing to do in Kima. It *is* a list of 14 worked examples to hand NLI for the Hebrew
disambiguation ask (A2 in REVIEW-PLAN).

One thing this bucket exposes: the tier vocabulary Kima used is inconsistent — Voivodeship
became `פרובינציה` (Piotrków, Koszalin), Okres became `מחוז משנה`, Regierungsbezirk
`מחוז שלטוני`, oblast `אובלסט`. Worth settling one table before touching the next eight.

**`pseudo-disambiguated-in-kima` (2).** Weimar: `וימאר (גרמניה : מחוז)` vs
`ויימאר (גרמניה : מחוז)` — Landkreis vs Stadtkreis separated by a yod. Suwałki:
`סובאלק (פולין, מחוז)` vs `סובאלק (פולין : מחוז)` — powiat vs gubernia separated by a comma.
Real disambiguation needed.

**`tier-pair` (3)** — Cottbus (Landkreis / Bezirk), Bydgoszcz (Powiat / Voivodeship),
Potsdam (Stadtkreis / Bezirk). Only B is in Kima; A needs a new Kima place with a tiered
heading (`suggestA` / `suggestB` columns carry a proposal).

**`distinct-homonym` (8)** — different places, one Hebrew form:

| A | B | km | note |
|---|---|---:|---|
| Ardeşen (Turkey) | Trabzon (Turkey) | 108 | **A's Hebrew `טרבזון` is wrong** — NLI error, report |
| Kaba (Hungary) | Káva (Hungary) | 127 | spelling: קבה / קאבה |
| Elba / Alba — already handled (in Kima bucket above) | | | |
| Ehningen | Eningen unter Achalm | 31 | spelling |
| Osterwieck | Osterwick | ? | your note: Osterwick is a hamlet, unlikely intended — merge in Kima, report |
| Hochstätten | Hochstetten | ? | spelling |
| Lüben (Poland today: Lubin) | Lübben (Spreewald) | 170 | לובין / לובן |
| Cherniïv | Chernihiv | 553 | צ'רנייב / צ'רניהיב |
| Dalʹnevostochnyĭ federalʹnyĭ okrug | Russian Far East | — | federal district vs region — really a tier pair |

**`same-entity` (3)** — both records carry the same QID, so the duplicate is NLI's:
El Albaicín / Albaicín (Q576339), Moshavah ha-Yevanit / Greek Colony (Q2916738,
transliteration vs translation), Dobrich / Tolbukhin (co-located; Tolbukhin is the 1949–90
name — NLI may intend a historical heading, check `551`). Report; Kima keeps one id and
stores the other's names as variants.

**`kima-id-suppressed` (7)** — Bystrowice, South Sudan, Tibetan Plateau, Mahilioŭ oblast,
France Southern, Betar, China. B returns HTTP 500 from NLI; A is the live successor.
Repoint mechanically (the דרום סודאן worked example in session-a).

**`unresolved` (6)** — Planes (Spain), Kharkiv raion, Dalian Shi, Bohemia (Kingdom),
Trzebicz, Chernivtsi oblast: no Kima place owns the heading or holds the id. Probably the
collision partner is under a Hebrew form the lookup didn't try.

## What I'd do, in order

1. Mechanical, no review: `heading-drift` (25) + `kima-id-suppressed` (7) = 32 cases.
2. Nothing: `already-disambiguated-in-kima` (14) — but keep the list for NLI.
3. One sitting: decide the Hebrew tier vocabulary, then `tier-pair` (3) + `pseudo` (2) +
   Far East (1) = 6 headings.
4. One sitting: the 7 spelling homonyms + Trabzon error.
5. Report to NLI: 3 `same-entity`, Trabzon, and the 14 + 6 disambiguation examples as the
   policy case.
6. `unresolved` (6) by hand.
