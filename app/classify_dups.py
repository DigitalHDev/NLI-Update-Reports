#!/usr/bin/env python3
"""Classify the duplicate-heading pile (dup-places-diff / dup-places / unresolved
dup-variants from app/dup-analysis.json) with Wikidata as arbiter, and recommend
an action per case.  Writes app/dup-classification.{tsv,json}.

Pair = incoming NLI record A (the one the feed announced) vs the record B that the
Kima place owning the same Hebrew heading is bound to.

Buckets
  same-entity          A and B are one Wikidata entity → duplicate on NLI's side; report, keep Kima on one
  tier-pair            same base name, different administrative tier (town / powiat / voivodeship…)
                       → disambiguate the Hebrew with a tier word
  distinct-homonym     different places, different Roman base names, identical Hebrew
                       → disambiguate the Hebrew (spelling or region)
  nli-heading-error    A's Hebrew heading names a different place than its Roman/Wikidata
  kima-bound-to-wrong-twin   Kima's identity (WD / Hebrew qualifier) matches A, but its MAZAL_ID is B
  kima-id-suppressed   B no longer served by NLI → repoint Kima to A
  heading-drift        Kima already holds A's id; only the Hebrew heading spelling differs → no dup
  unresolved           no Kima owner found for the heading
"""
import csv, json, os, re, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classify_moves as cm                                        # noqa: E402
from classify_moves import wd_fetch, wd_search_by_statement, load_cache, norm  # noqa: E402
from server import haversine                                        # noqa: E402
from disambiguate import qualifier, tier_of, TIER_HE                # noqa: E402

APP = os.path.dirname(os.path.abspath(__file__))

TIER_WORDS = re.compile(r'(voivodeship|powiat|okres|kraj|guberni|oblast|voblast|rai.?o.?n|raion|landkreis|'
                        r'stadtkreis|bezirk|regierungsbezirk|sub-district|okrug|-shi|bashkia|province|'
                        r'district|county|region|municipality|island|federal)', re.I)
HEB_TIER = re.compile(r'(מחוז|נפה|פלך|אובלסט|עיריה|עירייה|אי\b|אזור|תת-מחוז|פרובינציה)')


def base_rom(rom):
    """Roman heading without qualifier and without tier words."""
    s = re.sub(r'\(.*?\)', ' ', rom or '')
    s = TIER_WORDS.sub(' ', s)
    return norm(s)


def same_base(a, b):
    import difflib
    a, b = base_rom(a), base_rom(b)
    if not a or not b:
        return False
    ta, tb = set(a.split()), set(b.split())
    if ta & tb:
        return True
    fa, fb = a.split()[0], b.split()[0]
    if min(len(fa), len(fb)) >= 4 and (fa.startswith(fb[:4]) or fb.startswith(fa[:4])):
        return True          # Minskaia / Minski, Pardubice / Pardubicky
    return difflib.SequenceMatcher(None, a.replace(' ', ''), b.replace(' ', '')).ratio() >= 0.8


def ent(wd, q):
    e = wd.get(q) if q else None
    if isinstance(e, dict) and e.get('redirect'):
        e = wd.get(e['redirect']) or e
    return e if isinstance(e, dict) and not e.get('missing') else None


def p31_text(wd, e):
    if not e:
        return ''
    return ' / '.join((wd.get(p) or {}).get('label_en') or p for p in e.get('p31', []))


def is_admin(txt):
    return bool(re.search(r'(voivodeship|powiat|district|county|oblast|raion|region|province|kraj|okres|'
                          r'administrative|municipality|governorate|okrug|landkreis|bezirk|territorial|'
                          r'subdivision|gubernia|governorate)', txt, re.I))


def is_settlement(txt):
    return bool(re.search(r'(city|town|village|human settlement|urban|neighbou?rhood|quarter|borough|'
                          r'big city|capital)', txt, re.I))


def classify(case, wd):
    inc = case['incoming']
    owners = [p for p in case['kimaPlaces'] if p['how'] == 'owns-heading']
    holders = [p for p in case['kimaPlaces'] if p['how'] == 'holds-incoming-id']
    a_id = inc['recordId']
    qa = inc['ids'].get('wikidata') or wd.get('search:P8189=%s' % a_id)
    ea = ent(wd, qa)
    out = {'recordId': a_id, 'category': case['category'], 'verdict': case['verdict'],
           'heading': case['heading'], 'dupKey': case['dupKey'],
           'aRoman': inc['primary'].get('lat'), 'aHeb': inc['primary'].get('heb'),
           'aWd': qa, 'aWdLabel': (ea or {}).get('label_en'), 'aWdHe': (ea or {}).get('label_he'),
           'aP31': p31_text(wd, ea), 'aCoords': inc.get('coords'),
           'bId': None, 'bRoman': None, 'bHeb': None, 'bWd': None, 'bWdLabel': None, 'bP31': None,
           'bCoords': None, 'bStatus': None,
           'kimaId': None, 'kimaHeb': None, 'kimaRom': None, 'kimaWd': None,
           'distanceKm': case.get('distanceKm'), 'earlierHeadings': ' | '.join(case.get('earlierHeadings') or [])}

    # -- heading-drift / unresolved ------------------------------------------
    if case['verdict'] == 'kima-unresolved':
        if holders:
            h = holders[0]
            out.update(kimaId=h['kimaId'], kimaHeb=h['heb'], kimaRom=h['rom'], kimaWd=h['wd'])
            return out | {'bucket': 'heading-drift', 'action': 'update-kima-heading', 'confidence': 'high',
                          'note': 'Kima %s already holds this id under "%s"; NLI now says "%s" — '
                                  'no second record involved' % (h['kimaId'], h['heb'], inc['primary'].get('heb'))}
        return out | {'bucket': 'unresolved', 'action': 'research', 'confidence': 'low',
                      'note': 'no Kima place owns the heading or holds the id'}

    if not owners:
        return out | {'bucket': 'unresolved', 'action': 'research', 'confidence': 'low', 'note': 'no owner'}
    k = owners[0]
    b_id = k['kimaMazal']
    both_in_kima = any(h['kimaMazal'] == a_id for h in holders)
    out['bothInKima'] = both_in_kima
    out['kimaHolderOfA'] = '; '.join('%s "%s"' % (h['kimaId'], h['heb']) for h in holders if h['kimaMazal'] == a_id) or None
    bm = (case.get('kimaMarc') or {}).get(b_id) or {}
    qb = (bm.get('ids') or {}).get('wikidata') or wd.get('search:P8189=%s' % b_id)
    eb = ent(wd, qb)
    qk = (k.get('wd') or '').strip() or None
    out.update(bId=b_id, bRoman=(bm.get('primary') or {}).get('lat') or k['rom'],
               bHeb=(bm.get('primary') or {}).get('heb') or k['heb'],
               bWd=qb, bWdLabel=(eb or {}).get('label_en'), bP31=p31_text(wd, eb),
               bCoords=bm.get('coords'), bStatus=bm.get('status') or case['verdict'],
               kimaId=k['kimaId'], kimaHeb=k['heb'], kimaRom=k['rom'], kimaWd=qk)
    a_rom, b_rom = out['aRoman'] or '', out['bRoman'] or ''
    dist = out['distanceKm']
    try:
        dist = float(dist) if dist not in (None, '') else None
    except ValueError:
        dist = None

    # -- suppressed: mechanical repoint ---------------------------------------
    if case['verdict'] == 'kima-id-suppressed':
        return out | {'bucket': 'kima-id-suppressed', 'action': 'repoint-kima-to-incoming', 'confidence': 'high',
                      'note': 'Kima %s -> %s is suppressed in NLI; successor is %s "%s"%s'
                              % (k['kimaId'], b_id, a_id, a_rom,
                                 ('; earlier heading(s): ' + out['earlierHeadings']) if out['earlierHeadings'] else '')}

    # -- Kima bound to the wrong twin -----------------------------------------
    if qk and qa and qk == qa and qb and qb != qa:
        return out | {'bucket': 'kima-bound-to-wrong-twin', 'action': 'swap-kima-binding', 'confidence': 'high',
                      'note': 'Kima %s carries WD %s = A "%s" but MAZAL_ID points to B "%s" (WD %s)'
                              % (k['kimaId'], qk, a_rom, b_rom, qb)}

    tier_a, tier_b = tier_of(a_rom), tier_of(b_rom)

    # -- both already in Kima with distinct headings: nothing to bind ---------
    if both_in_kima:
        holder = [h for h in holders if h['kimaMazal'] == a_id][0]
        letters = lambda x: re.sub(r'[^א-ת]', '', cm.nfc(x))
        import difflib
        if letters(holder['heb']) == letters(k['heb']) or \
                difflib.SequenceMatcher(None, letters(holder['heb']), letters(k['heb'])).ratio() >= 0.92:
            out['suggestA'] = holder['heb']; out['suggestB'] = k['heb']
            return out | {'bucket': 'pseudo-disambiguated-in-kima', 'action': 'disambiguate-hebrew-tier',
                          'confidence': 'high',
                          'note': 'Kima holds both (A=%s "%s", B=%s "%s") but the headings differ only in '
                                  'spelling/punctuation — still ambiguous' % (holder['kimaId'], holder['heb'], k['kimaId'], k['heb'])}
        if re.sub(r'\s+', '', cm.nfc(holder['heb'])) != re.sub(r'\s+', '', cm.nfc(k['heb'])):
            out['suggestA'] = holder['heb']; out['suggestB'] = k['heb']
            return out | {'bucket': 'already-disambiguated-in-kima', 'action': 'keep-kima-headings+variant',
                          'confidence': 'high',
                          'note': 'Kima already holds A as %s "%s" and B as %s "%s"; NLI\'s flat Hebrew "%s" '
                                  'only needs to stay a variant of A' % (holder['kimaId'], holder['heb'], k['kimaId'], k['heb'], out['aHeb'])}

    # -- same entity -----------------------------------------------------------
    if qa and qb and qa == qb:
        return out | {'bucket': 'same-entity', 'action': 'report-nli-duplicate', 'confidence': 'high',
                      'note': 'both records carry Wikidata %s "%s": "%s" / "%s"' % (qa, out['aWdLabel'], a_rom, b_rom)}
    if ea and eb is None and qb is None and dist is not None and dist <= 2 and same_base(a_rom, b_rom):
        return out | {'bucket': 'same-entity', 'action': 'report-nli-duplicate', 'confidence': 'medium',
                      'note': 'same place, %.1f km apart, no WD on B: "%s" / "%s"' % (dist, a_rom, b_rom)}

    # -- Hebrew heading names another place ------------------------------------
    he_a = (ea or {}).get('label_he')
    if he_a and not cm.name_matches({'label_en': he_a, 'label_he': he_a}, {'primary': {'heb': out['aHeb']}, 'variants': []}, None) \
            and not same_base(a_rom, b_rom):
        return out | {'bucket': 'nli-heading-error', 'action': 'report-nli', 'confidence': 'medium',
                      'note': 'A is "%s" (WD he: %s) but its Hebrew heading is "%s" = B "%s"'
                              % (a_rom, he_a, out['aHeb'], b_rom)}

    # -- tier pair --------------------------------------------------------------
    ta, tb = p31_text(wd, ea), p31_text(wd, eb)
    if same_base(a_rom, b_rom):
        tier_signal = (tier_a or tier_b) and tier_a != tier_b
        p31_signal = ta and tb and (is_admin(ta) != is_admin(tb) or is_settlement(ta) != is_settlement(tb))
        if tier_signal or p31_signal:
            sa = tier_a or ('עיר' if is_settlement(ta) else 'מחוז')
            sb = tier_b or ('עיר' if is_settlement(tb) else 'מחוז')
            return out | {'bucket': 'tier-pair', 'action': 'disambiguate-hebrew-tier', 'confidence': 'high' if (ea and eb) else 'medium',
                          'suggestA': '%s : %s' % (out['aHeb'].split(' (')[0], sa),
                          'suggestB': '%s : %s' % (out['bHeb'].split(' (')[0], sb),
                          'note': 'A "%s" [%s] vs B "%s" [%s]' % (a_rom, ta or tier_a, b_rom, tb or tier_b)}
        if dist is not None and dist <= 5:
            return out | {'bucket': 'same-entity', 'action': 'report-nli-duplicate', 'confidence': 'medium',
                          'note': 'same base name %.1f km apart, different WD (%s / %s): "%s" / "%s"' % (dist, qa, qb, a_rom, b_rom)}
        return out | {'bucket': 'distinct-homonym', 'action': 'disambiguate-hebrew-region', 'confidence': 'medium',
                      'note': 'same name, different places %s km apart: "%s" (%s) / "%s" (%s)'
                              % (dist, a_rom, out['aWdLabel'], b_rom, out['bWdLabel'])}

    # -- distinct places whose Hebrew coincides --------------------------------
    if ea and eb and ea.get('coord') and eb.get('coord') and haversine(ea['coord'], eb['coord']) <= 2:
        return out | {'bucket': 'same-entity', 'action': 'report-nli-duplicate', 'confidence': 'medium',
                      'note': 'different Roman names but WD entities co-located: %s "%s" / %s "%s"'
                              % (qa, out['aWdLabel'], qb, out['bWdLabel'])}
    return out | {'bucket': 'distinct-homonym', 'action': 'disambiguate-hebrew-spelling', 'confidence': 'high' if (ea and eb) else 'medium',
                  'note': 'different places with one Hebrew form: "%s" (%s %s) / "%s" (%s %s), %s km'
                          % (a_rom, qa, out['aWdLabel'], b_rom, qb, out['bWdLabel'], dist)}


def main():
    data = json.load(open(os.path.join(APP, 'dup-analysis.json')))
    cases = [c for c in data if c['verdict'] != 'same-id']
    wd = load_cache()
    qids = []
    for c in cases:
        inc = c['incoming']
        q = inc['ids'].get('wikidata')
        if not q:
            q = wd_search_by_statement('P8189', inc['recordId'], wd)
        qids.append(q)
        for p in c['kimaPlaces']:
            if (p.get('wd') or '').startswith('Q'):
                qids.append(p['wd'])
            bm = (c.get('kimaMarc') or {}).get(p['kimaMazal']) or {}
            qb = (bm.get('ids') or {}).get('wikidata')
            if not qb and p['how'] == 'owns-heading' and c['verdict'] != 'kima-unresolved':
                qb = wd_search_by_statement('P8189', p['kimaMazal'], wd)
            qids.append(qb)
    wd_fetch(qids, wd)
    wd_fetch([e['redirect'] for e in wd.values() if isinstance(e, dict) and e.get('redirect')], wd)
    wd_fetch([p for e in wd.values() if isinstance(e, dict) and not e.get('missing') for p in e.get('p31', [])], wd)

    rows = [classify(c, wd) for c in cases]
    cols = ['bucket', 'action', 'confidence', 'note', 'suggestA', 'suggestB', 'bothInKima', 'kimaHolderOfA', 'recordId', 'category', 'verdict',
            'heading', 'dupKey', 'aRoman', 'aHeb', 'aWd', 'aWdLabel', 'aWdHe', 'aP31', 'aCoords',
            'bId', 'bRoman', 'bHeb', 'bWd', 'bWdLabel', 'bP31', 'bCoords', 'bStatus',
            'kimaId', 'kimaHeb', 'kimaRom', 'kimaWd', 'distanceKm', 'earlierHeadings']
    json.dump(rows, open(os.path.join(APP, 'dup-classification.json'), 'w'), ensure_ascii=False, indent=1)
    with open(os.path.join(APP, 'dup-classification.tsv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter='\t', extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                        for k, v in r.items()})
    for (b, a, cf), n in collections.Counter((r['bucket'], r['action'], r['confidence']) for r in rows).most_common():
        print('%3d  %-26s %-28s %s' % (n, b, a, cf))
    print()
    for r in rows:
        if r['bucket'] not in ('heading-drift',):
            print('%-26s %-8s | %s | %s / %s | %s' % (r['bucket'], r['confidence'], r['heading'], r['aRoman'], r['bRoman'], r['note'][:110]))


if __name__ == '__main__':
    main()
