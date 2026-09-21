#!/usr/bin/env python3
"""Build the first NLI report — everything that is *not* a Hebrew-naming ask.

Reads the review decisions through the running app's full export (so the row
shape stays the single one defined by server.export_csv), drops the
Hebrew-naming queues, groups what remains by *the error the library has to
fix* rather than by our internal queue code, and writes:

    docs/index.html              the tabbed report (GitHub Pages)
    docs/data.json               the rows the page renders
    docs/nli-report-<date>.xlsx  one sheet per tab

The Hebrew-naming queues (A2 A4 A5 A6 A8 A11, and rename-suggestion anywhere)
are deliberately excluded: they are one argument about Hebrew heading form and
tier vocabulary, and they go in a second report of their own.

Run: python3 app/build_nli_report.py            (app server must be running)
     python3 app/build_nli_report.py --offline  (use a cached full.csv)
"""
import csv
import io
import json
import math
import os
import sys
import datetime
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(APP_DIR)
DOCS = os.path.join(REPO, 'docs')
APP_URL = os.environ.get('APP_URL', 'http://localhost:8765')

# Decisions that are by nature a report to the library. Mirrors
# server.NLI_DECISIONS — kept in sync by hand, deliberately: this script must
# still run when the app is not importable.
NLI_DECISIONS = {'keep-existing', 'nli-duplicate', 'data-problem', 'rename-suggestion'}

# Queues that are the Hebrew-naming argument. Excluded from report #1.
HEBREW_NAMING_TASKS = {'A2', 'A4', 'A5', 'A6', 'A8', 'A11'}

# B5 is *our* bug, not NLI's: (d+e)/2 on a box that crosses the antimeridian
# gives -56 instead of 124E. issue-categories.md calls it "באג ברצה". A row
# whose only finding is that must not be sent to the library, even though the
# review recorded `keep-existing` on it.
OUR_BUG_TASKS = {'B5'}


# ---------------------------------------------------------------- tabs
# One tab per action the library has to take. `task` lists the review queues
# that feed it; `why`/`ask`/`how` are the side-panel text. Order is the tab
# order, and it is deliberate: the two big mechanical piles first, because they
# are the ones NLI can fix in bulk without adjudicating anything.

TABS = [
    dict(
        key='dropped-zero',
        tasks={'B4'},
        title='אפס מוביל שנשמט משדה 034',
        short='אפס שנשמט',
        kind='mechanical',
        why='בשדה 034 של הרשומות האלה אחד מתתי־השדות של הקואורדינטות קצר בספרה אחת: '
            'האפס המוביל נשמט בכתיבה. הערך <code>E0120000</code> נכתב <code>E120000</code>, '
            'והמנתח קורא אותו כ־12° במקום 1.2°, או מזיז את הנקודה בעשרות ומאות קילומטרים. '
            'התיבה שנוצרת אינה מקיפה את המקום, ומרכזה נופל במקום אחר לגמרי — '
            'לעתים בים, לעתים במדינה שכנה.',
        ask='לתקן את ערכי 034 לפי העמודה "הערך המתוקן". זה תיקון מכני: '
            'הערך הנכון נגזר מן הערך הקיים בהוספת האפס החסר, ואינו דורש הכרעה '
            'עורכית באף אחד מן המקרים.',
        how='הגלאי יושב ב־<code>app/classify_moves.py</code> ומזהה את התקלה לפי אורך '
            'תת־השדה ביחס לצורות התקינות של MARC 034. אחרי התיקון מרכז התיבה חוזר '
            'לשבת על המקום, ובבדיקה שלנו הוא חוזר להתלכד עם הנקודה שכימה מחזיקה.',
        evidence='כל שורה: הערך הפגום כפי שהוא ברשומה, הערך המתוקן, והמרחק '
                 'שהתיקון סוגר.',
    ),
    dict(
        key='nli-coords',
        tasks={'B3', 'B9', 'B2', 'B7', 'B6', 'B8'},
        title='הקואורדינטות ברשומה מצביעות על מקום אחר',
        short='קואורדינטות שגויות',
        kind='judgment',
        why='בשורות האלה שדה 034 תקין מבחינה צורנית, אבל הנקודה שהוא מתאר אינה '
            'המקום שבכותרת. בחלק מן המקרים נבחר הומונים שגוי — יישוב בעל אותו שם '
            'ביבשת אחרת (Phoenicia שבניו־יורק במקום פיניקיה שבלבנון; Linden שבניו־ג׳רזי '
            'במקום לינדן שבגיאנה). באחרים הנקודה פשוט שגויה, בלי שנוכל להצביע על מקור '
            'הטעות.',
        ask='לבדוק את הקואורדינטות בכל שורה מול הכותרת, ולתקן את 034. '
            'העמודות "נקודת ויקינתונים" ו"מרחק" מראות מה לדעתנו הנקודה הנכונה '
            'ועד כמה הרשומה רחוקה ממנה.',
        how='ההשוואה נעשתה בין שלוש נקודות: זו שברשומת NLI, זו שכימה מחזיקה, '
            'וזו של ישות הוויקינתונים שהרשומה עצמה מפנה אליה בשדה 024. כשכימה '
            'וויקינתונים מסכימות זו עם זו ונקודת NLI לבדה — ייחסנו את הטעות לרשומה. '
            'הסיווג האוטומטי עבר אחר כך סקירה ידנית, שורה שורה.',
        evidence='עמודת "ביטחון" היא ביטחון הסיווג האוטומטי; כל השורות כאן עברו '
                 'גם אישור ידני.',
    ),
    dict(
        key='malformed-034',
        tasks={'B12'},
        title='שדה 034 שאינו ניתן לניתוח',
        short='034 פגום',
        kind='mechanical',
        why='שדה 034 שאינו עומד באף אחת מן הצורות שMARC מתיר — לא מעלות עשרוניות '
            'ולא <code>hdddmmss</code> — ולכן אין ממנו קואורדינטה כלל. הרשומה נראית '
            'כאילו יש בה מיקום, אבל בפועל אין.',
        ask='לתקן את הערכים לצורה תקינה. הדוח המלא של התקלה הזאת נמסר בנפרד '
            '(957 רשומות, <code>nli-malformed-coordinates-report_20260822.csv</code>) — '
            'כאן מופיעות רק השורות שעלו גם בסקירה הזאת.',
        how='מנתח הקואורדינטות שלנו מקבל את שתי הצורות התקינות ומרפד DMS קצר. '
            'מה שנשאר כאן לא נותח גם אחרי הריפוד.',
        evidence='ראו את הדוח הנפרד לפירוט מלא לפי סוג התקלה.',
    ),
    dict(
        key='wikidata-id',
        tasks={'B10'},
        title='מזהה ויקינתונים בשדה 024 מצביע על ישות שגויה',
        short='מזהה ויקינתונים',
        kind='judgment',
        why='הרשומה מפנה בשדה 024 לישות ויקינתונים שאינה המקום שבכותרת — ישות '
            'בעלת שם דומה, או מקום אחר לגמרי. זו תקלה חמורה יותר מקואורדינטה שגויה, '
            'משום שהיא מתפשטת: כל מי שמסתמך על המזהה הזה כדי לקשר את הרשומה למקורות '
            'חיצוניים יורש את הטעות.',
        ask='לתקן את המזהה בשדה 024. עמודת "המזהה הנכון" נושאת את הישות שלדעתנו '
            'הכותרת מתארת.',
        how='לכל שורה הוצאנו את הישות שהמזהה מפנה אליה, את תווית השם שלה ואת '
            'הקואורדינטות שלה, והשווינו לכותרת הרשומה ולנקודה שבה. כשהתווית והנקודה '
            'שתיהן אינן מתאימות — המזהה שגוי.',
        evidence='עמודות "תווית הישות" ו"נקודת הישות" מראות מה המזהה הקיים מתאר.',
    ),
    dict(
        key='duplicate-records',
        tasks={'A10', 'A13'},
        title='שתי רשומות רשות לאותו מקום',
        short='כפילות ברשומות',
        kind='judgment',
        why='שתי רשומות רשות נפרדות ב־NLI מתארות מקום אחד. בחלק מן המקרים העדות '
            'היא מזהה ויקינתונים זהה בשתיהן; באחרים אחת הכותרות היא שם היסטורי של '
            'האחרת (טולבוחין ודובריץ׳). זו אינה שאלה של איות עברי אלא של זהות '
            'הרשומה: הרשות כפולה.',
        ask='לבדוק את הזוגות ולמזג את הרשומות, או להסביר מה מבדיל ביניהן אם '
            'ההפרדה מכוונת.',
        how='הזוגות אותרו לפי מזהה ויקינתונים משותף ולפי הודעות הכפילות של '
            'ההרצה השבועית, ואומתו אחת אחת מול MARC מ־Alma OAI.',
        evidence='כל שורה נושאת את שני המזהים ואת שתי הכותרות.',
    ),
    dict(
        key='other',
        tasks={'D5'},
        title='תקלות בודדות',
        short='בודדות',
        kind='judgment',
        why='מקרים שאינם מצטרפים לתבנית — תקלה בשם הערבי, סוגר שלא נסגר בכותרת, '
            'סוגריים שנכנסו להפניה. כל שורה עומדת בזכות עצמה, וההערה שלצדה אומרת '
            'מה נמצא.',
        ask='לקרוא את ההערה בכל שורה ולתקן בהתאם.',
        how='אלה מקרים שעלו במהלך סקירת קטגוריות אחרות. חלקם הוכרעו בהרצה '
            'מוקדמת יותר, והנתונים שלהם נשלפו מחדש מ־Alma OAI לצורך הדוח הזה.',
        evidence='עמודת "הערה" היא הממצא עצמו.',
    ),
]

TAB_OF_TASK = {t: tab['key'] for tab in TABS for t in tab['tasks']}

# `Z` means only "decided in an earlier run, no longer in any current report" —
# it says nothing about what was found. Route those by the decision instead:
# a coordinate verdict is a coordinate error, everything else is a one-off.
Z_TAB_OF_DECISION = {'keep-existing': 'nli-coords', 'nli-duplicate': 'duplicate-records',
                     'data-problem': 'other'}


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


def fetch_full():
    cache = os.path.join(APP_DIR, '.cache', 'full-export.csv')
    if '--offline' in sys.argv and os.path.exists(cache):
        return open(cache, encoding='utf-8-sig').read()
    body = urllib.request.urlopen(APP_URL + '/export.csv', timeout=120).read().decode('utf-8-sig')
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    open(cache, 'w').write(body)
    return body


def split_ll(s):
    if not s or ',' not in s:
        return None
    try:
        a, b = s.split(',')
        return [float(a), float(b)]
    except ValueError:
        return None


def recovered():
    """Heading + coordinates re-fetched from OAI for the stale Z rows, whose
    export line carries only a record id. Written by fetch_stale_marc()."""
    p = os.path.join(APP_DIR, '.cache', 'stale-recovered.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def build_rows():
    rows = list(csv.DictReader(io.StringIO(fetch_full())))
    rec = recovered()
    out = []
    skipped_heb = skipped_ours = 0
    for r in rows:
        if not (r['for_nli'] == 'yes' or r['decision'] in NLI_DECISIONS):
            continue
        # The Hebrew-naming argument goes in report #2 — both the queues that are
        # about heading form, and any rename-suggestion wherever it was recorded.
        if r['task'] in HEBREW_NAMING_TASKS or r['decision'] == 'rename-suggestion':
            skipped_heb += 1
            continue
        if r['task'] in OUR_BUG_TASKS:
            skipped_ours += 1
            continue
        tab = (Z_TAB_OF_DECISION.get(r['decision']) if r['task'] == 'Z'
               else TAB_OF_TASK.get(r['task']))
        if not tab:
            print('  ! no tab for task %s (%s) — skipped' % (r['task'], r['new_id']))
            continue

        heb, rom = r['new_heb'], r['new_rom']
        nli_ll = split_ll(r['new_lat_lon'])
        kima_ll = split_ll(r['existing_lat_lon'])
        dist = r['distance_km']
        extra = rec.get(r['new_id'])
        if extra and not heb:
            # stale row: fill from the OAI re-fetch
            heb = extra.get('heb') or ''
            rom = extra.get('rom') or ''
            nli_ll = nli_ll or extra.get('nliLatLon')
            kima_ll = kima_ll or extra.get('kimaLatLon')
        if not dist and nli_ll and kima_ll:
            dist = haversine(nli_ll, kima_ll)

        out.append({
            'tab': tab,
            'task': r['task'],
            'id': r['new_id'],
            'url': r['new_url'],
            'heb': heb,
            'rom': rom,
            'ara': r['new_ara'],
            'nliLatLon': nli_ll,
            'kimaLatLon': kima_ll,
            'dist': float(dist) if dist not in ('', None) else None,
            'nliWd': r['new_wikidata'],
            'kimaWd': r['existing_wikidata'],
            'correctWd': r['correct_wd'],
            'manualLatLon': split_ll('%s,%s' % (r['manual_lat'], r['manual_lon']))
                            if r['manual_lat'] else None,
            'viaf': r['new_viaf'],
            'lccn': r['new_lccn'],
            'geonames': r['existing_geonames'],
            'kimaId': r['kima_place_id'],
            'kimaHeb': r['existing_heb'],
            'kimaRom': r['existing_rom'],
            'otherNliId': r['existing_id'],
            'otherNliUrl': r['existing_url'],
            'bucket': r['classifier_bucket'],
            'bucketWhy': r['classifier_reason'],
            'confidence': r['classifier_confidence'],
            'fix034': (extra or {}).get('fix034') or '',
            'note': r['note'],
            'decision': r['decision'],
            'period': r['period'],
            'recovered': bool(extra and extra.get('heb')),
        })
    print('rows: %d  (Hebrew-naming held back for report #2: %d; our own bugs dropped: %d)'
          % (len(out), skipped_heb, skipped_ours))
    return out


# ---------------------------------------------------------------- fix034
def attach_fix034(rows):
    """The corrected 034 value for the dropped-zero pile, from the classifier."""
    p = os.path.join(APP_DIR, 'move-analysis.tsv')
    if not os.path.exists(p):
        return
    fix = {}
    with open(p) as fh:
        for row in csv.DictReader(fh, delimiter='\t'):
            if row.get('fix034'):
                fix[row['recordId']] = (row['fix034'], row.get('fixedNliCoords', ''))
    n = 0
    for r in rows:
        f = fix.get(r['id'])
        if f:
            # fixedNliCoords is a JSON list in the TSV, not a "lat,lon" pair
            try:
                fixed = json.loads(f[1]) if f[1] else None
            except ValueError:
                fixed = None
            r['fix034'], r['fixedLatLon'] = f[0], fixed
            n += 1
    print('fix034 values attached: %d' % n)



# ---------------------------------------------------------------- spreadsheet
# Column order per tab. Every id column is paired with a words column — the
# convention from the review app's exports: a report the library has to act on
# must never make a reader resolve an id by hand.
COLUMNS = {
    'dropped-zero': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('fix034', 'הערך הפגום ← הערך המתוקן'),
        ('nliLatLon', 'נקודת NLI (כפי שהיא)'), ('fixedLatLon', 'נקודת NLI לאחר התיקון'),
        ('kimaLatLon', 'נקודת כימה'), ('dist', 'מרחק (ק״מ)'),
        ('nliWd', 'ויקינתונים ברשומה'), ('url', 'קישור לרשומה'),
    ],
    'nli-coords': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('nliLatLon', 'נקודת NLI'), ('kimaLatLon', 'הנקודה שלדעתנו נכונה'),
        ('dist', 'מרחק (ק״מ)'), ('bucketWhy', 'סוג הממצא'), ('confidence', 'ביטחון'),
        ('nliWd', 'ויקינתונים ברשומה'), ('correctWd', 'מזהה ויקינתונים נכון'),
        ('geonames', 'GeoNames'), ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
    ],
    'malformed-034': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
    ],
    'wikidata-id': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('nliWd', 'המזהה שברשומה'), ('correctWd', 'המזהה הנכון'),
        ('nliLatLon', 'נקודת NLI'), ('kimaLatLon', 'נקודת כימה'), ('dist', 'מרחק (ק״מ)'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
    ],
    'duplicate-records': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('otherNliId', 'מזהה הרשומה השנייה'), ('kimaHeb', 'כותרת הרשומה השנייה'),
        ('nliWd', 'ויקינתונים משותף'), ('dist', 'מרחק בין הנקודות (ק״מ)'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'), ('otherNliUrl', 'קישור לשנייה'),
    ],
    'other': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('note', 'הערת הסוקר'), ('nliLatLon', 'נקודת NLI'), ('kimaLatLon', 'נקודת כימה'),
        ('url', 'קישור לרשומה'),
    ],
}


def cell(r, key):
    v = r.get(key)
    if v is None or v == '':
        return ''
    if key.endswith('LatLon') and isinstance(v, list):
        return '%.5f, %.5f' % (v[0], v[1])
    return v


def write_xlsx(payload, path):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        print('  ! openpyxl not installed — skipping the .xlsx')
        return None
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill('solid', fgColor='1F3A5F')
    head_font = Font(color='FFFFFF', bold=True, size=11)
    for tab in payload['tabs']:
        cols = COLUMNS[tab['key']]
        ws = wb.create_sheet(tab['short'][:31])
        ws.sheet_view.rightToLeft = True
        ws.append([label for _, label in cols])
        for c in range(1, len(cols) + 1):
            cl = ws.cell(row=1, column=c)
            cl.fill, cl.font = head_fill, head_font
            cl.alignment = Alignment(vertical='center', wrap_text=True)
        for r in [x for x in payload['rows'] if x['tab'] == tab['key']]:
            ws.append([cell(r, k) for k, _ in cols])
        widths = {'heb': 30, 'rom': 30, 'id': 20, 'fix034': 46, 'note': 52,
                  'url': 34, 'otherNliUrl': 34, 'bucketWhy': 34, 'kimaHeb': 28}
        for i, (k, _) in enumerate(cols, start=1):
            ws.column_dimensions[get_column_letter(i)].width = widths.get(k, 16)
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(cols)), ws.max_row)
    # a first sheet that says what the workbook is
    intro = wb.create_sheet('אודות', 0)
    intro.sheet_view.rightToLeft = True
    intro['A1'] = 'דוח שגיאות ברשומות רשות של מקומות — אוסף כימה'
    intro['A1'].font = Font(bold=True, size=14)
    lines = [
        '',
        'נוצר: %s' % payload['generated'],
        'סך השורות: %d' % len(payload['rows']),
        '',
        'הדוח הזה עוסק רק בשגיאות שאינן שאלות של שמות בעברית.',
        'שאלות הכותרת העברית והדרגות המנהליות נמסרות בדוח נפרד.',
        '',
        'גיליון לכל סוג תיקון:',
    ]
    for t in payload['tabs']:
        lines.append('    %s — %d שורות — %s' % (t['short'], t['n'], t['title']))
    lines += ['',
              'כל שורה עברה סקירה ידנית. עמודת "הערת הסוקר" נושאת את הממצא',
              'כפי שנרשם בעת הסקירה.']
    for i, line in enumerate(lines, start=2):
        intro.cell(row=i, column=1, value=line)
    intro.column_dimensions['A'].width = 95
    wb.save(path)
    return path


def main():
    os.makedirs(DOCS, exist_ok=True)
    rows = build_rows()
    attach_fix034(rows)
    today = datetime.date.today().isoformat()
    counts = {}
    for r in rows:
        counts[r['tab']] = counts.get(r['tab'], 0) + 1
    payload = {
        'generated': today,
        'tabs': [{k: t[k] for k in ('key', 'title', 'short', 'kind', 'why', 'ask', 'how', 'evidence')}
                 | {'n': counts.get(t['key'], 0), 'tasks': sorted(t['tasks'])}
                 for t in TABS if counts.get(t['key'])],
        'rows': rows,
    }
    json.dump(payload, open(os.path.join(DOCS, 'data.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('wrote docs/data.json — %d rows in %d tabs' % (len(rows), len(payload['tabs'])))
    xl = write_xlsx(payload, os.path.join(DOCS, 'nli-report-%s.xlsx' % today.replace('-', '')))
    if xl:
        payload['xlsx'] = os.path.basename(xl)
        json.dump(payload, open(os.path.join(DOCS, 'data.json'), 'w'),
                  ensure_ascii=False, indent=1)
        print('wrote %s' % os.path.basename(xl))
    for t in payload['tabs']:
        print('  %-20s %4d  %s' % (t['key'], t['n'], t['title']))
    return payload


if __name__ == '__main__':
    main()
