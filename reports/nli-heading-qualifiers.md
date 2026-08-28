# Hebrew headings that do not say what kind of place the record is

Draft for discussion — generated 2026-08-28 from the
NLI weekly update reports. **Not yet sent to the library.**

Two requests, both the same shape: NLI's Roman `151` states what kind of entity a
record describes, and the Hebrew `151` frequently does not. Kima consumes the Hebrew
heading, so the distinction is lost on our side and two different places end up
competing for one Hebrew string.

Nothing here asks NLI to change a coordinate or merge a record. Both asks are about
the heading only.

---

## Part 1 — Extended features (river, region, range, island group …)

### The pattern

`Beauce (France)` is a river. Its Hebrew heading is `בוס (צרפת)` — a name and a
country, with nothing saying it is a river. A cataloguer or a downstream consumer
reading only the Hebrew cannot tell it from a town called Beauce.

This matters to us concretely: an extended feature has no single correct point, so
NLI's coordinate and ours can differ by tens of kilometres while both being right.
When the Hebrew heading does not say the record is a river, our pipeline treats that
difference as an error to be reconciled rather than a property of the entity.

### NLI already does this — inconsistently

This is the heart of the request. Of **321**
extended features in the current reports:

* **212** already carry a Hebrew type word — `הים הלבן`, `מיצרי מגלן`,
  `נהר סנט מרי'ס`, `אוהיו (נהר)`
* **42** do not, and we think should
* **67** we are not asking about (see below)

So the practice exists and is well established. The ask is to extend it to the
records that were missed, not to adopt something new.

Type words already in use, by frequency:

| Hebrew type word | records |
|---|---|
| נהר | 82 |
| ים | 26 |
| אי | 23 |
| איי | 10 |
| הרי | 10 |
| מפרץ | 6 |
| נחל | 5 |
| שמורת | 3 |
| מיצר | 3 |
| רמת | 3 |
| עמק | 2 |
| ביצות | 2 |
| יער | 2 |
| מישור | 2 |
| אגם | 2 |

### What we would suggest

| proposed word | records |
|---|---|
| אזור | 12 |
| נהר | 10 |
| איים | 4 |
| גן לאומי | 3 |
| עמק | 2 |
| חוף | 2 |
| חצי האי | 1 |
| יער | 1 |
| מישור | 1 |
| מיצר | 1 |
| הרי | 1 |
| מדבר | 1 |
| הר | 1 |
| שמורה | 1 |
| מפרץ | 1 |

Full list: **`qualifiers-suggested.csv`**. Every row carries the NLI id, both
headings, the Wikidata entity **and its plain-language type**, the distance between
NLI's point and ours, and the proposed Hebrew heading.

First rows for orientation:

| NLI id | Hebrew now | Roman | Wikidata type | proposed Hebrew |
|---|---|---|---|---|
| 987007548212005171 | הודו-סין | Indochina | peninsula / region | חצי האי הודו-סין |
| 987007558385105171 | פודהייל (פולין) | Podhale (Poland) | valley | עמק פודהייל (פולין) |
| 987007558563405171 | גאלווי (סקוטלנד) | Galloway (Scotland) | region | אזור גאלווי (סקוטלנד) |
| 987007541357205171 | סיביר (רוסיה) | Siberia (Russia) | region | אזור סיביר (רוסיה) |
| 987011433526905171 | ריו גרנדה (קולורדו-מקסיקו וטקסס) | Rio Grande (Colo.-Mexico and Tex.) | river / border river | נהר ריו גרנדה (קולורדו-מקסיקו וטקסס) |
| 987007553466805171 | אואטר בנקס (קרולינה הצפונית) | Outer Banks (N.C.) | barrier island / island / island group | איים אואטר בנקס (קרולינה הצפונית) |
| 987007534295705171 | ביג ת'יקט (טקסס) | Big Thicket (Tex.) | forest | יער ביג ת'יקט (טקסס) |
| 987007550889705171 | לברדור (ניופאונדלנד ולברדור) | Labrador (N.L.) | region | אזור לברדור (ניופאונדלנד ולברדור) |
| 987007554286305171 | קומאטי | Komati River | river | נהר קומאטי |
| 987007553768505171 | פרוט | Prut River | river | נהר פרוט |
| 987007562835605171 | דראווה | Drava River | river / transboundary river / border river | נהר דראווה |
| 987007533595705171 | לאנואסטקדו | Llano Estacado | mesa / plain | מישור לאנואסטקדו |

### What we are deliberately not asking about

**`qualifiers-not-suggested.csv`** (67 records) — kept in the report so
the exclusions are auditable rather than invisible:

* types where a qualifier would be wrong — `אירופה`, `אוקיאניה`: you do not qualify a
  continent
* types where a qualifier would be right but we have no Hebrew word we trust —
  *upland*, *plateau*, *massif*. `מאסיף סנטרל (צרפת)` sits here. **If NLI has an
  established usage for these we would adopt it**; we would rather ask than guess
* records whose Wikidata type is too vague to act on (`geographical feature`)
* records with no usable Wikidata type at all

### Honest limitations

1. **The proposals are machine-generated from Wikidata `P31` and need a cataloguer's
   eye.** In testing, roughly one in six was wrong before filtering. Treat every row as
   a proposal, not a finding. Where no Hebrew word could be proposed with confidence the
   record was excluded rather than guessed at — `upland`, `plateau` and `massif` are
   left out for this reason, so `מאסיף סנטרל (צרפת)` does not appear below.
2. **The word choice is ours, not authoritative.** `אזור` for *region*, `נהר` for
   *river* and `חוף` for *coast* we are confident in; anywhere else we would defer to
   NLI's own usage.
3. **This is a sample, not the whole authority file.** These are only the records that
   surfaced in weekly update reports between 2024-06 and 2026-08 — records that
   changed. The same gap almost certainly exists across records that did not change.

### If NLI declines

We would record the feature type on our side instead, in Kima's `LocationTypeId`
field. The column `kima_fallback_location_type_id` in the CSV carries the value we
would set, with `kima_fallback_meaning` spelling it out in words. Values observed in
Kima today:

| LocationTypeId | Hebrew | meaning |
|---|---|---|
|  | לא הוגדר | no type recorded in Kima |
| 1 | יישוב / נקודה | settlement / point feature |
| 2 | אזור / ישות מורחבת | region / extended feature |

This is a poorer outcome — the distinction would live only in Kima and stay invisible
to every other consumer of NLI's authority data — but it is workable.

**A finding on our own side, recorded here so it is not lost.** Looking up Kima's
stored type for all 321 extended features shows the field is mostly wrong or unset:

| Kima's stored type | records |
|---|---|
| settlement / point feature | 180 |
| no type recorded in Kima | 85 |
| region / extended feature | 56 |

Only 56 of 321 are typed as regions. **180 extended features — rivers,
mountain ranges, seas — are typed in Kima as settlements or point features**, and
85 have no type at all. So the fallback above is not simply a matter of writing a
value we already hold: the existing values would have to be corrected first. This is
Kima's problem, not NLI's, and it is being tracked separately.

---

## Part 2 — Administrative tiers

### The pattern

`Pardubice (Czech Republic : Okres)` is a district. `Pardubický kraj` is the region
containing it. Both carry the Hebrew heading `פרדוביצה (צ'כיה : מחוז)`, because Hebrew
flattens roughly 45 distinct Roman tier words into `מחוז` / `פרובינציה`, and 231 place
headings carry no tier word at all.

The Roman `151` is unique. The Hebrew `151` is not. Where NLI's own uniqueness
constraint applies to the Roman heading, the same two records collide in Hebrew.

### What this costs us

Kima has already made the distinction by hand for **19** of these,
creating tier-qualified Hebrew headings. Because NLI's flat Hebrew is re-sent on every
update, our pipeline reads it as a competing heading and reports a collision.

Four further cases were reported to us as *"no Kima place owns this heading"* when in
fact the place existed — under a tier-qualified form our automatic lookup could not
match: Kharkiv raion, Chernivtsi oblast, Dalian Shi, Bohemia Kingdom.

### The ask

Apply the same uniqueness constraint to the Hebrew `151` as to the Roman, using a
fixed tier vocabulary and the qualifier form `X (country : tier)` — not the prefix
form `מחוז X`, which sorts badly and reads as part of the name.

| NLI id | Hebrew now | Roman | tier in Roman | proposed Hebrew |
|---|---|---|---|---|
| 987007480110005171 | פרדוביצה (צ'כיה : מחוז) | Pardubice (Czech Republic : Okres) | okres | פרדוביצה (צ'כיה : נפה) |
| 987007557512105171 | אישיגאקי (יפן) | Ishigaki-shi (Japan) | shi | אישיגאקי (יפן : עיר) |
| 987007566720805171 | מחוז הורדנה (בלארוס) | Hrodzenskai︠a︡ voblastsʹ (Belarus) | voblastsʹ | הורדנה (בלארוס : מחוז) |
| 987007480110605171 | ליברץ (צ'כיה) | Liberecký kraj (Czech Republic) | kraj | ליברץ (צ'כיה : מחוז) |
| 987007479992705171 | זלין (צ'כיה) | Zlínský kraj (Czech Republic) | kraj | זלין (צ'כיה : מחוז) |
| 987007562028305171 | מחוז מינסק (בלארוס) | Minskai︠a︡ voblastsʹ (Belarus) | voblastsʹ | מינסק (בלארוס : מחוז) |
| 987007564837905171 | פיוטרקוב (פולין : מחוז) | Piotrków Trybunalski (Poland : Voivodeship) | voivodeship | פיוטרקוב (פולין : מחוז) |
| 987007535451305171 | אאכן (גרמניה : מחוז) | Aachen (Germany : Regierungsbezirk) | regierungsbezirk | אאכן (גרמניה : מחוז ממשל) |
| 987007552845305171 | קושאלין (פולין : מחוז) | Koszalin (Poland : Voivodeship) | voivodeship | קושאלין (פולין : מחוז) |
| 987007557595805171 | ויימאר (גרמניה : מחוז) | Weimar (Germany : Landkreis) | landkreis | ויימאר (גרמניה : נפה) |
| 987007566933405171 | קוטבוס (גרמניה : מחוז) | Cottbus (Germany : Landkreis) | landkreis | קוטבוס (גרמניה : נפה) |
| 987007550246505171 | בידגושץ' (פולין : מחוז) | Bydgoszcz (Poland : Powiat) | powiat | בידגושץ' (פולין : נפה) |
| 987007557599905171 | פוטסדם (גרמניה : מחוז) | Potsdam (Germany : Stadtkreis) | stadtkreis | פוטסדם (גרמניה : עיר-נפה) |
| 987007487056105171 | סובאלק (פולין : מחוז) | Suwałki (Poland : Powiat) | powiat | סובאלק (פולין : נפה) |

Full list with the Kima side: **`tier-suggested.csv`**.

### The vocabulary is not settled

⚠️ **The Hebrew tier words above are a working assumption**, taken from our internal
`tier-vocabulary.md` §3a: `מחוז` / `נפה` / `עיר-נפה` / `פלך` / `מחוז ממשל`. We have not
finalised it, and would rather agree it with NLI than impose it. The mapping used to
generate this draft:

| Roman tier word | proposed Hebrew |
|---|---|
| kraj | מחוז |
| voblasts | מחוז |
| voblastsʹ | מחוז |
| oblast | מחוז |
| oblastʹ | מחוז |
| województwo | מחוז |
| voivodeship | מחוז |
| departement | מחוז |
| département | מחוז |
| province | מחוז |
| prefecture | מחוז |
| regierungsbezirk | מחוז ממשל |
| okres | נפה |
| raion | נפה |
| raĭon | נפה |
| powiat | נפה |
| landkreis | נפה |
| kreis | נפה |
| county | נפה |
| district | נפה |
| shi | עיר |
| municipality | עיר |
| stadtkreis | עיר-נפה |
| gubernia | פלך |
| guberniya | פלך |

Where the same Hebrew word serves several Roman tiers, that is a deliberate collapse,
not an oversight — but it is exactly the kind of decision worth making together.

---

## Files

| file | rows | what it is |
|---|---|---|
| `qualifiers-suggested.csv` | 42 | extended features we suggest adding a type word to |
| `qualifiers-already-present.csv` | 212 | extended features whose Hebrew already names the type — the precedent |
| `qualifiers-not-suggested.csv` | 67 | deliberately excluded, with the reason per row |
| `tier-suggested.csv` | 19 | administrative-tier collisions with a proposed Hebrew heading |

Every column naming an identifier is paired with a column stating in words what it
means, so no row requires resolving an id to be read.
