#!/usr/bin/env python3
"""Classify the `location-move` cases (NLI coordinates differ from Kima's)
into recurring buckets, using Wikidata as an independent arbiter.

Emits app/move-analysis.{tsv,json}.  Wikidata entities are cached under
app/.cache/wikidata.json so re-runs are offline.

Buckets (see app/move-analysis.md for the write-up):
  nli-034-antimeridian  034 box crosses 180°, the (d+e)/2 centre is garbage  → runner bug
  nli-034-dropped-zero  one 034 fraction lost its leading 0 (051.836979 = 051.0836979) → report NLI
  extended-feature      river / region / sea / range … — both points lie on the feature
  kima-coords-wrong     Wikidata agrees with NLI, not Kima                  → apply-new
  nli-coords-wrong      Wikidata agrees with Kima, not NLI                  → keep, report NLI
  kima-wd-wrong         Kima's QID is a different entity whose name doesn't match
  kima-geonames-wrong   Kima's GeoNames id (via P1566) is a different entity
  nli-wd-wrong          NLI's QID is a different entity whose name doesn't match
  homonym               two legitimate same-named places; NLI self-consistent → apply-new, else research
  wd-disagrees          Wikidata sits near neither point
  no-wd                 nothing to arbitrate with (no 024, no P8189, no usable GeoNames)

Wikidata lookups: QIDs from NLI 024 and Kima WD; fallbacks via haswbstatement
search on P8189 (NLI J9U id) and P1566 (Kima's GeoNames id).
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server                                              # noqa: E402
from server import DATA, haversine, nfc                    # noqa: E402

APP = os.path.dirname(os.path.abspath(__file__))
WD_CACHE = os.path.join(APP, '.cache', 'wikidata.json')
NEAR_KM = 20.0          # the runner's own move threshold (min observed 20.1)

# ------------------------------------------------------------------ wikidata

def load_cache():
    if os.path.exists(WD_CACHE):
        return json.load(open(WD_CACHE))
    return {}


def save_cache(c):
    json.dump(c, open(WD_CACHE, 'w'), ensure_ascii=False)


def wd_fetch(qids, cache):
    need = [q for q in dict.fromkeys(qids) if q and str(q).startswith("Q") and q not in cache]
    for i in range(0, len(need), 50):
        batch = need[i:i + 50]
        url = ('https://www.wikidata.org/w/api.php?action=wbgetentities&format=json'
               '&props=claims|labels|descriptions&languages=en|he&ids=' + '|'.join(batch))
        req = urllib.request.Request(url, headers={'User-Agent': 'kima-nli-review/1 (sinai.rusinek@gmail.com)'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                ents = json.load(r).get('entities', {})
        except Exception as e:                              # pragma: no cover
            print('wikidata fetch failed:', e, file=sys.stderr)
            ents = {}
        for q in batch:
            e = ents.get(q) or {}
            cache[q] = slim(e) if 'claims' in e else {'missing': True}
        save_cache(cache)
        time.sleep(0.3)


def wd_search_by_statement(prop, value, cache):
    """QID holding `prop = value` (via haswbstatement search), cached; None if none."""
    key = 'search:%s=%s' % (prop, value)
    if key in cache:
        return cache[key]
    url = ('https://www.wikidata.org/w/api.php?action=query&list=search&format=json&srlimit=3'
           '&srsearch=' + urllib.parse.quote('haswbstatement:%s=%s' % (prop, value)))
    req = urllib.request.Request(url, headers={'User-Agent': 'kima-nli-review/1 (sinai.rusinek@gmail.com)'})
    hits = []
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            hits = [h['title'] for h in json.load(r)['query']['search']]
    except Exception as e:                                  # pragma: no cover
        print('wikidata search failed:', e, file=sys.stderr)
        return None
    cache[key] = hits[0] if len(hits) == 1 else (hits[0] if hits else None)
    if len(hits) > 1:
        cache[key + ':all'] = hits
    save_cache(cache)
    time.sleep(0.3)
    return cache[key]


def first_val(claims, prop):
    for c in claims.get(prop, []):
        ms = c.get('mainsnak', {})
        if ms.get('snaktype') == 'value':
            return ms['datavalue']['value']
    return None


def all_ids(claims, prop):
    out = []
    for c in claims.get(prop, []):
        ms = c.get('mainsnak', {})
        if ms.get('snaktype') == 'value':
            out.append(ms['datavalue']['value']['id'])
    return out


def slim(e):
    cl = e.get('claims', {})
    coord = first_val(cl, 'P625')
    area = first_val(cl, 'P2046')
    length = first_val(cl, 'P2043')
    redirect = e.get('redirects', {}).get('to')
    return {
        'label_en': e.get('labels', {}).get('en', {}).get('value'),
        'label_he': e.get('labels', {}).get('he', {}).get('value'),
        'desc_en': e.get('descriptions', {}).get('en', {}).get('value'),
        'coord': [coord['latitude'], coord['longitude']] if coord else None,
        'p31': all_ids(cl, 'P31'),
        'area_km2': qty_km2(area),
        'length_km': qty_km(length),
        'redirect': redirect,
    }


UNIT_KM2 = {'Q712226': 1.0, 'Q25343': 1e-6, 'Q232291': 2.59, 'Q35852': 0.01,
            'Q81292': 0.00404686}
UNIT_KM = {'Q828224': 1.0, 'Q11573': 0.001, 'Q253276': 1.609344}


def qty_km2(v):
    if not v:
        return None
    try:
        return float(v['amount']) * UNIT_KM2.get(v['unit'].rsplit('/', 1)[-1], 1.0)
    except Exception:
        return None


def qty_km(v):
    if not v:
        return None
    try:
        return float(v['amount']) * UNIT_KM.get(v['unit'].rsplit('/', 1)[-1], 1.0)
    except Exception:
        return None


# ------------------------------------------------------------------ raw 034

def load_raw_034(record_ids):
    """recordId -> list of {'d','e','f','g','2'} raw strings from the weekly files."""
    import glob
    out = {}
    want = set(record_ids)
    for path in sorted(glob.glob(os.path.join(server.REPO, 'places_*.json'))):
        if not want:
            break
        d = json.load(open(path))
        for sect in server.Data.SECTIONS:
            for it in d.get(sect) or []:
                rid = it['item']['recordId']
                if rid in want and it.get('marcXml'):
                    fields = []
                    for m in re.finditer(r'<datafield[^>]*tag="034"[^>]*>(.*?)</datafield>', it['marcXml'], re.S):
                        fields.append(dict(re.findall(r'code="(\w)">([^<]*)<', m.group(1))))
                    out[rid] = fields
                    want.discard(rid)
    return out


def _zero_variants(v):
    """the value as given, plus the value with a '0' re-inserted after the point"""
    v = (v or '').strip()
    yield v
    if re.match(r'^-?\d+\.\d+$', v):
        i = v.index('.')
        yield v[:i + 1] + '0' + v[i + 1:]


def dropped_zero_fix(raw034):
    """If a 034 box is implausibly wide on one axis and re-inserting a lost leading
    zero in one subfield's fraction makes it narrow, return (fixed_center, desc)."""
    import itertools
    for f in raw034:
        vals = {k: f.get(k) for k in 'defg'}
        if any(not vals[k] for k in 'defg'):
            continue
        try:
            orig = {k: float(vals[k]) for k in 'defg'}
        except ValueError:
            continue
        w0, h0 = abs(orig['e'] - orig['d']), abs(orig['f'] - orig['g'])
        if max(w0, h0) < 0.25:
            continue
        best = None
        for combo in itertools.product(*[list(_zero_variants(vals[k])) for k in 'defg']):
            if combo == tuple(vals[k] for k in 'defg'):
                continue
            try:
                d, e, fl, g = map(float, combo)
            except ValueError:
                continue
            w, h = abs(e - d), abs(fl - g)
            if max(w, h) < 0.25 and fl >= g and e >= d:
                changed = [k for k, a, b in zip('defg', combo, [vals[k] for k in 'defg']) if a != b]
                cand = (len(changed), max(w, h), [(fl + g) / 2, (d + e) / 2], changed, combo)
                if best is None or cand[:2] < best[:2]:
                    best = cand
        if best:
            n, _, center, changed, combo = best
            desc = ', '.join('$%s %s -> %s' % (k, vals[k], c) for k, c in zip('defg', combo) if vals[k] != c)
            return [round(center[0], 5), round(center[1], 5)], desc
    return None, None


def antimeridian_fix(raw034):
    """034 box with west > east (crosses 180°): the naive (d+e)/2 centre is wrong.
    Returns (corrected_center, desc) or (None, None)."""
    for f in raw034:
        try:
            d, e, fl, g = (float(f[k]) for k in 'defg')
        except (KeyError, ValueError):
            continue
        if d > e and (d - e) > 180:
            lon = ((d + e + 360) / 2)
            if lon > 180:
                lon -= 360
            return [round((fl + g) / 2, 5), round(lon, 5)], '$d %s > $e %s (box crosses 180°)' % (f['d'], f['e'])
    return None, None


def bbox_extent_km(raw034):
    """half-diagonal of the NLI bounding box, km (0 for a point)"""
    best = 0.0
    for f in raw034:
        try:
            d, e, fl, g = (float(f[k]) for k in 'defg')
        except (KeyError, ValueError):
            continue
        best = max(best, haversine((g, d), (fl, e)) / 2)
    return best


# ------------------------------------------------------------------ feature type

EXTENDED_RE = re.compile(
    r'\b(river|rivers|stream|creek|brook|canal|region|regions|sea|ocean|gulf|bay|strait|'
    r'channel|sound|lake|lakes|lagoon|mountain|mountains|range|ranges|massif|hills|highlands|'
    r'uplands|plateau|island|islands|archipelago|valley|desert|peninsula|isthmus|coast|'
    r'forest|park|reserve|reservation|refuge|marsh|marshes|swamp|wetland|basin|delta|plain|'
    r'plains|steppe|tundra|glacier|reef|cape|ridge|escarpment|gorge|canyon|continent|'
    r'country|countries|state|province|district|county|department|oblast|voivodeship|'
    r'governorate|prefecture|kingdom|empire|republic|territory|land|area|zone|road|route|'
    r'trail|railway|line|wall|border|historical|former|cultural|geographic|natural|'
    r'watershed|drainage|subcontinent|riviera|harbor|harbour|fjord|firth|estuary|'
    r'reservoir|pass|tribal|nation|federal subject)\b', re.I)
POINT_RE = re.compile(r'\b(city|town|village|municipality|human settlement|borough|'
                      r'neighbou?rhood|hamlet|suburb|commune|quarter|urban|locality|'
                      r'kibbutz|moshav|street|square|building|site|castle|monastery|'
                      r'archaeological|ruins|railway station|airport|fort)\b', re.I)
HEADING_EXT_RE = re.compile(
    r'\b(River|Rivers|Creek|Canal|Region|Sea|Ocean|Gulf|Bay|Strait|Lake|Mountains|Mts\.|'
    r'Range|Massif|Hills|Highlands|Plateau|Islands|Archipelago|Valley|Desert|Peninsula|'
    r'Coast|Forest|Park|Reserve|Reservation|Refuge|Marshes|Swamp|Basin|Delta|Plain|Plains|'
    r'Glacier|Reef|Cape|Ridge|Canyon|Alps|Carpathian|Riviera|Harbor|Harbour|Fjord|'
    r'Province|State|District|Department|County|Oblast|Voivodeship|Governorate|Prefecture|'
    r'Territory|Kingdom|Empire|Land|Area|Road|Route|Trail|Wall|Pass|Country|Countries)\b')
HEADING_EXT_HE = re.compile(r'(נהר|נחל|ימת|ים |אגם|הרי|הר |רכס|מחוז|חבל|מדבר|איי |חצי האי|עמק|'
                            r'רמת|אגן|מפרץ|מיצר|אזור|יערות|יער|שמורת|פלך|אובלסט|מישור|חופ|דלתה|'
                            r'ארץ|ממלכת|אימפריה|אימפרית|מלכות|נפת|יבשת|ארצות)')


def feature_type(marc, kima, wd_entities, p31_labels):
    """('extended'|'point'|None, evidence string)"""
    ev = []
    verdict = None
    for q in wd_entities:
        e = wd_entities[q]
        if not e or e.get('missing'):
            continue
        labs = [p31_labels.get(p, {}).get('label_en') or p for p in e.get('p31', [])]
        txt = ' ; '.join(labs) + ' ; ' + (e.get('desc_en') or '')
        if EXTENDED_RE.search(txt) and not POINT_RE.search(txt):
            verdict = verdict or 'extended'; ev.append('%s P31=%s' % (q, ' / '.join(labs)))
        elif POINT_RE.search(txt):
            verdict = verdict or 'point'; ev.append('%s P31=%s' % (q, ' / '.join(labs)))
    heading = marc['primary'].get('lat') or ''
    heb = marc['primary'].get('heb') or ''
    base = heading.split(' (')[0]
    if verdict is None:
        if HEADING_EXT_RE.search(base) or HEADING_EXT_HE.search(heb.split(' (')[0]):
            verdict = 'extended'; ev.append('heading: ' + base)
        elif re.search(r'\(.*: *(Region|Province|State|District|Department|Parish)\)', heading):
            verdict = 'extended'; ev.append('heading qualifier')
    if kima and kima.get('LocationTypeId') == 2:
        ev.append('Kima LocationTypeId=2')
        if verdict is None:
            verdict = 'extended'
    return verdict, '; '.join(ev)


def extent_km(wd_entities):
    """Half-diagonal of the feature, from Wikidata area/length, if known."""
    best = None
    for e in wd_entities.values():
        if not e or e.get('missing'):
            continue
        cands = []
        if e.get('area_km2'):
            cands.append(math.sqrt(e['area_km2'] / math.pi) * 2.0)
        if e.get('length_km'):
            cands.append(e['length_km'] * 1.0)
        if cands:
            best = max(best or 0, max(cands))
    return best


# ------------------------------------------------------------------ name match

def norm(s):
    import unicodedata
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace('ʻ', '').replace('ʼ', '').replace("'", '')
    s = re.sub(r'\(.*?\)', ' ', s)
    s = re.sub(r'\b(river|the|of|de|di|del|la|le|el|lake|mount|mountains?|sea|island|islands)\b', ' ', s)
    s = re.sub(r'[^a-z֐-׿؀-ۿ]+', ' ', s)
    return ' '.join(s.split())


def name_matches(entity, marc, kima):
    if not entity or entity.get('missing'):
        return False
    names = set()
    for v in (marc['primary'].get('lat'), marc['primary'].get('heb'),
              (kima or {}).get('primary_rom_full'), (kima or {}).get('primary_heb_full')):
        if v:
            names.add(norm(v))
    for v in marc.get('variants', []):
        names.add(norm(v['name']))
    names.discard('')
    for lab in (entity.get('label_en'), entity.get('label_he')):
        if not lab:
            continue
        ln = norm(lab)
        if not ln:
            continue
        for n in names:
            toks_n, toks_l = set(n.split()), set(ln.split())
            if ln == n or (toks_l and toks_n and (toks_l <= toks_n or toks_n <= toks_l)):
                return True
            import difflib
            if difflib.SequenceMatcher(None, ln.replace(' ', ''), n.replace(' ', '')).ratio() >= 0.8:
                return True
    return False


# ------------------------------------------------------------------ classify

def dist(a, b):
    if not a or not b or None in a or None in b:
        return None
    return haversine(a, b)


def classify(case, marc, kima, wd, p31_labels, raw034):
    nli_q = marc['ids'].get('wikidata')
    nli_q_src = '024' if nli_q else None
    if not nli_q:
        nli_q = wd.get('search:P8189=%s' % case['recordId'])
        nli_q_src = 'P8189' if nli_q else None
    kima_q = (kima.get('WD') or '').strip() or None
    if kima_q and not kima_q.startswith('Q'):
        kima_q = None
    kima_q_src = 'WD' if kima_q else None
    gn = (kima.get('Geoname_ID') or '').strip()
    if not kima_q and gn:
        kima_q = wd.get('search:P1566=%s' % gn)
        kima_q_src = 'geonames:%s' % gn if kima_q else None
    ents = {q: wd.get(q) for q in (nli_q, kima_q) if q}
    for q, e in list(ents.items()):
        if e and e.get('redirect'):
            ents[q] = wd.get(e['redirect']) or e
    nli_c = marc.get('coords')
    kima_c = [kima['lat'], kima['lon']] if kima.get('lat') is not None else None
    d = case['movedKm']
    ftype, fev = feature_type(marc, kima, ents, p31_labels)
    ext = extent_km(ents)
    bb = bbox_extent_km(raw034)
    fixed_center, fix_desc = dropped_zero_fix(raw034)
    am_center, am_desc = antimeridian_fix(raw034)
    if bb > 25 and not fixed_center:
        fev += ('; ' if fev else '') + 'NLI 034 box half-diagonal %.0f km' % bb
        if ftype is None:
            ftype = 'extended'
        ext = max(ext or 0, bb)
    near = NEAR_KM if ftype != 'extended' else max(NEAR_KM, ext or 0)

    r = {'nliWd': nli_q, 'kimaWd': kima_q, 'sameWd': bool(nli_q and nli_q == kima_q),
         'nliWdSrc': nli_q_src, 'kimaWdSrc': kima_q_src,
         'featureType': ftype, 'featureEvidence': fev, 'extentKm': round(ext, 1) if ext else None,
         'nliWdCoord': None, 'kimaWdCoord': None,
         'dNliWd_Nli': None, 'dNliWd_Kima': None, 'dKimaWd_Kima': None, 'dKimaWd_Nli': None,
         'nliWdLabel': None, 'kimaWdLabel': None, 'nliWdNameOk': None, 'kimaWdNameOk': None,
         'fixedNliCoords': fixed_center, 'fix034': fix_desc, 'bboxHalfDiagKm': round(bb, 1)}
    ne = ents.get(nli_q) if nli_q else None
    ke = ents.get(kima_q) if kima_q else None
    if ne and not ne.get('missing'):
        r['nliWdCoord'] = ne['coord']; r['nliWdLabel'] = ne['label_en'] or ne['label_he']
        r['dNliWd_Nli'] = dist(ne['coord'], nli_c); r['dNliWd_Kima'] = dist(ne['coord'], kima_c)
        r['nliWdNameOk'] = name_matches(ne, marc, kima)
    if ke and not ke.get('missing'):
        r['kimaWdCoord'] = ke['coord']; r['kimaWdLabel'] = ke['label_en'] or ke['label_he']
        r['dKimaWd_Kima'] = dist(ke['coord'], kima_c); r['dKimaWd_Nli'] = dist(ke['coord'], nli_c)
        r['kimaWdNameOk'] = name_matches(ke, marc, kima)

    def le(x, t):
        return x is not None and x <= t

    # 0a. box crosses the antimeridian: the runner's centre is meaningless
    if am_center:
        dk = dist(am_center, kima_c)
        return r | {'bucket': 'nli-034-antimeridian', 'action': 'runner-bug', 'confidence': 'high',
                    'note': '034 box crosses 180° (%s); proper centre %s is %s km from Kima' % (am_desc, am_center, dk)}

    # 0. NLI 034 with a dropped leading zero in one fraction
    if fixed_center:
        dk = dist(fixed_center, kima_c)
        if le(dk, NEAR_KM):
            return r | {'bucket': 'nli-034-dropped-zero', 'action': 'keep-existing+report', 'confidence': 'high',
                        'note': 'NLI 034 fraction lost a leading 0 (%s); corrected centre is %.1f km from Kima' % (fix_desc, dk)}
        r['note034'] = 'possible dropped zero (%s) but corrected centre is %s km from Kima' % (fix_desc, dk)

    # 1. extended feature: both points plausibly on the feature
    if ftype == 'extended':
        if ext is not None and d <= max(ext * 1.2, 50):
            return r | {'bucket': 'extended-feature', 'action': 'apply-new', 'confidence': 'high',
                        'note': 'two points on one %s (extent ~%.0f km)' % (fev.split(';')[0] or 'feature', ext)}
        if ext is None and d <= 150:
            return r | {'bucket': 'extended-feature', 'action': 'apply-new', 'confidence': 'medium',
                        'note': 'two points on one %s (extent unknown)' % (fev.split(';')[0] or 'feature')}
        # extended but the move is far beyond the feature's size → fall through to Wikidata
        r['featureEvidence'] += '; move %.0f km exceeds extent' % d

    # 2. same Wikidata id on both sides → Wikidata coordinates arbitrate
    if r['sameWd'] and r['nliWdCoord']:
        a, b = r['dNliWd_Nli'], r['dNliWd_Kima']
        if le(a, near) and not le(b, near):
            return r | {'bucket': 'kima-coords-wrong', 'action': 'apply-new', 'confidence': 'high',
                        'note': 'Wikidata %s is %.0f km from NLI, %.0f km from Kima' % (nli_q, a, b)}
        if le(b, near) and not le(a, near):
            return r | {'bucket': 'nli-coords-wrong', 'action': 'keep-existing+report', 'confidence': 'high',
                        'note': 'Wikidata %s is %.0f km from Kima, %.0f km from NLI' % (nli_q, b, a)}
        if le(a, near) and le(b, near):
            return r | {'bucket': 'extended-feature', 'action': 'apply-new', 'confidence': 'medium',
                        'note': 'Wikidata within %.0f km of both points' % near}
        return r | {'bucket': 'wd-disagrees', 'action': 'research', 'confidence': 'low',
                    'note': 'Wikidata %s is %.0f km from NLI and %.0f km from Kima' % (nli_q, a or -1, b or -1)}

    # 3. different Wikidata ids
    if nli_q and kima_q and not r['sameWd']:
        n_ok, k_ok = r['nliWdNameOk'], r['kimaWdNameOk']
        n_here = le(r['dNliWd_Nli'], near); k_here = le(r['dKimaWd_Kima'], near)
        if n_ok and not k_ok:
            return r | {'bucket': 'kima-geonames-wrong' if kima_q_src.startswith('geonames') else 'kima-wd-wrong',
                        'action': 'apply-new', 'confidence': 'high' if n_here else 'medium',
                        'note': 'Kima %s -> %s = "%s" does not match the name; NLI WD %s = "%s"'
                                % (kima_q_src, kima_q, r['kimaWdLabel'], nli_q, r['nliWdLabel'])}
        if k_ok and not n_ok:
            return r | {'bucket': 'nli-wd-wrong', 'action': 'keep-existing+report', 'confidence': 'high' if k_here else 'medium',
                        'note': 'NLI WD %s = "%s" does not match the name; Kima WD %s = "%s"'
                                % (nli_q, r['nliWdLabel'], kima_q, r['kimaWdLabel'])}
        if n_ok and k_ok:
            if n_here and k_here and d >= 500:
                return r | {'bucket': 'homonym', 'action': 'apply-new', 'confidence': 'medium',
                            'note': 'Kima linked to a same-named entity elsewhere: Kima %s "%s" is %.0f km from '
                                    'NLI\'s self-consistent %s "%s"' % (kima_q, r['kimaWdLabel'], d, nli_q, r['nliWdLabel'])}
            return r | {'bucket': 'homonym', 'action': 'research', 'confidence': 'medium',
                        'note': 'two same-named entities: NLI %s "%s" vs Kima %s "%s"'
                                % (nli_q, r['nliWdLabel'], kima_q, r['kimaWdLabel'])}
        return r | {'bucket': 'wd-disagrees', 'action': 'research', 'confidence': 'low',
                    'note': 'neither WD label matches: NLI %s "%s", Kima %s "%s"'
                            % (nli_q, r['nliWdLabel'], kima_q, r['kimaWdLabel'])}

    # 4. only one side has a Wikidata id
    if nli_q and r['nliWdCoord']:
        a, b = r['dNliWd_Nli'], r['dNliWd_Kima']
        if not r['nliWdNameOk']:
            return r | {'bucket': 'nli-wd-wrong', 'action': 'research', 'confidence': 'medium',
                        'note': 'NLI WD %s = "%s" does not match the name' % (nli_q, r['nliWdLabel'])}
        if le(a, near) and not le(b, near):
            return r | {'bucket': 'kima-coords-wrong', 'action': 'apply-new', 'confidence': 'high',
                        'note': 'Wikidata %s (NLI only) is %.0f km from NLI, %.0f km from Kima' % (nli_q, a, b)}
        if le(b, near) and not le(a, near):
            return r | {'bucket': 'nli-coords-wrong', 'action': 'keep-existing+report', 'confidence': 'medium',
                        'note': 'Wikidata %s (NLI only) is %.0f km from Kima, %.0f km from NLI' % (nli_q, b, a)}
        return r | {'bucket': 'wd-disagrees', 'action': 'research', 'confidence': 'low',
                    'note': 'Wikidata %s near neither (%.0f / %.0f km)' % (nli_q, a or -1, b or -1)}
    if kima_q and r['kimaWdCoord']:
        a, b = r['dKimaWd_Kima'], r['dKimaWd_Nli']
        if not r['kimaWdNameOk']:
            return r | {'bucket': 'kima-geonames-wrong' if kima_q_src.startswith('geonames') else 'kima-wd-wrong',
                        'action': 'research', 'confidence': 'medium',
                        'note': 'Kima %s -> %s = "%s" does not match the name' % (kima_q_src, kima_q, r['kimaWdLabel'])}
        if le(b, near) and not le(a, near):
            return r | {'bucket': 'kima-coords-wrong', 'action': 'apply-new', 'confidence': 'medium',
                        'note': 'Kima\'s own WD %s is %.0f km from NLI, %.0f km from Kima' % (kima_q, b, a)}
        if le(a, near) and not le(b, near):
            if d >= 500 and '(' in (marc['primary'].get('lat') or ''):
                return r | {'bucket': 'homonym', 'action': 'apply-new', 'confidence': 'medium',
                            'note': 'Kima %s -> %s "%s" is a same-named place %.0f km from the NLI point; '
                                    'NLI heading qualifier disambiguates' % (kima_q_src, kima_q, r['kimaWdLabel'], d)}
            return r | {'bucket': 'nli-coords-wrong', 'action': 'keep-existing+report', 'confidence': 'medium',
                        'note': 'Kima %s -> %s (Kima only) is %.0f km from Kima, %.0f km from NLI' % (kima_q_src, kima_q, a, b)}
        return r | {'bucket': 'wd-disagrees', 'action': 'research', 'confidence': 'low',
                    'note': 'Kima WD %s near neither (%.0f / %.0f km)' % (kima_q, a or -1, b or -1)}

    return r | {'bucket': 'no-wd', 'action': 'research', 'confidence': 'low',
                'note': 'no Wikidata id on either side' + (' (%s)' % fev if fev else '')}


# ------------------------------------------------------------------ main

def main():
    cases = [c for c in DATA.cases if c['category'] in ('location-move', 'multi-034')]
    wd = load_cache()
    qids = []
    kimas = {}
    for c in cases:
        marc = DATA.marc[c['recordId']]
        k = DATA.kima_place_by_id(c['kimaId']) or {}
        kimas[c['recordId']] = k
        qids.append(marc['ids'].get('wikidata'))
        kq = (k.get('WD') or '').strip()
        if kq.startswith('Q'):
            qids.append(kq)
    wd_fetch(qids, wd)
    # follow redirects + fetch P31 class labels
    wd_fetch([e['redirect'] for e in wd.values() if isinstance(e, dict) and e.get('redirect')], wd)
    p31 = [p for e in wd.values() if isinstance(e, dict) and not e.get('missing') for p in e.get('p31', [])]
    wd_fetch(p31, wd)
    raw = load_raw_034([c['recordId'] for c in cases])
    extra = []
    for c in cases:
        marc = DATA.marc[c['recordId']]; k = kimas[c['recordId']]
        if not marc['ids'].get('wikidata'):
            extra.append(wd_search_by_statement('P8189', c['recordId'], wd))
        kq = (k.get('WD') or '').strip(); gn = (k.get('Geoname_ID') or '').strip()
        if not kq.startswith('Q') and gn:
            extra.append(wd_search_by_statement('P1566', gn, wd))
    wd_fetch([q for q in extra if q], wd)
    wd_fetch([e['redirect'] for e in wd.values() if isinstance(e, dict) and e.get('redirect')], wd)
    wd_fetch([p for e in wd.values() if isinstance(e, dict) and not e.get('missing') for p in e.get('p31', [])], wd)

    rows = []
    for c in cases:
        marc = DATA.marc[c['recordId']]
        k = kimas[c['recordId']]
        res = classify(c, marc, k, wd, wd, raw.get(c['recordId'], []))
        dec = DATA.decisions.get(c['recordId']) or {}
        rows.append({
            'recordId': c['recordId'], 'period': c['period'], 'category': c['category'],
            'bucket': res['bucket'], 'action': res['action'], 'confidence': res['confidence'],
            'note': res['note'],
            'heading': marc['primary'].get('lat'), 'headingHeb': marc['primary'].get('heb'),
            'kimaId': c['kimaId'], 'kimaRom': k.get('primary_rom_full'), 'kimaHeb': k.get('primary_heb_full'),
            'movedKm': c['movedKm'],
            'nliCoords': marc.get('coords'), 'kimaCoords': [k.get('lat'), k.get('lon')] if k.get('lat') is not None else None,
            'n034': len(marc.get('coordsList') or []),
            'src034': '|'.join(x['source'] for x in marc.get('coordsList') or []),
            'decision': dec.get('decision'), 'decisionNote': dec.get('note'),
            **{kk: res[kk] for kk in ('nliWd', 'kimaWd', 'sameWd', 'featureType', 'featureEvidence', 'extentKm',
                                      'nliWdLabel', 'kimaWdLabel', 'nliWdCoord', 'kimaWdCoord',
                                      'dNliWd_Nli', 'dNliWd_Kima', 'dKimaWd_Kima', 'dKimaWd_Nli',
                                      'nliWdNameOk', 'kimaWdNameOk', 'nliWdSrc', 'kimaWdSrc',
                                      'fixedNliCoords', 'fix034', 'bboxHalfDiagKm')},
        })
    json.dump(rows, open(os.path.join(APP, 'move-analysis.json'), 'w'), ensure_ascii=False, indent=1)
    with open(os.path.join(APP, 'move-analysis.tsv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter='\t')
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                        for k, v in r.items()})
    import collections
    print(collections.Counter((r['bucket'], r['action'], r['confidence']) for r in rows).most_common())
    print('\n-- against the %d human decisions --' % sum(1 for r in rows if r['decision']))
    xt = collections.Counter((r['decision'], r['bucket']) for r in rows if r['decision'])
    for (d, b), n in sorted(xt.items()):
        print('%3d  %-18s -> %s' % (n, d, b))


if __name__ == '__main__':
    main()
