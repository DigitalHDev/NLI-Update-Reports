#!/usr/bin/env python3
"""Turn live-vs-live Hebrew collisions into a disambiguation worksheet.

NLI enforces uniqueness on the primary *Roman* heading; Kima's duplication
check runs on the *Hebrew* heading. So two perfectly valid NLI authorities can
collide in Kima whenever their Hebrew forms coincide. Kima's goal is to mirror
NLI ids exactly, so the fix is never to merge — it is either

  * disambiguate: give the Hebrew the distinction the Roman already carries
    (usually an administrative tier the Hebrew flattens to 'מחוז'), or
  * report to NLI: the two Roman headings denote the same place, so the
    duplicate is on NLI's side.

Reads app/dup-analysis.json (produced by analyze_dups.py).
Writes app/disambiguation.tsv
"""
import json
import os
import re

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Roman qualifier -> Hebrew tier. NLI spells the administrative level out in the
# Roman heading, while the Hebrew flattens nearly all of them to 'מחוז' — which
# is what makes the two records collide. Suggestions only; wording is a
# curatorial call.
TIER_HE = {
    'voivodeship': 'מחוז', 'powiat': 'נפה', 'okres': 'נפה', 'kraj': 'מחוז',
    'gubernia': 'פלך', 'guberni': 'פלך', 'oblast': 'אובלסט', 'oblasty': 'אובלסט',
    'voblasts': 'אובלסט', 'raion': 'נפה', 'rai': 'נפה',
    'landkreis': 'נפה', 'stadtkreis': 'עיר', 'bezirk': 'מחוז',
    'regierungsbezirk': 'מחוז ממשל', 'sub-district': 'תת-מחוז',
    'okrug': 'אוקרוג', 'shi': 'עיר', 'island': 'אי', 'bashkia': 'עירייה',
    'province': 'פרובינציה', 'state': 'מדינה', 'region': 'אזור',
    'colony': 'מושבה', 'federal': 'מחוז פדרלי',
}


def qualifier(rom):
    """The part of a Roman heading that states the administrative tier."""
    m = re.search(r'\(([^)]*)\)\s*$', rom or '')
    if not m:
        return ''
    inner = m.group(1)
    return inner.split(':', 1)[1].strip() if ':' in inner else inner.strip()


def tier_of(rom):
    """Best-effort Hebrew tier word for a Roman heading."""
    q = qualifier(rom).lower()
    for key, he in TIER_HE.items():
        if key in q:
            return he
    # some headings carry the tier in the name itself (Pardubický kraj,
    # Hrodzenskai︠a︡ voblastsʹ). Plain substring, not \b — romanisation appends
    # modifier letters (voblastsʹ) that defeat a word boundary.
    low = (rom or '').lower()
    for key, he in sorted(TIER_HE.items(), key=lambda kv: -len(kv[0])):
        if key in low:
            return he
    return ''


def base_name(rom):
    return re.sub(r'\s*\([^)]*\)\s*$', '', rom or '').strip()


def classify(a):
    """What should happen to this collision?"""
    o = next(p for p in a['kimaPlaces'] if p['how'] == 'owns-heading')
    inc, oth = a['incoming'], a['kimaMarc'].get(o['kimaMazal'], {})
    r1 = inc['primary'].get('lat', '')
    r2 = (oth.get('primary') or {}).get('lat', '')
    t1, t2 = tier_of(r1), tier_of(r2)
    dist = a['distanceKm']

    # same base name + different tier -> one place recorded at two admin levels
    if base_name(r1).lower() == base_name(r2).lower() and qualifier(r1) != qualifier(r2):
        return ('disambiguate-tier',
                'אותו שם, רמות מנהל שונות: %s / %s' % (qualifier(r1) or '—',
                                                        qualifier(r2) or '—'),
                t1, t2)
    # different Roman base names but co-located -> likely one place under two
    # naming conventions (translation vs transliteration, or a renaming)
    if dist is not None and dist <= 2:
        return ('report-to-nli',
                'שמות לועזיים שונים באותו מיקום — כפילות אפשרית ב־NLI: %s / %s'
                % (r1, r2), t1, t2)
    # different Roman names, far apart -> genuinely two places whose Hebrew
    # transliterations happen to coincide
    return ('disambiguate-distinct',
            'שני מקומות שונים עם תעתיק עברי זהה: %s / %s' % (r1, r2), t1, t2)


def suggest(heb, tier, rom):
    """Propose a disambiguated Hebrew heading."""
    if not heb:
        return ''
    core = re.sub(r'\s*\([^)]*\)\s*$', '', heb).strip()
    inner = re.search(r'\(([^)]*)\)\s*$', heb)
    country = inner.group(1).split(':')[0].strip() if inner else ''
    if tier and country:
        return '%s (%s : %s)' % (core, country, tier)
    if tier:
        return '%s (%s)' % (core, tier)
    # no tier available — fall back to the distinguishing Roman form
    return '%s (%s)' % (core, base_name(rom)) if rom else heb


COLUMNS = ['action', 'hebrewCollision', 'incomingId', 'incomingRoman',
           'incomingHebrew', 'suggestedIncomingHebrew', 'kimaMazal',
           'kimaRoman', 'kimaHebrew', 'suggestedKimaHebrew', 'kimaPlaceId',
           'distanceKm', 'note']


def main():
    d = json.load(open(os.path.join(APP_DIR, 'dup-analysis.json')))
    rows = []
    for a in [x for x in d if x['verdict'] == 'both-live']:
        o = next(p for p in a['kimaPlaces'] if p['how'] == 'owns-heading')
        oth = a['kimaMarc'].get(o['kimaMazal'], {})
        inc = a['incoming']
        r1 = inc['primary'].get('lat', '')
        r2 = (oth.get('primary') or {}).get('lat', '')
        h1 = inc['primary'].get('heb', '')
        h2 = (oth.get('primary') or {}).get('heb', '')
        action, note, t1, t2 = classify(a)
        rows.append({
            'action': action, 'hebrewCollision': a['heading'] or '',
            'incomingId': a['recordId'], 'incomingRoman': r1, 'incomingHebrew': h1,
            'suggestedIncomingHebrew': suggest(h1, t1, r1)
                if action != 'report-to-nli' else '',
            'kimaMazal': o['kimaMazal'], 'kimaRoman': r2, 'kimaHebrew': h2,
            'suggestedKimaHebrew': suggest(h2, t2, r2)
                if action != 'report-to-nli' else '',
            'kimaPlaceId': o['kimaId'],
            'distanceKm': '' if a['distanceKm'] is None else a['distanceKm'],
            'note': note,
        })

    rows.sort(key=lambda r: (r['action'], r['hebrewCollision']))
    out = os.path.join(APP_DIR, 'disambiguation.tsv')
    with open(out, 'w') as fh:
        fh.write('\t'.join(COLUMNS) + '\n')
        for r in rows:
            fh.write('\t'.join(str(r[c]).replace('\t', ' ') for c in COLUMNS) + '\n')

    tally = {}
    for r in rows:
        tally[r['action']] = tally.get(r['action'], 0) + 1
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print('%-22s %d' % (k, v))
    print('\nwrote app/disambiguation.tsv (%d rows)' % len(rows))


if __name__ == '__main__':
    main()
