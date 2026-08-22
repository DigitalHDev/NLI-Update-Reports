#!/usr/bin/env python3
"""Local review app for NLI update-report failures.

Zero-dependency (stdlib only). Serves a two-card UI: the incoming ("new")
record parsed from the report MARC vs. the place currently holding the same
Hebrew heading in Kima. All outbound API calls happen server-side.

Run:  python3 app/server.py   →  http://localhost:8765
"""
import json
import glob
import io
import os
import re
import csv
import math
import time
import unicodedata
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(APP_DIR)
CACHE_DIR = os.path.join(APP_DIR, '.cache')
KIMA_DUMP = os.environ.get(
    'KIMA_DUMP',
    os.path.expanduser('~/Documents/GitHub/Kimatch/20250126KimaPlacesCSVx.csv'))
KIMA_VARIANTS = [
    os.path.expanduser('~/Documents/GitHub/Kimatch/Kima-Variants-20250929.tsv'),
    os.path.expanduser('~/Documents/GitHub/Kimatch/Kima-Variants-20250929-missing-tsv.tsv'),
]
KIMA_API = 'https://data.geo-kima.org/api'
PORT = int(os.environ.get('PORT', '8765'))


def nfc(s):
    return unicodedata.normalize('NFC', s) if s else s


# ---------------------------------------------------------------- categories

def categorize(msg):
    if 'dbo.Places' in msg:
        return 'dup-places'
    if 'dbo.Variants' in msg:
        return 'dup-variants'
    if 'does not exist in repository' in msg:
        return 'missing-marc'
    if 'geography' in msg:
        return 'bad-geography'
    return 'other'


DUP_KEY_RE = re.compile(r"duplicate key value is \((.*?)\)\.\s*(?:\n|The statement|$)", re.S)

# the two review sub-classes of "NLI announced an id whose MARC it won't serve",
# both of which the runner reports as present in Kima (see Data.GONE_IN_KIMA)
NLI_GONE = ('nli-gone-suggest-delete', 'nli-gone-possibly')


# ---------------------------------------------------------------- MARC parse

PACKED_COORD = re.compile(r'^([NSEW])(\d{3})(\d{2})(\d{2}(?:\.\d+)?)$')


def parse_coord(v):
    """034 subfield value: decimal degrees or packed hdddmmss (e.g. E0120000)."""
    if not v:
        return None
    v = v.strip()
    try:
        return float(v)
    except ValueError:
        pass
    m = PACKED_COORD.match(v)
    if m:
        sign = -1 if m.group(1) in 'SW' else 1
        return sign * (int(m.group(2)) + int(m.group(3)) / 60 + float(m.group(4)) / 3600)
    return None


def parse_marc(xml):
    """Extract naming info, external ids, coordinates and notes from MARC XML."""
    xml = nfc(xml)
    rec = {'primary': {}, 'variants': [], 'seealso': [], 'ids': {}, 'notes': [],
           'sources': [], 'coords': None, 'bbox': None, 'coordsList': []}
    for m in re.finditer(r'<datafield[^>]*tag="(\d+)"[^>]*>(.*?)</datafield>', xml, re.S):
        tag, body = m.group(1), m.group(2)
        pairs = re.findall(r'code="(\w)">([^<]*)<', body)
        subs = {}
        for c, v in pairs:
            subs.setdefault(c, v)
        a = subs.get('a', '').strip()
        lang = subs.get('9', '')
        if tag == '151' and a:
            rec['primary'][lang or 'und'] = a
        elif tag == '451' and a:
            rec['variants'].append({'name': a, 'lang': lang})
        elif tag == '551' and a:
            rec['seealso'].append(a)
        elif tag == '024':
            scheme = subs.get('2', '').lower()
            if scheme and a:
                rec['ids'][scheme] = a
        elif tag == '010' and a:
            rec['ids']['lccn'] = a
        elif tag == '035' and a:
            rec['ids'].setdefault('aleph', a)
        elif tag == '034':
            d = parse_coord(subs.get('d')); e = parse_coord(subs.get('e'))
            f = parse_coord(subs.get('f')); g = parse_coord(subs.get('g'))
            if None not in (d, e, f, g):
                center = [round((f + g) / 2, 5), round((d + e) / 2, 5)]
                rec['coordsList'].append({'center': center,
                                          'source': subs.get('2', '')})
                if rec['coords'] is None:
                    rec['coords'] = center
                    rec['bbox'] = [g, d, f, e]
        elif tag == '667' and a:
            rec['notes'].append(a)
        elif tag == '670':
            src = a
            if subs.get('b'):
                src += ' — ' + subs['b']
            rec['sources'].append(src)
    return rec


# ---------------------------------------------------------------- data load

class Data:
    def __init__(self):
        self.cases = []          # failure rows
        self.marc = {}           # recordId -> parsed marc card
        self.history = {}        # heading -> [{recordId, period, event}]
        self.dump_by_heb = {}
        self.dump_by_mazal = {}
        self.kima_cache = {}     # heading/id keys -> kima place json or None
        self.decisions = {}
        self.seen = set()        # recordIds already turned into a case
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._load_decisions()
        self._load_failures()
        self._load_reviews()
        self._load_orphans()
        self._load_marc()
        self._load_dump()
        self._load_history()
        self._load_kima_cache()
        self._classify_multi_034()
        self._classify_dup_places()

    # -- dup-places: does Kima's owner of the heading carry the same NLI id? --
    def _classify_dup_places(self):
        """Split place-name collisions by whether Kima already points at this
        very record (same MAZAL_ID) or at a different NLI authority."""
        n = {'same': 0, 'diff': 0, 'unresolved': 0}
        for case in self.cases:
            if case['category'] != 'dup-places' or not case['dupKey']:
                continue
            # for dup-places the failure key *is* the heading (see case_heading)
            place = (self.kima_by_heading(case['dupKey']) or {}).get('place') or {}
            mazal = str(place.get('MAZAL_ID') or '').strip()
            if not mazal:
                n['unresolved'] += 1      # no owner resolved — leave as-is
                continue
            case['kimaMazal'] = mazal
            if mazal == case['recordId']:
                case['category'] = 'dup-places-same'
                n['same'] += 1
            else:
                case['category'] = 'dup-places-diff'
                n['diff'] += 1
        if any(n.values()):
            print('dup-places split: same NLI id %d, different NLI id %d, '
                  'unresolved %d' % (n['same'], n['diff'], n['unresolved']))

    # -- multi-034: two coordinate sources in the record, one matching Kima --
    def _classify_multi_034(self):
        n = 0
        for case in self.cases:
            if case['category'] != 'location-move':
                continue
            marc = self.marc.get(case['recordId'])
            if not marc or len(marc.get('coordsList') or []) < 2:
                continue
            centers = {tuple(c['center']) for c in marc['coordsList']}
            if len(centers) < 2:
                continue
            place = self.kima_place_by_id(case['kimaId'])
            if not place or place.get('lat') is None:
                continue
            kc = (place['lat'], place['lon'])
            if min(haversine(c, kc) for c in centers) <= 1.0:
                case['category'] = 'multi-034'
                n += 1
        if n:
            print('multi-034 cases separated from location-move: %d' % n)

    # -- decisions ---------------------------------------------------------
    def _load_decisions(self):
        path = os.path.join(APP_DIR, 'decisions.json')
        if os.path.exists(path):
            self.decisions = json.load(open(path))

    def save_decision(self, rid, payload):
        if payload.get('decision') or payload.get('forGili'):
            self.decisions[rid] = {
                'decision': payload.get('decision') or '',
                'forGili': bool(payload.get('forGili')),
                'suggestedNewName': payload.get('suggestedNewName', ''),
                'suggestedExistingName': payload.get('suggestedExistingName', ''),
                'manualLat': payload.get('manualLat', ''),
                'manualLon': payload.get('manualLon', ''),
                'correctWd': payload.get('correctWd', ''),
                'note': payload.get('note', ''),
                'timestampUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            }
        else:
            self.decisions.pop(rid, None)
        json.dump(self.decisions, open(os.path.join(APP_DIR, 'decisions.json'), 'w'),
                  ensure_ascii=False, indent=1)

    # -- failures ----------------------------------------------------------
    def _load_failures(self):
        """Failure rows from the current report set.

        A re-run overwrites these files, so a row that stopped failing (or
        moved to the manual-review track) silently disappears. Decisions made
        against such a row resurface via _load_orphans.
        """
        for path in sorted(glob.glob(os.path.join(REPO, 'failures-combined_*.json'))):
            for row in json.load(open(path)):
                if row['recordId'] in self.seen:
                    continue
                self.seen.add(row['recordId'])
                msg = nfc(' | '.join(row['messages']))
                cat = categorize(msg)
                dk = DUP_KEY_RE.search(msg)
                key = nfc(dk.group(1).strip()) if dk else None
                self.cases.append({
                    'recordId': row['recordId'],
                    'period': row['period'],
                    'track': row['track'],
                    'category': cat,
                    'isNew': 'addPlaceRecord' in msg,
                    'dupKey': key,
                    'messages': [nfc(m) for m in row['messages']],
                    'manualAction': row.get('manualAction'),
                    'sourceFile': os.path.basename(path),
                    'stale': False,
                })

    # -- manual-review rows -------------------------------------------------
    LOC_RE = re.compile(r'Location supposed to move ([\d.]+) km.*?Kima Id:(\d+) Name:(.*)')
    # heading collision surfaced as a review row rather than a duplicate-key
    # failure: the incoming record wants a Kima place another NLI id still owns
    REPOINT_RE = re.compile(
        r'would repoint onto Kima Id (\d+) \(currently MAZAL_ID (\d+)\)')
    # NLI's weekly feed announced this id, but NLI's own MARC endpoint 404s for
    # it. Unlike the 'missing-marc' failures, Kima *does* hold the record — the
    # runner says so explicitly — so these are review rows, not failures. Two
    # wordings, and the runner means different things by them.
    GONE_IN_KIMA = 'although it is in the Kima database'
    GONE_SUGGEST_DELETE = 'no longer exists in NLI'

    def _load_reviews(self):
        for path in sorted(glob.glob(os.path.join(REPO, 'manual-review-combined_*.json'))):
            for row in json.load(open(path)):
                if row['recordId'] in self.seen:
                    continue
                msgs = [nfc(m) for m in row['messages']]
                case = None
                for x in msgs:
                    m = self.LOC_RE.search(x)
                    if m:
                        case = {'category': 'location-move',
                                'kimaId': int(m.group(2)),
                                'movedKm': float(m.group(1)),
                                'kimaName': nfc(m.group(3).strip())}
                        break
                    m = self.REPOINT_RE.search(x)
                    if m:
                        case = {'category': 'repoint-blocked',
                                'kimaId': int(m.group(1)),
                                'blockingMazal': m.group(2)}
                        break
                    if self.GONE_IN_KIMA in x:
                        case = {'category': 'nli-gone-suggest-delete'
                                            if self.GONE_SUGGEST_DELETE in x
                                            else 'nli-gone-possibly'}
                        break
                if case is None:
                    continue
                self.seen.add(row['recordId'])
                self.cases.append({
                    'recordId': row['recordId'],
                    'period': row['period'],
                    'track': row['track'],
                    'isNew': False,
                    'dupKey': None,
                    'movedKm': None,
                    'kimaName': None,
                    'messages': msgs,
                    'manualAction': row.get('manualAction'),
                    'sourceFile': os.path.basename(path),
                    'stale': False,
                    **case,
                })

    # -- decided records that no longer appear in any report ----------------
    def _load_orphans(self):
        for rid in self.decisions:
            if rid in self.seen:
                continue
            self.seen.add(rid)
            self.cases.append({
                'recordId': rid,
                'period': '—',
                'track': 'Place',
                'category': 'orphan-decision',
                'isNew': False,
                'dupKey': None,
                'messages': ['ההחלטה נשמרה בריצה קודמת; הרשומה אינה מופיעה '
                             'עוד באף דוח (לא בכשלים ולא בסקירה הידנית).'],
                'manualAction': None,
                'sourceFile': 'decisions.json',
                'stale': True,
            })

    # -- weekly MARC -------------------------------------------------------
    SECTIONS = ('failedItems', 'requireReviewItems', 'newSummary', 'modifiedSummary')

    def _load_marc(self):
        wanted = {c['recordId'] for c in self.cases}
        by_id = {c['recordId']: c for c in self.cases}
        for period in sorted({c['period'] for c in self.cases}):
            path = os.path.join(REPO, 'places_%s.json' % period)
            if not os.path.exists(path):
                continue
            d = json.load(open(path))
            for sect in ('failedItems', 'requireReviewItems'):
                for it in d.get(sect) or []:
                    rid = it['item']['recordId']
                    if rid in wanted and rid not in self.marc and it.get('marcXml'):
                        # no marcXml at all → leave unset, so the card reads
                        # "missing" rather than rendering an empty record
                        self.marc[rid] = parse_marc(it['marcXml'])
        # records whose period is unknown (orphaned decisions) or whose weekly
        # file no longer carries them: sweep every weekly file, all sections
        missing = wanted - set(self.marc)
        if not missing:
            return
        for path in sorted(glob.glob(os.path.join(REPO, 'places_*.json'))):
            if not missing:
                return
            period = os.path.basename(path)[len('places_'):-len('.json')]
            d = json.load(open(path))
            for sect in self.SECTIONS:
                for it in d.get(sect) or []:
                    rid = it['item']['recordId']
                    if rid in missing:
                        if it.get('marcXml'):
                            self.marc[rid] = parse_marc(it['marcXml'])
                        missing.discard(rid)
                        if by_id[rid]['period'] == '—':
                            by_id[rid]['period'] = period

    # -- Kima local dump ---------------------------------------------------
    def _load_dump(self):
        if os.path.exists(KIMA_DUMP):
            with open(KIMA_DUMP) as fh:
                for row in csv.DictReader(fh):
                    heb = nfc(row['primary_heb_full'])
                    self.dump_by_heb[heb] = row
                    mz = (row.get('MAZAL_ID') or '').strip()
                    if mz and mz != 'NULL':
                        self.dump_by_mazal[mz] = row
        # variant dumps: PlaceId -> [variant, ...]
        self.variants_by_place = {}
        for path in KIMA_VARIANTS:
            if not os.path.exists(path):
                continue
            with open(path) as fh:
                lines = fh.read().splitlines()
            while lines and not lines[0].startswith('Id\t'):
                lines = lines[1:]          # skip junk pre-header rows
            if not lines:
                continue
            header = lines[0].split('\t')
            i_var, i_pid = header.index('variant'), header.index('PlaceId')
            for line in lines[1:]:
                parts = line.split('\t')
                if len(parts) <= max(i_var, i_pid):
                    continue
                pid, v = parts[i_pid].strip(), nfc(parts[i_var].strip())
                if pid and v:
                    lst = self.variants_by_place.setdefault(pid, [])
                    if v not in lst:
                        lst.append(v)

    # -- feed history (added/renamed headings) -----------------------------
    def _load_history(self):
        cache = os.path.join(CACHE_DIR, 'history_index.json')
        if os.path.exists(cache):
            self.history = json.load(open(cache))
            return
        add_re = re.compile(r'addPlaceRecord: added place (\d+) \((.+?)\)\s*$')
        ren_re = re.compile(r"Updated PrimaryHebFull from '(.*?)' to '(.*?)'")
        hist = {}
        for pf in sorted(glob.glob(os.path.join(REPO, 'places_*.json'))):
            period = os.path.basename(pf)[len('places_'):-len('.json')]
            d = json.load(open(pf))
            for sect in ('newSummary', 'modifiedSummary'):
                for it in d.get(sect) or []:
                    if it.get('result') != 'Success':
                        continue
                    rid = it['item']['recordId']
                    for msg in it['messages']:
                        msg = nfc(msg)
                        m = add_re.search(msg)
                        if m:
                            hist.setdefault(nfc(m.group(2)), []).append(
                                {'recordId': rid, 'period': period, 'event': 'added'})
                        m = ren_re.search(msg)
                        if m:
                            hist.setdefault(nfc(m.group(2)), []).append(
                                {'recordId': rid, 'period': period,
                                 'event': "renamed from '%s'" % nfc(m.group(1))})
        self.history = hist
        json.dump(hist, open(cache, 'w'), ensure_ascii=False)

    # -- Kima lookups ------------------------------------------------------
    def _load_kima_cache(self):
        cache = os.path.join(CACHE_DIR, 'kima_cache.json')
        if os.path.exists(cache):
            self.kima_cache = json.load(open(cache))

    def _save_kima_cache(self):
        json.dump(self.kima_cache, open(os.path.join(CACHE_DIR, 'kima_cache.json'), 'w'),
                  ensure_ascii=False)

    def _kima_get(self, path):
        url = KIMA_API + path
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception:
            return None

    def kima_place_by_id(self, pid):
        ck = 'id:%s' % pid
        if ck not in self.kima_cache:
            self.kima_cache[ck] = self._kima_get('/Places/%s' % pid)
            self._save_kima_cache()
        return self.kima_cache[ck]

    def kima_by_heading(self, heading):
        """Resolve a Hebrew heading to the Kima place currently owning it."""
        ck = 'heb:%s' % heading
        if ck in self.kima_cache:
            return self.kima_cache[ck]
        result = None
        # 1. live API — exact heading match via variant search
        for q in (heading, heading.split(' (')[0]):
            hits = self._kima_get('/Places/ByVariant/%s/0'
                                  % urllib.parse.quote(q, safe='')) or []
            exact = [p for p in hits if nfc(p.get('primary_heb_full') or '') == heading]
            if exact:
                result = {'source': 'kima-api', 'place': exact[0]}
                break
        # 2. local dump
        if result is None and heading in self.dump_by_heb:
            row = self.dump_by_heb[heading]
            place = self.kima_place_by_id(row['id'])
            result = {'source': 'local-dump', 'place': place or {
                'Id': int(row['id']),
                'primary_heb_full': row['primary_heb_full'],
                'primary_rom_full': row['primary_rom_full'],
                'primary_arab_full': None if row['primary_arab_full'] == 'NULL' else row['primary_arab_full'],
                'MAZAL_ID': row['MAZAL_ID'],
                'NAF_ID': row['NAF_ID'], 'VIAF_ID': row['VIAF_ID'],
                'Geoname_ID': row['Geoname_ID'], 'WD': row['WikiData_Id'],
                'lat': None if row['lat'] == 'NULL' else float(row['lat']),
                'lon': None if row['lon'] == 'NULL' else float(row['lon']),
            }}
        # 3. feed history (row exists in update DB but predates no dump/API view)
        if result is None and heading in self.history:
            ev = self.history[heading][-1]
            result = {'source': 'feed-history (%s %s)' % (ev['event'], ev['period']),
                      'place': {'primary_heb_full': heading,
                                'MAZAL_ID': ev['recordId']}}
        if result is None:
            result = {'source': 'unresolved', 'place': None}
        self.kima_cache[ck] = result
        self._save_kima_cache()
        return result


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


DATA = Data()


def case_heading(case):
    """The Hebrew heading whose Kima owner should appear on the 'kima now' card."""
    marc = DATA.marc.get(case['recordId'], {})
    if case['category'].startswith('dup-places') and case['dupKey']:
        return case['dupKey']
    # variants key = "<heading>, <variant>"; prefer the record's own heb 151
    heb = (marc.get('primary') or {}).get('heb')
    if heb:
        return heb
    if case['dupKey']:
        return case['dupKey'].split(', ')[0]
    return None


def build_case(case):
    rid = case['recordId']
    marc = DATA.marc.get(rid)
    heading = case_heading(case)
    kima = None
    if case['category'] in ('location-move', 'repoint-blocked'):
        kima = {'source': 'kima-api (by Kima Id %d)' % case['kimaId'],
                'place': DATA.kima_place_by_id(case['kimaId'])}
        if kima['place'] is None and heading:
            kima = DATA.kima_by_heading(heading)
    elif rid in DATA.dump_by_mazal and case['category'] in (
            ('missing-marc', 'orphan-decision') + NLI_GONE):
        row = DATA.dump_by_mazal[rid]
        kima = {'source': 'local-dump (by NLI id)',
                'place': DATA.kima_place_by_id(row['id']) or None}
    elif case['category'] in NLI_GONE:
        # the runner resolved this against live Kima and found the record; the
        # local dump is older than the report, so its silence proves nothing
        kima = {'source': 'in Kima per the report; not in the local dump '
                          '(dump predates this period)', 'place': None}
    elif case['category'] == 'missing-marc':
        # NLI serves no MARC for this id and Kima has no row under it either —
        # the runner's own verdict, not a lookup that failed
        kima = {'source': 'not in Kima either (runner: "Nothing to do")',
                'place': None}
    elif heading:
        kima = DATA.kima_by_heading(heading)
    place = (kima or {}).get('place')
    dist = None
    if marc and marc.get('coords') and place and place.get('lat') is not None:
        dist = haversine(marc['coords'], (place['lat'], place['lon']))
    kima_variants = []
    if place and place.get('Id') is not None:
        kima_variants = DATA.variants_by_place.get(str(place['Id']), [])
    # the variant named in a dup-variants failure key: "<heading>, <variant>"
    conflict_variant = None
    if case['category'] == 'dup-variants' and case['dupKey']:
        key = case['dupKey']
        heads = list((marc or {}).get('primary', {}).values())
        if place and place.get('primary_heb_full'):
            heads.append(nfc(place['primary_heb_full']))
        for h in sorted(set(heads), key=len, reverse=True):
            if h and key.startswith(h + ', '):
                conflict_variant = key[len(h) + 2:]
                break
        if conflict_variant is None and ', ' in key:
            conflict_variant = key.split(', ', 1)[1]
    return {
        **{k: case[k] for k in ('recordId', 'period', 'category', 'isNew',
                                'dupKey', 'messages', 'manualAction')},
        'kimaId': case.get('kimaId'),
        'movedKm': case.get('movedKm'),
        'kimaName': case.get('kimaName'),
        'stale': case.get('stale', False),
        'sourceFile': case.get('sourceFile'),
        'blockingMazal': case.get('blockingMazal'),
        'kimaMazal': case.get('kimaMazal'),
        'heading': heading,
        'newCard': marc,
        'kimaCard': place,
        'kimaVariants': kima_variants,
        'conflictVariant': conflict_variant,
        'kimaSource': (kima or {}).get('source'),
        'distanceKm': dist,
        'nliUrlNew': 'https://www.nli.org.il/he/authorities/%s' % rid,
        'nliUrlExisting': ('https://www.nli.org.il/he/authorities/%s' % place['MAZAL_ID'])
                          if place and place.get('MAZAL_ID') else None,
        'kimaUrl': ('https://data.geo-kima.org/Places/Details/%s' % place['Id'])
                   if place and place.get('Id') else None,
        'decision': DATA.decisions.get(rid),
    }


def export_csv():
    cols = ['decision', 'for_gili', 'suggested_new_name', 'suggested_existing_name',
            'manual_lat', 'manual_lon', 'correct_wd', 'note',
            'decided_at', 'period', 'category', 'stale', 'source_file',
            'new_id', 'new_url', 'new_heb', 'new_rom', 'new_ara',
            'new_wikidata', 'new_viaf', 'new_lccn', 'new_lat_lon',
            'existing_id', 'existing_url', 'existing_heb', 'existing_rom', 'existing_ara',
            'existing_wikidata', 'existing_viaf', 'existing_lat_lon',
            'kima_place_id', 'distance_km']
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for case in DATA.cases:
        d = DATA.decisions.get(case['recordId'])
        if not d or (d['decision'] == 'skip' and not d.get('forGili')):
            continue
        c = build_case(case)
        n, k = c.get('newCard') or {}, c.get('kimaCard') or {}
        p, ids = n.get('primary') or {}, n.get('ids') or {}
        w.writerow({
            'decision': d['decision'],
            'for_gili': 'yes' if d.get('forGili') else '',
            'suggested_new_name': d.get('suggestedNewName', ''),
            'suggested_existing_name': d.get('suggestedExistingName', ''),
            'manual_lat': d.get('manualLat', ''), 'manual_lon': d.get('manualLon', ''),
            'correct_wd': d.get('correctWd', ''),
            'note': d.get('note', ''), 'decided_at': d.get('timestampUtc', ''),
            'period': c['period'], 'category': c['category'],
            'stale': 'yes' if c.get('stale') else '',
            'source_file': c.get('sourceFile') or '',
            'new_id': c['recordId'], 'new_url': c['nliUrlNew'],
            'new_heb': p.get('heb', ''), 'new_rom': p.get('lat', ''), 'new_ara': p.get('ara', ''),
            'new_wikidata': ids.get('wikidata', ''), 'new_viaf': ids.get('viaf', ''),
            'new_lccn': ids.get('lccn', ''),
            'new_lat_lon': '%s,%s' % tuple(n['coords']) if n.get('coords') else '',
            'existing_id': k.get('MAZAL_ID', ''), 'existing_url': c.get('nliUrlExisting') or '',
            'existing_heb': nfc(k.get('primary_heb_full') or ''),
            'existing_rom': k.get('primary_rom_full') or '',
            'existing_ara': nfc(k.get('primary_arab_full') or ''),
            'existing_wikidata': (k.get('WD') or '').strip(),
            'existing_viaf': str(k.get('VIAF_ID') or '').strip(),
            'existing_lat_lon': ('%s,%s' % (k['lat'], k['lon']))
                                if k.get('lat') is not None else '',
            'kima_place_id': k.get('Id', ''), 'distance_km': c.get('distanceKm') or '',
        })
    return '\ufeff' + buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ('/', '/index.html'):
            with open(os.path.join(APP_DIR, 'index.html'), 'rb') as fh:
                self._send(200, fh.read(), 'text/html; charset=utf-8')
        elif url.path == '/api/cases':
            qs = urllib.parse.parse_qs(url.query)
            cat = qs.get('category', ['all'])[0]
            pool = DATA.cases
            if qs.get('current', [''])[0] == '1':
                pool = [c for c in pool if not c.get('stale')]
            cases = [c for c in pool if cat in ('all', c['category'])]
            self._send(200, {
                'total': len(cases),
                'staleTotal': sum(1 for c in DATA.cases if c.get('stale')),
                'categories': {k: sum(1 for c in pool if c['category'] == k)
                               for k in sorted({c['category'] for c in pool})},
                'cases': [{**{k: c[k] for k in ('recordId', 'period', 'category',
                                                'isNew', 'dupKey', 'manualAction')},
                           'stale': c.get('stale', False),
                           'decision': (DATA.decisions.get(c['recordId']) or {}).get('decision'),
                           'forGili': (DATA.decisions.get(c['recordId']) or {}).get('forGili', False)}
                          for c in cases],
            })
        elif url.path.startswith('/api/case/'):
            rid = url.path.rsplit('/', 1)[1]
            case = next((c for c in DATA.cases if c['recordId'] == rid), None)
            if case is None:
                self._send(404, {'error': 'unknown recordId'})
            else:
                self._send(200, build_case(case))
        elif url.path == '/export.csv':
            body = export_csv().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition',
                             'attachment; filename="nli-triage-report.csv"')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, {'error': 'not found'})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == '/api/decision':
            length = int(self.headers.get('Content-Length') or 0)
            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(400, {'error': 'bad json'})
                return
            rid = payload.get('recordId')
            if not any(c['recordId'] == rid for c in DATA.cases):
                self._send(404, {'error': 'unknown recordId'})
                return
            DATA.save_decision(rid, payload)
            self._send(200, {'ok': True, 'decision': DATA.decisions.get(rid)})
        else:
            self._send(404, {'error': 'not found'})


if __name__ == '__main__':
    orphan = sum(1 for c in DATA.cases if c['category'] == 'orphan-decision')
    print('cases: %d  (decided in an earlier run, no longer reported: %d)'
          % (len(DATA.cases), orphan))
    print('marc parsed: %d, dump rows: %d, history headings: %d'
          % (len(DATA.marc), len(DATA.dump_by_heb), len(DATA.history)))
    print('serving on http://localhost:%d' % PORT)
    # threading: a browser keeps idle/preconnect sockets open, and a
    # single-threaded server blocks on them instead of serving real requests
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
