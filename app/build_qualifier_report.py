#!/usr/bin/env python3
"""Build the NLI heading-qualifier report.

Two families of suggestion to the library, both of the same shape — NLI's Hebrew
151 does not say what kind of entity the record is, while its Roman 151 does:

  * extended features (river / region / range ...) -> add a type word
  * administrative tiers (okres / kraj / oblast ...) -> add a tier qualifier

Every id column is paired with a plain-language column, so a reader never has to
resolve an identifier to follow the argument.

Output: reports/*.csv  +  reports/nli-heading-qualifiers.md
"""
import json, re, csv, os, collections

APP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP)
OUT = os.path.join(ROOT, 'reports')
os.makedirs(OUT, exist_ok=True)

moves = json.load(open(os.path.join(APP, 'move-analysis.json')))
# Kima's own type per place, fetched from the API (move-analysis does not carry it).
_lt = os.path.join(APP, '.cache', 'kima_loctype.json')
KIMA_LT = json.load(open(_lt)) if os.path.exists(_lt) else {}
dups = json.load(open(os.path.join(APP, 'dup-classification.json')))
dupinfo = {r['recordId']: r for r in json.load(open(os.path.join(APP, 'dup-analysis.json')))}

# ---------------------------------------------------------------- vocabulary
# Wikidata P31 label -> the Hebrew type word we would ask NLI to add.
P31_HE = {
    'river': 'נהר', 'main stem': 'נהר', 'watercourse': 'נהר', 'border river': 'נהר',
    'lake': 'אגם', 'endorheic lake': 'אגם', 'aeolian lake': 'אגם', 'reservoir': 'מאגר',
    'sea': 'ים', 'marginal sea': 'ים', 'adjacent sea': 'ים', 'ocean': 'אוקיינוס',
    'mountain range': 'הרי', 'mountain': 'הר', 'massif': 'מסיף', 'upland': 'רמה',
    'plateau': 'רמה', 'valley': 'עמק', 'plain': 'מישור', 'canyon': 'קניון',
    'region': 'אזור', 'historical region': 'אזור', 'cultural region': 'אזור',
    'geographic region': 'אזור', 'natural region': 'אזור',
    'peninsula': 'חצי האי', 'strait': 'מיצר', 'bay': 'מפרץ', 'gulf': 'מפרץ',
    'coast': 'חוף', 'cape': 'כף', 'island group': 'איים', 'archipelago': 'איים',
    'desert': 'מדבר', 'oasis': 'נווה מדבר', 'forest': 'יער', 'swamp': 'ביצות',
    'national park': 'גן לאומי', 'protected area': 'שמורה', 'nature reserve': 'שמורת טבע',
    'canal': 'תעלה', 'glacier': 'קרחון', 'volcano': 'הר געש',
}
# Types where a qualifier would be wrong or absurd — never suggest for these.
P31_SKIP = {
    'continent', 'part of the world', 'subcontinent', 'sovereign state', 'country',
    'city', 'municipality', 'town', 'village', 'administrative territorial entity',
    'state', 'federal state', 'human settlement', 'capital city',
    'geographical feature', 'geographical object', 'physico-geographical object',
    'terrain', 'location', 'area',
}
# Hebrew type words already in use — if the heading has one, nothing to suggest.
HE_TYPES = ['נהר', 'נחל', 'אגם', 'ים', 'אוקיינוס', 'מפרץ', 'מיצר', 'מיצרי', 'הר געש',
            'הרי', 'הרים', 'הר', 'רמת', 'רמה', 'עמק', 'מישור', 'מדבר', 'יער', 'ביצות',
            'איי', 'איים', 'אי ', 'חצי האי', 'חוף', 'כף', 'גן לאומי', 'שמורת', 'שמורה',
            'תעלת', 'תעלה', 'קרחון', 'נמל', 'מסיף', 'מאגר', 'נווה מדבר', 'קניון', 'רכס']

# Kima LocationTypeId — the fallback if NLI declines. Derived from the data:
# only 0/1/2 occur. 1 sits on settlements, 2 on regions and extended features.
LOCTYPE = {0: 'לא הוגדר', 1: 'יישוב / נקודה', 2: 'אזור / ישות מורחבת'}
LOCTYPE_NOTE = {
    0: 'no type recorded in Kima',
    1: 'settlement / point feature',
    2: 'region / extended feature',
}

# Roman administrative-tier word -> proposed Hebrew, per tier-vocabulary.md §3a.
# WORKING ASSUMPTION — the vocabulary is not settled; regenerate if it changes.
TIER_HE = {
    'okres': 'נפה', 'kraj': 'מחוז', 'voblasts': 'מחוז', 'voblastsʹ': 'מחוז',
    'oblast': 'מחוז', 'oblastʹ': 'מחוז', 'raion': 'נפה', 'raĭon': 'נפה',
    'powiat': 'נפה', 'gubernia': 'פלך', 'guberniya': 'פלך', 'województwo': 'מחוז',
    'voivodeship': 'מחוז', 'regierungsbezirk': 'מחוז ממשל', 'landkreis': 'נפה',
    'stadtkreis': 'עיר-נפה', 'kreis': 'נפה', 'departement': 'מחוז',
    'département': 'מחוז', 'province': 'מחוז', 'prefecture': 'מחוז',
    'county': 'נפה', 'district': 'נפה', 'shi': 'עיר', 'municipality': 'עיר',
}


def p31_labels(ev):
    return [x.strip() for w in re.findall(r'P31=([^;]+)', ev or '') for x in w.split(' / ')]


def he_base(h):
    return (h or '').split(' (')[0]


def has_he_type(h):
    """True if the Hebrew heading already names the feature type anywhere —
    base or qualifier. "אוהיו (נהר)" counts; only the base was checked before."""
    return any(w.strip() in (h or '') for w in HE_TYPES)


def wd_url(q):
    return 'https://www.wikidata.org/wiki/%s' % q if q else ''


def nli_url(i):
    return 'https://www.nli.org.il/he/authorities/%s' % i if i else ''


# ---------------------------------------------------------------- family 1
rows_sugg, rows_have, rows_skip = [], [], []
for r in moves:
    if r.get('featureType') != 'extended':
        continue
    labs = p31_labels(r.get('featureEvidence'))
    lab_txt = ' / '.join(labs) if labs else ''
    kid = r.get('kimaId')
    lt = KIMA_LT.get(str(kid)) if kid else None
    base = dict(
        nli_id=r['recordId'], nli_url=nli_url(r['recordId']),
        heb_heading=r.get('headingHeb'), rom_heading=r.get('heading'),
        wikidata=r.get('kimaWd') or r.get('nliWd') or '',
        wikidata_url=wd_url(r.get('kimaWd') or r.get('nliWd')),
        wikidata_says=lab_txt,
        wikidata_label=r.get('kimaWdLabel') or '',
        kima_id=kid, kima_url=('https://data.geo-kima.org/Places/Details/%s' % kid) if kid else '',
        kima_heb=r.get('kimaHeb'), kima_rom=r.get('kimaRom'),
        kima_location_type_id=lt if lt is not None else '',
        kima_location_type_meaning=LOCTYPE_NOTE.get(lt, '') if lt is not None else '',
        distance_km=r.get('movedKm'), feature_extent_km=r.get('extentKm'),
        classifier_bucket=r.get('bucket'),
        classifier_bucket_meaning={
            'extended-feature': 'both points lie on the feature — no real move',
            'nli-coords-wrong': "Wikidata backs Kima's point; NLI's stands alone",
            'homonym': 'two same-named places; which one did NLI mean',
            'no-wd': 'no Wikidata entity to arbitrate with',
        }.get(r.get('bucket'), r.get('bucket') or ''),
        period=r.get('period'),
    )
    if has_he_type(r.get('headingHeb')):
        rows_have.append(base | {
            'existing_he_type': next((w.strip() for w in HE_TYPES
                                      if w.strip() in he_base(r.get('headingHeb'))), ''),
            'why': 'Hebrew heading already names the feature type — NLI does do this, '
                   'just not consistently',
        })
        continue
    if any(l in P31_SKIP for l in labs):
        rows_skip.append(base | {'why_skipped':
                                 'type is one where a qualifier would be wrong (%s)' % lab_txt})
        continue
    hit = next((P31_HE[l] for l in labs if l in P31_HE), None)
    if not hit:
        rows_skip.append(base | {'why_skipped':
                                 'no Hebrew type word mapped for: %s' % (lab_txt or 'no P31')})
        continue
    heb = r.get('headingHeb') or ''
    b, rest = he_base(heb), heb[len(he_base(heb)):]
    rows_sugg.append(base | {
        'proposed_he_type': hit,
        'proposed_heb_heading': ('%s %s%s' % (hit, b, rest)) if hit not in ('אזור',)
                                else ('%s %s%s' % (hit, b, rest)),
        'kima_fallback_location_type_id': 2,
        'kima_fallback_meaning': LOCTYPE_NOTE[2],
        'why': 'Roman heading and Wikidata both say this is a %s; the Hebrew heading '
               'does not say what kind of entity it is' % (labs[0] if labs else 'feature'),
    })

# ---------------------------------------------------------------- family 2
rows_tier = []
TIER_BUCKETS = {'already-disambiguated-in-kima', 'tier-pair', 'pseudo-disambiguated-in-kima'}
for c in dups:
    if c.get('bucket') not in TIER_BUCKETS:
        continue
    rid = c['recordId']
    inf = dupinfo.get(rid, {})
    inc = (inf.get('incoming') or {})
    rom = (inc.get('primary') or {}).get('lat') or ''
    heb = (inc.get('primary') or {}).get('heb') or ''
    # The tier sits after a colon — "Pardubice (Czech Republic : Okres)" — or as a
    # trailing word in forms like "Hrodzenskaia voblasts' (Belarus)". Matching the
    # last parenthesised token instead picks up the country, which is never a tier.
    word = ''
    m = re.search(r':\s*([^:()]+?)\s*\)\s*$', rom)
    if m:
        word = m.group(1).strip().lower()
    else:
        head = re.split(r'\s*\(', rom)[0]
        for tok in reversed(re.findall(r"[A-Za-zÀ-ſĀ-ſ'ʹ︠︡]+", head)):
            if tok.rstrip("'ʹ").lower() in TIER_HE:
                word = tok.lower(); break
    tier_he = TIER_HE.get(word.rstrip("'ʹ"), '')
    kp = (inf.get('kimaPlaces') or [{}])
    owner = next((p for p in kp if p.get('how') == 'owns-heading'), {})
    holder = next((p for p in kp if p.get('how') == 'holds-incoming-id'), {})
    rows_tier.append(dict(
        nli_id=rid, nli_url=nli_url(rid), heb_heading=heb, rom_heading=rom,
        roman_tier_word=word, roman_tier_meaning=(
            'the Roman heading names the administrative tier; the Hebrew does not'
            if word else 'no tier word found in the Roman heading'),
        proposed_he_tier=tier_he,
        proposed_heb_heading=(
            '%s (%s : %s)' % (re.sub(r'^(מחוז|נפה|פלך)\s+', '', he_base(heb)),
                              (re.findall(r'\(([^:)]+)', heb) or [''])[0].strip(),
                              tier_he)) if tier_he else '',
        kima_holder_id=holder.get('kimaId', ''),
        kima_holder_heb=holder.get('heb', ''),
        kima_holder_meaning='the Kima place that already holds this NLI record id',
        kima_owner_id=owner.get('kimaId', ''),
        kima_owner_heb=owner.get('heb', ''),
        kima_owner_meaning='a different Kima place that owns the flat Hebrew heading NLI sends',
        distance_km=inf.get('distanceKm', ''),
        classifier_bucket=c.get('bucket'),
        classifier_bucket_meaning={
            'already-disambiguated-in-kima': 'Kima already made the distinction NLI does not',
            'tier-pair': 'only one side of the tier pair exists in Kima',
            'pseudo-disambiguated-in-kima': 'Kima distinguishes only by spelling/punctuation',
        }.get(c.get('bucket'), ''),
        note=c.get('note', ''),
        vocabulary_status='WORKING ASSUMPTION — tier-vocabulary.md §3a, not yet settled',
    ))


def write(name, rows):
    p = os.path.join(OUT, name)
    if not rows:
        return p, 0
    with open(p, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    return p, len(rows)


for n, rs in [('qualifiers-suggested.csv', rows_sugg),
              ('qualifiers-already-present.csv', rows_have),
              ('qualifiers-not-suggested.csv', rows_skip),
              ('tier-suggested.csv', rows_tier)]:
    p, k = write(n, rs)
    print('%-34s %4d rows' % (n, k))

json.dump({'sugg': rows_sugg, 'have': rows_have, 'skip': rows_skip, 'tier': rows_tier},
          open(os.path.join(OUT, '_data.json'), 'w'), ensure_ascii=False)

# ---------------------------------------------------------------- the document
def md_table(rows, cols, limit=None):
    rs = rows[:limit] if limit else rows
    out = ['| ' + ' | '.join(h for _, h in cols) + ' |',
           '|' + '|'.join('---' for _ in cols) + '|']
    for r in rs:
        out.append('| ' + ' | '.join(str(r.get(k, '') or '').replace('|', '\\|')
                                     for k, _ in cols) + ' |')
    return '\n'.join(out)


_allext = rows_sugg + rows_have + rows_skip
_ltc = collections.Counter(r['kima_location_type_meaning'] or 'not fetched' for r in _allext)
n_all = len(_allext)
n_point = _ltc.get('settlement / point feature', 0)
n_region = _ltc.get('region / extended feature', 0)
n_none = _ltc.get('no type recorded in Kima', 0)
loctable = md_table([{'m': k, 'n': v} for k, v in _ltc.most_common()],
                    [('m', "Kima's stored type"), ('n', 'records')])

sugg_by_type = collections.Counter(r['proposed_he_type'] for r in rows_sugg)
have_by_type = collections.Counter(r['existing_he_type'] for r in rows_have if r['existing_he_type'])
tier_ok = [r for r in rows_tier if r['proposed_he_tier']]

doc = f"""# Hebrew headings that do not say what kind of place the record is

Draft for discussion — generated {os.environ.get('REPORT_DATE', '2026-08-28')} from the
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

This is the heart of the request. Of **{len(rows_sugg) + len(rows_have) + len(rows_skip)}**
extended features in the current reports:

* **{len(rows_have)}** already carry a Hebrew type word — `הים הלבן`, `מיצרי מגלן`,
  `נהר סנט מרי'ס`, `אוהיו (נהר)`
* **{len(rows_sugg)}** do not, and we think should
* **{len(rows_skip)}** we are not asking about (see below)

So the practice exists and is well established. The ask is to extend it to the
records that were missed, not to adopt something new.

Type words already in use, by frequency:

{md_table([{'w': w, 'n': n} for w, n in have_by_type.most_common(15)],
          [('w', 'Hebrew type word'), ('n', 'records')])}

### What we would suggest

{md_table([{'t': t, 'n': n} for t, n in sugg_by_type.most_common()],
          [('t', 'proposed word'), ('n', 'records')])}

Full list: **`qualifiers-suggested.csv`**. Every row carries the NLI id, both
headings, the Wikidata entity **and its plain-language type**, the distance between
NLI's point and ours, and the proposed Hebrew heading.

First rows for orientation:

{md_table(rows_sugg, [('nli_id', 'NLI id'), ('heb_heading', 'Hebrew now'),
                      ('rom_heading', 'Roman'), ('wikidata_says', 'Wikidata type'),
                      ('proposed_heb_heading', 'proposed Hebrew')], limit=12)}

### What we are deliberately not asking about

**`qualifiers-not-suggested.csv`** ({len(rows_skip)} records) — kept in the report so
the exclusions are auditable rather than invisible:

* types where a qualifier would be wrong — `אירופה`, `אוקיאניה`: you do not qualify a
  continent
* records whose Wikidata type is too vague to act on (`geographical feature`)
* records with no usable Wikidata type at all

### Honest limitations

1. **The proposals are machine-generated from Wikidata `P31` and need a cataloguer's
   eye.** In testing, roughly one in six was wrong before filtering. One survives in
   the list knowingly: `מאסיף סנטרל (צרפת)`, where Wikidata says
   *non-geologically related mountain range* and the suggestion `רמה` is questionable —
   it is a massif. Treat every row as a proposal, not a finding.
2. **The word choice is ours, not authoritative.** `אזור` for *region* and `נהר` for
   *river* are uncontroversial; `חוף` for *coast* and `רמה` for *upland* are our
   reading and we would defer to NLI's own usage.
3. **This is a sample, not the whole authority file.** These are only the records that
   surfaced in weekly update reports between 2024-06 and 2026-08 — records that
   changed. The same gap almost certainly exists across records that did not change.

### If NLI declines

We would record the feature type on our side instead, in Kima's `LocationTypeId`
field. The column `kima_fallback_location_type_id` in the CSV carries the value we
would set, with `kima_fallback_meaning` spelling it out in words. Values observed in
Kima today:

{md_table([{'i': k, 'm': LOCTYPE_NOTE[k], 'h': LOCTYPE[k]} for k in sorted(LOCTYPE)],
          [('i', 'LocationTypeId'), ('h', 'Hebrew'), ('m', 'meaning')])}

This is a poorer outcome — the distinction would live only in Kima and stay invisible
to every other consumer of NLI's authority data — but it is workable.

**A finding on our own side, recorded here so it is not lost.** Looking up Kima's
stored type for all {n_all} extended features shows the field is mostly wrong or unset:

{loctable}

Only {n_region} of {n_all} are typed as regions. **{n_point} extended features — rivers,
mountain ranges, seas — are typed in Kima as settlements or point features**, and
{n_none} have no type at all. So the fallback above is not simply a matter of writing a
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

Kima has already made the distinction by hand for **{len(rows_tier)}** of these,
creating tier-qualified Hebrew headings. Because NLI's flat Hebrew is re-sent on every
update, our pipeline reads it as a competing heading and reports a collision.

Four further cases were reported to us as *"no Kima place owns this heading"* when in
fact the place existed — under a tier-qualified form our automatic lookup could not
match: Kharkiv raion, Chernivtsi oblast, Dalian Shi, Bohemia Kingdom.

### The ask

Apply the same uniqueness constraint to the Hebrew `151` as to the Roman, using a
fixed tier vocabulary and the qualifier form `X (country : tier)` — not the prefix
form `מחוז X`, which sorts badly and reads as part of the name.

{md_table(tier_ok, [('nli_id', 'NLI id'), ('heb_heading', 'Hebrew now'),
                    ('rom_heading', 'Roman'), ('roman_tier_word', 'tier in Roman'),
                    ('proposed_heb_heading', 'proposed Hebrew')])}

Full list with the Kima side: **`tier-suggested.csv`**.

### The vocabulary is not settled

⚠️ **The Hebrew tier words above are a working assumption**, taken from our internal
`tier-vocabulary.md` §3a: `מחוז` / `נפה` / `עיר-נפה` / `פלך` / `מחוז ממשל`. We have not
finalised it, and would rather agree it with NLI than impose it. The mapping used to
generate this draft:

{md_table([{'r': k, 'h': v} for k, v in sorted(TIER_HE.items(), key=lambda x: x[1])],
          [('r', 'Roman tier word'), ('h', 'proposed Hebrew')])}

Where the same Hebrew word serves several Roman tiers, that is a deliberate collapse,
not an oversight — but it is exactly the kind of decision worth making together.

---

## Files

| file | rows | what it is |
|---|---|---|
| `qualifiers-suggested.csv` | {len(rows_sugg)} | extended features we suggest adding a type word to |
| `qualifiers-already-present.csv` | {len(rows_have)} | extended features whose Hebrew already names the type — the precedent |
| `qualifiers-not-suggested.csv` | {len(rows_skip)} | deliberately excluded, with the reason per row |
| `tier-suggested.csv` | {len(rows_tier)} | administrative-tier collisions with a proposed Hebrew heading |

Every column naming an identifier is paired with a column stating in words what it
means, so no row requires resolving an id to be read.
"""

open(os.path.join(OUT, 'nli-heading-qualifiers.md'), 'w', encoding='utf-8').write(doc)
print('nli-heading-qualifiers.md      %d bytes' % len(doc))
