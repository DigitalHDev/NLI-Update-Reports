#!/usr/bin/env python3
"""Analyse reported duplications against live NLI authority records.

Context: Kima is built on an older copy of the NLI authority file. The weekly
feed reports updates but never deletions, so a "duplicate" can mean either

  * Kima still holds an NLI id that NLI has since deleted or merged away
    (stale pointer — the incoming record should simply take the heading), or
  * both ids are still live in NLI (a genuine duplicate needing a decision).

Only a live fetch can tell the two apart, so for every duplication case this
resolves the NLI id(s) Kima has stored, pulls their MARC from the NLI IIIF
endpoint, and reports the comparison.

  authority: https://iiif.nli.org.il/IIIFv21/marc/authority/<recordId>
  bib:       https://iiif.nli.org.il/IIIFv21/marc/bib/<recordId>

Usage:  python3 app/analyze_dups.py [--categories dup-places-diff,...] [--limit N]
Output: app/dup-analysis.tsv  +  app/dup-analysis.json
"""
import argparse
import importlib.util
import json
import os
import sys
import re
import time
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location('srv', os.path.join(APP_DIR, 'server.py'))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)
DATA = srv.DATA

MARC_CACHE = os.path.join(APP_DIR, '.cache', 'nli_marc')
IIIF = 'https://iiif.nli.org.il/IIIFv21/marc/%s/%s'
# the endpoint sits behind Cloudflare, which 403s a default urllib agent
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

DUP_CATEGORIES = ('dup-places', 'dup-places-diff', 'dup-places-same', 'dup-variants')


# ------------------------------------------------------------------ fetching

def classify(xml):
    """Read the record's state off the response body.

    The endpoint distinguishes two failure modes, and they mean different
    things — verified against control ids:

      'absent'     HTTP 200 + "Identifier does not exist in repository".
                   No such record; an unknown/never-used id looks like this.
      'suppressed' HTTP 500 + "String index out of range". The id IS known to
                   the repository but the record cannot be serialised — the
                   shape a deleted/suppressed authority takes. This is the
                   deletion the weekly feed never reports.
    """
    if '<record' in xml:
        return 'live'
    if 'does not exist in repository' in xml:
        return 'absent'
    if 'String index out of range' in xml:
        return 'suppressed'
    return 'error'


def fetch_marc(rid, kind='authority'):
    """Return (status, xml), cached on disk. See classify() for the states."""
    os.makedirs(MARC_CACHE, exist_ok=True)
    cache = os.path.join(MARC_CACHE, '%s_%s.json' % (kind, rid))
    if os.path.exists(cache):
        with open(cache) as fh:
            xml = json.load(fh)['xml']
        return classify(xml), xml            # re-derived, not trusted from cache

    req = urllib.request.Request(IIIF % (kind, rid), headers={
        'User-Agent': UA, 'Accept': 'application/xml,text/xml,*/*'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            xml = r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        xml = e.read().decode('utf-8', 'replace')
    except Exception as e:                              # network/timeout
        return 'error', str(e)

    status = classify(xml)
    if status != 'error':                    # don't cache transient failures
        with open(cache, 'w') as fh:
            json.dump({'status': status, 'xml': xml}, fh)
    time.sleep(0.25)                                    # be polite to NLI
    return status, xml


def heading_links(xml):
    """551 links carrying $w — MARC authority heading succession.

    $w/0 = 'a' -> the named heading is an EARLIER form this record replaced;
    'b' -> a later heading. An earlier heading means the record supersedes a
    different authority, which is how an entity change (region -> country)
    shows up. parse_marc() drops $w, so read it here.
    """
    out = []
    for m in re.finditer(r'<datafield[^>]*tag="551"[^>]*>(.*?)</datafield>',
                         xml, re.S):
        subs = dict(re.findall(r'code="(\w)">([^<]*)<', m.group(1)))
        w = (subs.get('w') or '')[:1]
        if w in ('a', 'b') and subs.get('a'):
            out.append({'rel': 'earlier' if w == 'a' else 'later',
                        'name': srv.nfc(subs['a'])})
    return out


def marc_summary(rid, kind='authority'):
    """Fetch + parse one NLI record into the fields we compare on."""
    status, xml = fetch_marc(rid, kind)
    out = {'recordId': rid, 'status': status, 'primary': {}, 'variants': [],
           'coords': None, 'seealso': [], 'ids': {}, 'notes': [],
           'headingLinks': []}
    if status != 'live':
        return out
    rec = srv.parse_marc(xml)
    out.update({'primary': rec['primary'], 'coords': rec['coords'],
                'variants': [v['name'] for v in rec['variants']],
                'seealso': rec['seealso'], 'ids': rec['ids'],
                'notes': rec['notes'], 'headingLinks': heading_links(xml)})
    return out


# ------------------------------------------------------------------ analysis

def kima_side(case):
    """Every Kima place implicated in this duplication, with its stored NLI id.

    Two ways in: the place that currently owns the colliding heading, and any
    place already carrying the incoming record's own NLI id.
    """
    rid = case['recordId']
    heading = srv.case_heading(case)
    places, seen = [], set()

    def add(place, how):
        if not place:
            return
        pid = str(place.get('Id') or '')
        if pid and pid in seen:
            return
        seen.add(pid)
        places.append({
            'how': how,
            'kimaId': pid,
            'kimaMazal': str(place.get('MAZAL_ID') or '').strip(),
            'heb': place.get('primary_heb_full'),
            'rom': place.get('primary_rom_full'),
            'arab': place.get('primary_arab_full'),
            'lat': place.get('lat'), 'lon': place.get('lon'),
            'wd': place.get('WD'), 'viaf': place.get('VIAF_ID'),
            'geonames': place.get('Geoname_ID'), 'naf': place.get('NAF_ID'),
            'variants': DATA.variants_by_place.get(pid, []),
        })

    if heading:
        add((DATA.kima_by_heading(heading) or {}).get('place'), 'owns-heading')
    row = DATA.dump_by_mazal.get(rid)
    if row:
        add(DATA.kima_place_by_id(row['id']), 'holds-incoming-id')
    return heading, places


def verdict(incoming, kima_places, kima_marcs):
    """Summarise what the live NLI state says about this duplication.

    Keyed on the place that *owns the colliding heading* — that is the actual
    conflict. A place merely holding the incoming id under some other heading
    is separate context (see 'alsoInKima'), not the collision itself.
    """
    owner = next((p for p in kima_places if p['how'] == 'owns-heading'), None)
    if owner is None:
        return 'kima-unresolved', 'לא אותר מקום בכימה עבור הכותרת'
    mz = owner['kimaMazal']
    if not mz:
        return 'kima-no-nli-id', 'למקום בכימה אין מזהה NLI שמור'
    if mz == incoming['recordId']:
        return 'same-id', 'כימה כבר מצביעה על אותה רשומה'
    st = kima_marcs.get(mz, {}).get('status')
    if st == 'suppressed':
        return 'kima-id-suppressed', 'המזהה בכימה קיים במאגר אך אינו נמסר — נמחק/הוסתר'
    if st == 'absent':
        return 'kima-id-absent', 'המזהה בכימה אינו קיים כלל במאגר NLI'
    if st == 'live':
        return 'both-live', 'שתי הרשומות קיימות ב־NLI — כפילות אמיתית'
    return 'unknown-status', 'סטטוס המזהה בכימה: %s' % st


def analyse(case):
    rid = case['recordId']
    heading, places = kima_side(case)
    incoming = marc_summary(rid)
    kima_marcs = {}
    for p in places:
        mz = p['kimaMazal']
        if mz and mz not in kima_marcs:
            kima_marcs[mz] = marc_summary(mz)
    kind, note = verdict(incoming, places, kima_marcs)

    # Kima already carrying the incoming record under a *different* place is a
    # merge candidate: the same NLI record would end up in Kima twice
    owner = next((p for p in places if p['how'] == 'owns-heading'), None)
    also = next((p for p in places if p['how'] == 'holds-incoming-id'
                 and (not owner or p['kimaId'] != owner['kimaId'])), None)

    dist = None
    kp = owner if (owner and owner['lat'] is not None) else \
        next((p for p in places if p['lat'] is not None), None)
    if incoming['coords'] and kp:
        dist = srv.haversine(incoming['coords'], (kp['lat'], kp['lon']))

    # variant overlap between the incoming record and the live Kima-held one
    shared = []
    live = [m for m in kima_marcs.values() if m['status'] == 'live']
    if live:
        inc = {srv.nfc(v) for v in incoming['variants']} | set(incoming['primary'].values())
        for m in live:
            other = {srv.nfc(v) for v in m['variants']} | set(m['primary'].values())
            shared += sorted(inc & other)

    # Entity succession: a 551 $w a means this record replaced an EARLIER
    # heading, i.e. NLI changed what the entity is (region -> country), not
    # just how it is spelled. Rare, and never merely a centroid difference.
    earlier = [h['name'] for h in incoming['headingLinks'] if h['rel'] == 'earlier']

    # Per-language name drift: Kima's stored primary vs the record's own 151 in
    # the same script. Cross-script translation defeats string matching, so
    # compare like with like — a mismatch is concrete and checkable.
    LANG = {'heb': 'heb', 'rom': 'lat', 'arab': 'ara'}
    mismatch = []
    for p in places:
        for fld, code in LANG.items():
            kv, nv = srv.nfc(p.get(fld) or ''), srv.nfc(incoming['primary'].get(code) or '')
            if kv and nv and kv != nv:
                mismatch.append({'kimaId': p['kimaId'], 'field': fld,
                                 'kima': kv, 'nli': nv})

    return {
        'recordId': rid, 'category': case['category'], 'period': case['period'],
        'dupKey': case.get('dupKey'), 'heading': heading,
        'verdict': kind, 'verdictNote': note,
        'incoming': incoming, 'kimaPlaces': places,
        'kimaMarc': kima_marcs, 'distanceKm': dist,
        'sharedNames': sorted(set(shared)),
        'alsoInKima': also,
        'earlierHeadings': earlier,
        'nameMismatch': mismatch,
    }


# -------------------------------------------------------------------- output

COLUMNS = ['recordId', 'category', 'verdict', 'heading', 'dupKey',
           'incomingStatus', 'incomingHeb', 'incomingCoords',
           'kimaId', 'kimaMazal', 'kimaMazalStatus', 'kimaHeb', 'kimaCoords',
           'kimaVariantCount', 'distanceKm', 'sharedNames', 'alsoInKimaId',
           'earlierHeadings', 'nameMismatch', 'verdictNote']


def to_row(a):
    p = next((x for x in a['kimaPlaces'] if x['how'] == 'owns-heading'), {})
    mz = p.get('kimaMazal') or ''
    coords = a['incoming']['coords']
    return {
        'recordId': a['recordId'], 'category': a['category'],
        'verdict': a['verdict'], 'heading': a['heading'] or '',
        'dupKey': a['dupKey'] or '',
        'incomingStatus': a['incoming']['status'],
        'incomingHeb': a['incoming']['primary'].get('heb')
                       or next(iter(a['incoming']['primary'].values()), ''),
        'incomingCoords': '%s, %s' % tuple(coords) if coords else '',
        'kimaId': p.get('kimaId', ''), 'kimaMazal': mz,
        'kimaMazalStatus': a['kimaMarc'].get(mz, {}).get('status', ''),
        'kimaHeb': p.get('heb') or '',
        'kimaCoords': ('%s, %s' % (p['lat'], p['lon'])
                       if p.get('lat') is not None else ''),
        'kimaVariantCount': len(p.get('variants') or []),
        'distanceKm': '' if a['distanceKm'] is None else a['distanceKm'],
        'sharedNames': ' | '.join(a['sharedNames']),
        'alsoInKimaId': (a['alsoInKima'] or {}).get('kimaId', ''),
        'earlierHeadings': ' | '.join(a['earlierHeadings']),
        'nameMismatch': ' | '.join('%s: kima=%s nli=%s' % (m['field'], m['kima'], m['nli'])
                                   for m in a['nameMismatch']),
        'verdictNote': a['verdictNote'],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--categories', default=','.join(DUP_CATEGORIES))
    ap.add_argument('--limit', type=int)
    ap.add_argument('--out', default='dup-analysis',
                    help='basename under app/ for the .tsv/.json output')
    args = ap.parse_args()
    wanted = [c.strip() for c in args.categories.split(',') if c.strip()]

    cases = [c for c in DATA.cases if c['category'] in wanted]
    if args.limit:
        cases = cases[:args.limit]
    print('analysing %d cases in %s' % (len(cases), ', '.join(wanted)))

    out = []
    for i, case in enumerate(cases, 1):
        a = analyse(case)
        out.append(a)
        print('  [%d/%d] %s  %-16s %s' % (i, len(cases), a['recordId'],
                                          a['verdict'], a['heading'] or ''))
        sys.stdout.flush()

    with open(os.path.join(APP_DIR, args.out + '.json'), 'w') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(APP_DIR, args.out + '.tsv'), 'w') as fh:
        fh.write('\t'.join(COLUMNS) + '\n')
        for a in out:
            r = to_row(a)
            fh.write('\t'.join(str(r[c]).replace('\t', ' ') for c in COLUMNS) + '\n')

    tally = {}
    for a in out:
        tally[a['verdict']] = tally.get(a['verdict'], 0) + 1
    print('\nverdicts:')
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print('  %-18s %d' % (k, v))
    print('\nwrote app/%s.tsv and app/%s.json' % (args.out, args.out))


if __name__ == '__main__':
    main()
