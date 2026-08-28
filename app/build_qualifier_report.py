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
    'mountain range': 'הרי', 'mountain': 'הר',
    'valley': 'עמק', 'plain': 'מישור', 'canyon': 'קניון',
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
# Types where a qualifier would be right but we have no Hebrew word we trust.
# רמה was proposed for these and rejected as doubtful for a massif (Massif Central).
# Listed separately from P31_SKIP because NLI may well have a usage to offer.
P31_NO_WORD = {'upland', 'plateau', 'massif', 'non-geologically related mountain range'}

# Administrative divisions belong to Part 2 (tiers), not Part 1 (extended features):
# the Roman heading names a tier the Hebrew drops, which is the Pardubice pattern.
# A bare "region" is NOT included — that is Cilicia or Siberia, a Part 1 case.
ADMIN_RE = re.compile(
    r'\b(?:'
    r'(?:province|county|district|state|region|department|governorate|territory|'
    r'prefecture|oblast|krai|voivodeship|okres|kraj|raion|powiat|gubernia|comarca|'
    r'municipality|federative unit|federal subject|autonomous \w+)\s+of\b'
    r'|federative unit|federal subject|administrative region|autonomous (?:county|'
    r'prefecture|oblast|okrug)|Scottish region|governorate|voivodeship|okres|kraj|'
    r'raion|powiat|gubernia|comarca'
    r')', re.I)

# Roman tier word -> Hebrew, extending TIER_HE with the English forms that appear in
# these headings. Same working assumption as tier-vocabulary.md 3a.
ADMIN_TIER_HE = {
    'county': 'נפה', 'district': 'נפה', 'province': 'מחוז', 'state': 'מדינה',
    'region': 'מחוז', 'department': 'מחוז', 'governorate': 'מחוז',
    'territory': 'טריטוריה', 'prefecture': 'מחוז', 'oblast': 'מחוז',
    'krai': 'מחוז', 'voivodeship': 'מחוז', 'okres': 'נפה', 'kraj': 'מחוז',
    'raion': 'נפה', 'powiat': 'נפה', 'gubernia': 'פלך', 'comarca': 'נפה',
    'municipality': 'עיר', 'fylke': 'מחוז', 'shi': 'עיר', 'landkreis': 'נפה',
    'stadtkreis': 'עיר-נפה', 'regierungsbezirk': 'מחוז ממשל', 'voblasts': 'מחוז',
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
rows_sugg, rows_have, rows_skip, rows_admin = [], [], [], []
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
    if ADMIN_RE.search(lab_txt) and r.get('bucket') != 'homonym':
        rows_admin.append(base | {
            'why': 'Wikidata calls this an administrative division (%s); the Roman heading '
                   'names the tier and the Hebrew does not — same pattern as Part 2' % lab_txt})
        continue
    if any(l in P31_SKIP for l in labs):
        rows_skip.append(base | {'why_skipped':
                                 'a type word would be wrong for this kind of entity (%s)' % lab_txt})
        continue
    if any(l in P31_NO_WORD for l in labs):
        rows_skip.append(base | {'why_skipped':
                                 'a type word would be right, but we have no Hebrew word we trust '
                                 'for this type (%s) — NLI may have an established usage' % lab_txt})
        continue
    hit = next((P31_HE[l] for l in labs if l in P31_HE), None)
    if not hit:
        rows_skip.append(base | {'why_skipped':
                                 'no Hebrew type word mapped for: %s' % (lab_txt or 'no P31')})
        continue
    heb = r.get('headingHeb') or ''
    b, rest = he_base(heb), heb[len(he_base(heb)):]
    country = (re.findall(r'\(([^:)]+)', heb) or [''])[0].strip()
    rows_sugg.append(base | {
        'proposed_he_type': hit,
        # NLI's own dominant practice: 214 of 234 Hebrew headings that name a
        # feature type use the prefix form (נהר הירדן, מפרץ אילת, איי גלפגוס).
        'proposed_heb_heading': '%s %s%s' % (hit, b, rest),
        'alt_form_parenthetical': '%s (%s)' % (b, hit) if not country else
                                  '%s (%s : %s)' % (b, country, hit),
        'alt_form_comma': '%s, %s%s' % (b, hit, rest),
        'form_note': 'prefix form proposed — it is NLI\'s dominant practice '
                     '(214 of 234 headings); the alternatives are shown for comparison',
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


# ---- Part 2b: proposed tier heading for the administrative divisions -------
for r in rows_admin:
    rom, heb = r.get('rom_heading') or '', r.get('heb_heading') or ''
    word = ''
    m = re.search(r':\s*([^:()]+?)\s*\)\s*$', rom)          # "X (Country : Tier)"
    if m:
        word = m.group(1).strip().lower()
    if not word:                                              # "Møre og Romsdal fylke (Norway)"
        for tok in reversed(re.findall(r"[A-Za-zÀ-ſĀ-ſ'ʹ]+", re.split(r'\s*\(', rom)[0])):
            if tok.rstrip("'ʹ").lower() in ADMIN_TIER_HE:
                word = tok.lower(); break
    if not word:                                              # else take it from Wikidata
        m2 = re.search(r'\b(\w+)\s+of\b', r.get('wikidata_says') or '')
        if m2:
            word = m2.group(1).lower()
    tier_he = ADMIN_TIER_HE.get(word.rstrip("'ʹ"), '')
    country = (re.findall(r'\(([^:)]+)', heb) or [''])[0].strip()
    base_he = re.sub(r'^(מחוז|נפה|פלך|מדינה)\s+', '', heb.split(' (')[0])
    r['roman_tier_word'] = word
    r['roman_tier_meaning'] = ('the Roman heading names the administrative tier; '
                               'the Hebrew does not' if word else 'no tier word found')
    r['proposed_he_tier'] = tier_he
    r['proposed_heb_heading'] = ('%s (%s : %s)' % (base_he, country, tier_he)
                                 if tier_he and country else '')
    r['vocabulary_status'] = 'WORKING ASSUMPTION — tier-vocabulary.md 3a, not yet settled'


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
              ('tier-suggested.csv', rows_tier),
              ('tier-from-coordinate-pile.csv', rows_admin)]:
    p, k = write(n, rs)
    print('%-34s %4d rows' % (n, k))

json.dump({'sugg': rows_sugg, 'have': rows_have, 'skip': rows_skip, 'tier': rows_tier,
           'admin': rows_admin},
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

n_admin = len(rows_admin)
n_admin_ok = sum(1 for r in rows_admin if r['proposed_heb_heading'])
n_admin_no = n_admin - n_admin_ok
n_tier_total = len(rows_tier) + n_admin
admin_tbl = md_table([r for r in rows_admin if r['proposed_heb_heading']],
                     [('nli_id', 'מזהה NLI'), ('heb_heading', 'עברית כיום'),
                      ('rom_heading', 'לטינית'), ('wikidata_says', 'סוג בוויקינתונים'),
                      ('proposed_heb_heading', 'עברית מוצעת')], limit=14)

have_tbl = md_table([{'w': w, 'n': n} for w, n in
                     collections.Counter(r['existing_he_type'] for r in rows_have
                                         if r['existing_he_type']).most_common(15)],
                    [('w', 'מילת סוג'), ('n', 'רשומות')])
loc_tbl = md_table([{'i': k, 'h': LOCTYPE[k], 'm': LOCTYPE_NOTE[k]} for k in sorted(LOCTYPE)],
                   [('i', 'LocationTypeId'), ('h', 'עברית'), ('m', 'משמעות')])
sugg_tbl = md_table(rows_sugg, [('nli_id', 'מזהה NLI'), ('heb_heading', 'עברית כיום'),
                                ('rom_heading', 'לטינית'), ('wikidata_says', 'סוג בוויקינתונים'),
                                ('proposed_heb_heading', 'עברית מוצעת')], limit=12)
tier_tbl = md_table([r for r in rows_tier if r['proposed_he_tier']],
                    [('nli_id', 'מזהה NLI'), ('heb_heading', 'עברית כיום'),
                     ('rom_heading', 'לטינית'), ('roman_tier_word', 'דרגה בלטינית'),
                     ('proposed_heb_heading', 'עברית מוצעת')])
tier_map_tbl = md_table([{'r': k, 'h': v} for k, v in
                         sorted(TIER_HE.items(), key=lambda x: x[1])],
                        [('r', 'מילת דרגה לטינית'), ('h', 'עברית מוצעת')])

sugg_by_type = collections.Counter(r['proposed_he_type'] for r in rows_sugg)
sugg_tbl_types = md_table([{'t': t, 'n': n} for t, n in sugg_by_type.most_common()],
                          [('t', 'מילה מוצעת'), ('n', 'רשומות')])
have_by_type = collections.Counter(r['existing_he_type'] for r in rows_have if r['existing_he_type'])
tier_ok = [r for r in rows_tier if r['proposed_he_tier']]

doc = f"""# כותרות עבריות שאינן אומרות מאיזה סוג המקום

טיוטה לדיון — הופקה {os.environ.get('REPORT_DATE', '2026-08-28')} מתוך דוחות העדכון
השבועיים של הספרייה. **טרם נשלחה.**

שתי בקשות מאותו סוג: הכותרת הלטינית (`151`) ברשומות NLI אומרת מאיזה סוג הישות —
נהר, מחוז, אזור — והכותרת העברית לרוב אינה אומרת זאת. כימה צורכת את הכותרת העברית,
ולכן ההבחנה אובדת אצלנו, ושני מקומות שונים מתחרים על אותה מחרוזת עברית.

אין כאן בקשה לשנות קואורדינטות או למזג רשומות. שתי הבקשות נוגעות לכותרת בלבד.

## למה זה חשוב — לא רק לנו

**דיסאמביגואציה.** כשהכותרת העברית אינה אומרת מה סוג הישות, שתי רשומות שונות נושאות
מחרוזת זהה ואי אפשר להבחין ביניהן:

* `גנגס (צרפת)` — עיירה בדרום צרפת. בעברית היא בלתי ניתנת להבחנה מהנהר גנגס, ואצלנו
  הפער בין הנקודות הוא 8,104 ק"מ. `נהר גנגס` לעומת `גנגס (צרפת)` פותר זאת מיידית.
* `פרדוביצה (צ'כיה : מחוז)` — אותה כותרת עברית משמשת גם את המחוז וגם את הנפה שבתוכו,
  שני מקומות במרחק 38 ק"מ. הלטינית מבחינה (`Okres` מול `kraj`), העברית לא.
* `ליברץ (צ'כיה)` — העיר והמחוז נושאים כותרת עברית זהה; 8 ק"מ מפרידים ביניהם.
* `אישיגאקי (יפן)` — האי והעיר. הלטינית אומרת `Ishigaki-shi` מול `Ishigaki Island`.

**מידע.** מעבר לפתרון ההתנגשויות, כותרת שאומרת `נהר בוס` במקום `בוס (צרפת)` היא פשוט
אינפורמטיבית יותר לקורא, לקטלוגר ולכל מי שצורך את קובץ הרשויות.

---

## חלק 1 — ישויות מורחבות (נהר, אזור, רכס, קבוצת איים …)

### התופעה

`Beauce (France)` הוא נהר. הכותרת העברית שלו היא `בוס (צרפת)` — שם ומדינה, בלי שום
רמז לכך שמדובר בנהר.

לנו זה משנה באופן מעשי: לישות מורחבת אין נקודה אחת נכונה, ולכן הקואורדינטה של NLI
ושלנו יכולות להתרחק זו מזו בעשרות קילומטרים בעוד שתיהן נכונות. כשהכותרת העברית אינה
אומרת שמדובר בנהר, הצינור שלנו מתייחס להפרש כאל שגיאה שיש ליישב.

### הספרייה כבר עושה זאת — לא בעקביות

זה לב הבקשה. מתוך **{n_all}** ישויות מורחבות בדוחות הנוכחיים:

* **{len(rows_have)}** כבר נושאות מילת סוג בעברית — `הים הלבן`, `מיצרי מגלן`, `נהר הירדן`
* **{len(rows_sugg)}** אינן, ולדעתנו כדאי שיישאו
* **{len(rows_skip)}** איננו מבקשים לגביהן דבר (ראו להלן)

הנוהג קיים ומבוסס. הבקשה היא להרחיב אותו לרשומות שנפלו בין הכיסאות, לא לאמץ משהו חדש.

מילות הסוג שכבר בשימוש, לפי שכיחות:

{have_tbl}

### צורת הכותרת המוצעת

בדקנו את הנוהג בפועל על פני **2,255 מחרוזות עבריות שונות** מתוך קובץ הרשויות. התוצאה
חד־משמעית: **צורת הקידומת היא הנוהג המקובל** — `נהר הירדן`, `מפרץ אילת`, `איי גלפגוס`.

| צורה | מופעים |
|---|---|
| `נהר X` — קידומת | 214 |
| `X, נהר` — פסיק | 5 |
| `X (נהר)` — סוגריים | 4 |
| `X (מדינה : נהר)` | 1 |

לכן ההצעות בקובץ נוקטות בצורת הקידומת. **הצורות האחרות הן חלופה לגיטימית** — הן
מופיעות בעמודות `alt_form_parenthetical` ו־`alt_form_comma` בקובץ — ואם הספרייה מעדיפה
צורה אחרת, נשמח לדעת ונתאים את ההצעה.

⚠️ שימו לב: בקטגוריית הדרגות המנהליות (חלק 2) הנוהג **הפוך** — שם צורת הסוגריים
`X (מדינה : דרגה)` שכיחה יותר. פירוט שם.

### מה נציע

{sugg_tbl_types}

הרשימה המלאה: **`qualifiers-suggested.csv`**. כל שורה נושאת את מזהה NLI, שתי הכותרות,
ישות הוויקינתונים **והסוג שלה במילים**, המרחק בין הנקודה של NLI לשלנו, והכותרת המוצעת.

שורות ראשונות להתמצאות:

{sugg_tbl}

### מה איננו מבקשים

**`qualifiers-not-suggested.csv`** ({len(rows_skip)} רשומות) — נשמר בדוח כדי שההחרגות
יהיו גלויות ולא בלתי־נראות:

* סוגים שבהם מילת סוג תהיה שגויה — `אירופה`, `אוקיאניה`: אין מכנים יבשת
* סוגים שבהם מילת סוג נכונה אך אין בידינו מילה עברית שאנו סומכים עליה — *upland*,
  *plateau*, *massif*. `מאסיף סנטרל (צרפת)` נמצא כאן. **אם לספרייה יש נוהג מקובל
  לסוגים אלה נאמץ אותו** — עדיף לשאול מלנחש
* רשומות שסוג הוויקינתונים שלהן מעורפל מכדי לפעול לפיו (`geographical feature`)
* רשומות בלי סוג ויקינתונים שמיש

### מגבלות, בגילוי לב

1. **ההצעות הופקו אוטומטית מ־`P31` בוויקינתונים וזקוקות לעין של קטלוגר.** בבדיקה,
   כאחת מכל שש היתה שגויה לפני הסינון. יש להתייחס לכל שורה כהצעה, לא כממצא. במקום
   שבו לא יכולנו להציע מילה בביטחון, הוחרגה הרשומה ולא נוחשה.
2. **בחירת המילים היא שלנו ואינה סמכותית.** ב־`אזור`, `נהר` ו־`חוף` אנו בטוחים;
   בכל השאר נעדיף את הנוהג של הספרייה.
3. **זהו מדגם ולא קובץ הרשויות כולו.** אלה רק רשומות שהופיעו בדוחות שבועיים בין
   2024-06 ל־2026-08 — כלומר רשומות שהשתנו. סביר שאותו פער קיים גם ברשומות שלא השתנו.

### אם הספרייה תעדיף שלא

נרשום את סוג הישות אצלנו, בשדה `LocationTypeId` של כימה. העמודה
`kima_fallback_location_type_id` נושאת את הערך שנציב, ו־`kima_fallback_meaning` מסבירה
אותו במילים. הערכים הקיימים בכימה:

{loc_tbl}

זו תוצאה פחות טובה — ההבחנה תחיה רק בכימה ותישאר בלתי נראית לכל שאר צרכני קובץ
הרשויות — אך היא בת ביצוע.

**ממצא בצד שלנו, נרשם כאן כדי שלא יאבד.** בדיקת הסוג השמור בכימה לכל {n_all} הישויות
המורחבות מראה שהשדה שגוי או ריק ברובו:

{loctable}

רק {n_region} מתוך {n_all} מסומנות כאזור. **{n_point} ישויות מורחבות — נהרות, רכסים,
ימים — מסומנות בכימה כיישובים**, ול־{n_none} אין סוג כלל. כלומר החלופה שלעיל אינה
עניין של כתיבת ערך שכבר בידינו: יש לתקן קודם את הקיים. זו בעיה של כימה, לא של
הספרייה, והיא מטופלת בנפרד.

---

## חלק 2 — דרגות מנהליות

### התופעה

`Pardubice (Czech Republic : Okres)` היא נפה. `Pardubický kraj` הוא המחוז שמכיל אותה.
שתיהן נושאות בעברית `פרדוביצה (צ'כיה : מחוז)`, משום שהעברית מכווצת כ־45 מילות דרגה
לטיניות שונות ל־`מחוז` / `פרובינציה`, ו־231 כותרות מקום אינן נושאות מילת דרגה כלל.

הכותרת הלטינית ייחודית. העברית אינה. במקום שבו אילוץ הייחודיות של הספרייה חל על
הכותרת הלטינית, אותן שתי רשומות מתנגשות בעברית.

### מה זה עולה לנו

כימה כבר ביצעה את ההבחנה ידנית ב־**{len(rows_tier)}** מהמקרים, ויצרה כותרות עבריות
עם מבחין דרגה. מכיוון שהעברית השטוחה של NLI נשלחת מחדש בכל עדכון, הצינור שלנו קורא
אותה ככותרת מתחרה ומדווח על התנגשות.

ארבעה מקרים נוספים דווחו לנו כ*"אין מקום בכימה שמחזיק בכותרת"* בעוד שהמקום קיים —
תחת צורה עם מבחין דרגה שהחיפוש האוטומטי שלנו לא ידע להתאים: חרקיב, צ'רנוביץ,
דאליין, בוהמיה.

### הבקשה

להחיל על הכותרת העברית (`151`) את אותו אילוץ ייחודיות החל על הלטינית, באמצעות אוצר
מילים קבוע לדרגות ובצורת המבחין `X (מדינה : דרגה)`.

**כאן הנוהג הפוך מחלק 1.** בבדיקת אותן 2,255 מחרוזות:

| צורה | מופעים |
|---|---|
| `X (מדינה : דרגה)` | 44 |
| `מחוז X` — קידומת | 29 |
| `X (דרגה)` | 8 |

צורת הסוגריים מובילה, ולכן היא המוצעת. היא גם עדיפה לדעתנו מסיבה מעשית: הצורה
`מחוז X` נקראת כחלק מהשם עצמו וממיינת גרוע — כל המחוזות מתקבצים תחת האות מ'.

{tier_tbl}

הרשימה המלאה עם צד כימה: **`tier-suggested.csv`**.

### עוד {n_admin} מאותו סוג, מתוך דוחות הקואורדינטות

אלה לא הגיעו כהתנגשות כותרות — הם צפו משום שהקואורדינטה של NLI ושלנו נחלקו. אך
הבעיה זהה: ויקינתונים מגדירה כל אחד מהם כחלוקה מנהלית, הכותרת הלטינית נוקבת בדרגה,
והעברית לא.

{admin_tbl}

הרשימה המלאה: **`tier-from-coordinate-pile.csv`**. ל־{n_admin_ok} מתוך {n_admin} יש
כותרת מוצעת; ב־{n_admin_no} הנותרות לא ניתן היה לקרוא מילת דרגה מהכותרת הלטינית —
`Brazil, Northeast`, `Grampian (Scotland)`, ושתי חלוקות אוטונומיות סיניות שלדרגתן
אין צורה עברית מקובלת.

רשומות שסווגו אצלנו כהומונים הוחרגו כאן גם כשוויקינתונים מגדירה אותן כחלוקה מנהלית,
משום שבהן ייתכן שישות הוויקינתונים אינה של הרשומה כלל: `אזור הצפון (גאנה)` נושאת
מזהה ויקינתונים של האזור הצפוני **של אוגנדה**, במרחק 3,710 ק"מ. זו שגיאת קישור אצלנו,
לא בעיית דרגה.

בספירת שני המקורות, שאלת הדרגות מכסה **{n_tier_total} רשומות** והיא הגדולה מבין שתי
הבקשות במסמך זה.

### אוצר המילים אינו סופי

⚠️ **מילות הדרגה העבריות שלעיל הן הנחת עבודה**, מתוך `tier-vocabulary.md` §3a:
`מחוז` / `נפה` / `עיר-נפה` / `פלך` / `מחוז ממשל`. טרם סגרנו אותו, ונעדיף לסכם אותו
עם הספרייה מאשר לכפות אותו. המיפוי ששימש להפקת הטיוטה:

{tier_map_tbl}

במקום שבו אותה מילה עברית משמשת כמה דרגות לטיניות — זהו כיווץ מכוון, לא פליטה — אך
זו בדיוק ההחלטה שכדאי לקבל יחד.

---

## קבצים

| קובץ | שורות | מה זה |
|---|---|---|
| `qualifiers-suggested.csv` | {len(rows_sugg)} | ישויות מורחבות שנציע להוסיף להן מילת סוג |
| `qualifiers-already-present.csv` | {len(rows_have)} | ישויות מורחבות שהעברית שלהן כבר נוקבת בסוג — התקדים |
| `qualifiers-not-suggested.csv` | {len(rows_skip)} | הוחרגו במכוון, עם הנימוק לכל שורה |
| `tier-suggested.csv` | {len(rows_tier)} | התנגשויות דרגה מנהלית עם כותרת עברית מוצעת |
| `tier-from-coordinate-pile.csv` | {len(rows_admin)} | חלוקות מנהליות שצפו מדוחות הקואורדינטות — אותה בעיית דרגה |

בכל קובץ, כל עמודה הנושאת מזהה מלווה בעמודה המסבירה במילים מה הוא — כדי ששורה לא
תדרוש פענוח מזהה כדי להיקרא.
"""

open(os.path.join(OUT, 'nli-heading-qualifiers.md'), 'w', encoding='utf-8').write(doc)
print('nli-heading-qualifiers.md      %d bytes' % len(doc))
