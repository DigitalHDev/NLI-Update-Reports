#!/usr/bin/env python3
"""Build the first NLI report to the library.

Reads the review decisions through the running app's full export (so the row
shape stays the single one defined by server.export_csv), drops the
Hebrew-naming queues, groups what remains by *the error the library has to
fix* rather than by our internal queue code, and writes:

    docs/index.html              the tabbed report (GitHub Pages)
    docs/data.json               the rows the page renders
    docs/nli-report-<date>.xlsx  one sheet per tab

Structural errors (coordinates, external ids, duplicate records) plus the
individual Hebrew headings that need a correction or a disambiguation — the
latter added 2026-09-22 at Sinai's request, with a concrete proposal for each
side. What still goes to report #2 is the *tier vocabulary*: one cross-cutting
argument about qualifier form, not a list of per-record fixes.

Editing the report (option A, chosen 2026-09-22): the spreadsheet in Drive is
the source of truth for the *report*. Edit it there, then rebuild from it — the
page is regenerated to match. Coordinates are read-only on that path (the sheet
prints 5 decimals; Kima holds ~11) and a row removed from the sheet is kept in
data.json flagged `removed`, hidden from the page and listed on every build, so
a deletion can never silently drop a finding.

Run: python3 app/build_nli_report.py                  (from decisions.json)
     python3 app/build_nli_report.py --offline        (cached full.csv)
     python3 app/build_nli_report.py --from-xlsx F    (from an edited workbook)
     python3 app/build_nli_report.py --from-drive     (download it first)
"""
import csv
import io
import json
import math
import os
import re
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

# ...except the ones the library must act on record by record, which Sinai
# asked to include here (2026-09-22). These are not the tier-vocabulary
# argument — they are individual headings where one Hebrew string is doing the
# work of two places. The wider question of qualifier form still goes in #2.
HEBREW_ROWS_INCLUDED = {
    # two places, one Hebrew heading — a qualifier is needed on each side
    '987011060395805171',   # הוכשטטן   Hochstätten / Hochstetten
    '987007494092005171',   # אנינגן    Ehningen / Eningen unter Achalm
    '987007545176905171',   # צ'רנייב   Cherniïv / Chernihiv
    '987007494367505171',   # לובן      Lüben / Lübben
    '987007562214205171',   # קאבה      Hajdú-Bihar / Pest
    '987007559599105171',   # מריון     Marion Station / Marion
    '987010489292905171',   # פוליני    Jura / Meurthe-et-Moselle
    '987011252608705171',   # אופנהיים  Bavaria / Rheinland-Pfalz
    '987013405241405171',   # פלאנס     two live NLI records, one village
    # the heading is wrong, not ambiguous
    '987007567653605171',   # אוסטרוויק Osterwick vs Osterwieck
    '987007469750605171',   # טרבזון    Hebrew name of a different record
    '987007496754305171',   # המזרח הרחוק הרוסי
}

# Spelling corrections to NLI's Hebrew heading that are not about a collision
# at all. Two sat in the R research queue — recorded, marked "report to the
# library" in the note, and then with nowhere to go (the open R-queue question
# in the 2026-08-28 hand-off). Sinai confirmed 2026-09-22 these belong here.
# ברוקין/בירקין was considered and dropped: בירקין is a legitimate form.
HEBREW_SPELLING_ROWS = {
    '987007559626405171',   # אינגולשטדט → איגולשטדט
    '987007284075505171',   # רנידוס → קנידוס (plus a stray parenthesis)
    '987007552593705171',   # שטרסבורג — a German Strasbourg distinct from the French
}

# Which of the three Hebrew tabs each admitted row belongs to. Explicit rather
# than derived: these twelve rows were classified one by one, and the queue code
# they carry (A8, A11, R, Z) does not distinguish a collision from a misspelling
# from a wrong attribution.
HEB_TAB_OF_ROW = {
    **{rid: 'heb-homonym' for rid in (
        '987011060395805171', '987007494092005171', '987007545176905171',
        '987007494367505171', '987007562214205171', '987007559599105171',
        '987010489292905171', '987011252608705171')},
    '987013405241405171': 'heb-identity',   # פלאנס — two live NLI records
    '987007567653605171': 'heb-identity',   # אוסטרוויק — merge
    '987007469750605171': 'heb-identity',   # טרבזון — name of another record
    '987007496754305171': 'heb-identity',   # המזרח הרחוק הרוסי
    '987007559626405171': 'heb-spelling',
    '987007284075505171': 'heb-spelling',
    '987007552593705171': 'heb-spelling',
}

# Spelling corrections stated plainly, so the library reads the ask in a column
# rather than digging it out of a free-text note.
SPELLING_FIX = {
    '987007559626405171': dict(was='אינגולשטדט (גרמניה)', now='איגולשטדט (גרמניה)',
                               why='האיות העברי אינו תואם את Ingolstadt.'),
    '987007284075505171': dict(was='רנידוס (טורקיה : עיר קדומה)',
                               now='קנידוס (טורקיה : עיר קדומה)',
                               why='Cnidus — התעתיק המקובל הוא בקו״ף. כמו כן הסוגר '
                                   'הסופי חסר בכותרת, והרמיזות כוללות את הסוגריים '
                                   'שלא כבדרך כלל.'),
    '987007552593705171': dict(was='שטרסבורג (גרמניה)', now='',
                               why='אין כאן שגיאת איות אלא שאלת זהות: יש שטרסבורג '
                                   'גרמנית (Q565624) השונה מזו הצרפתית של היום. '
                                   'האם יש צורך לשמר את הזהות הזו? אם כן, מוטב '
                                   'להוסיף 1871-1918 לכותרת הראשית.'),
}

# Checks against Wikidata that contradict a suggestion recorded in the review.
# Raised as a flag on the row, never by silently rewriting Sinai's own words:
# the reviewer may know something the check does not.
SUGGEST_WARNING = {
    '987010489292905171':
        'לבדיקה: הרשומה הנכנסת היא Pulligny, ולפי ויקינתונים (Q1099419) היא '
        'במחוז מרת ומוזל — ואילו ההצעה מייחסת אותה ליורה. ייתכן ששני הצדדים '
        'הוחלפו. יש לאשר לפני שליחה.',
}

# Drafted disambiguation proposals for the rows where the review recorded the
# collision but no distinguishing name. Grounded on the administrative parent
# in Wikidata (P131), using ITS OWN Hebrew label where one exists rather than a
# transliteration of mine. Marked `draft` in the report so the library — and
# Sinai — can see these are proposals awaiting approval, not review verdicts.
NAME_DRAFTS = {
    '987011060395805171': dict(
        new='הוכשטטן (מחוז באד קרויצנאך, גרמניה)',
        existing='הוכשטטן (גרמניה)',
        why='שתי רשומות שונות: Hochstätten שבמחוז באד קרויצנאך, ו־Hochstetten '
            'באיות אחר. ההצעה מוסיפה את המחוז לרשומה הנכנסת; יש לאשר מהי הרשומה '
            'השנייה לפני שמציעים לה מבחין.'),
    '987007494092005171': dict(
        new='אנינגן (מחוז בבלינגן, גרמניה)',
        existing='אנינגן אונטר אכלם (מחוז רויטלינגן, גרמניה)',
        why='שני יישובים שונים במרחק 31 ק״מ: Ehningen שבמחוז בבלינגן (Q314758) '
            'ו־Eningen unter Achalm שבמחוז רויטלינגן (Q81423). שמות המחוזות '
            'לקוחים מתוויות ויקינתונים בעברית.'),
    '987007545176905171': dict(
        new="צ'רנייב (מחוז איוונו-פרנקיבסק, אוקראינה)",
        existing="צ'רניהיב (אוקראינה)",
        why='כאן לא די במבחין: המרחק 553 ק״מ, והרשומה השנייה היא צ׳רניהיב — '
            'בירת המחוז (Q157053), שהתעתיק העברי המקובל לה בוויקינתונים הוא '
            '"צ׳רניהיב" ולא "צ׳רנייב". כלומר אחת הכותרות שגויה ולא רק עמומה.'),
    '987007494367505171': dict(
        new='לובין (מחוז דולנוסלונסקיה, פולין)',
        existing='לובן (מחוז דאמה-שפרוואלד, גרמניה)',
        why='לפי הערת הסוקר, הרשומה הנכנסת היא Lubin שבפולין — השם העכשווי — '
            'ו־Lüben/Lueben הם וריאנטים היסטוריים שלה. הרשומה השנייה היא '
            'Lübben שבברנדנבורג (Q584815). שני מקומות שונים ב־170 ק״מ.'),
}

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
        evidence='עמודת "הנקודה שלדעתנו נכונה" היא הנקודה שכימה מחזיקה, אלא אם '
                 'הסוקר רשם נקודה משלו — במקרים שבהם גם נקודת כימה שגויה. '
                 'עמודת "מרחק" היא המרחק בין נקודת הרשומה לנקודה הזאת.',
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
        title='מזהה ויקינתונים בשדה 024',
        short='מזהה ויקינתונים',
        kind='judgment',
        why='שני מצבים, ועמודת "סוג הפנייה" מבדילה ביניהם. <b>מזהה שגוי:</b> הרשומה '
            'מפנה בשדה 024 לישות ויקינתונים שאינה המקום שבכותרת — ישות בעלת שם דומה, '
            'או מקום אחר לגמרי. זו תקלה חמורה יותר מקואורדינטה שגויה, משום שהיא '
            'מתפשטת: כל מי שמסתמך על המזהה הזה כדי לקשר את הרשומה למקורות חיצוניים '
            'יורש את הטעות. <b>מזהה מוצע:</b> אין ברשומה 024 כלל, ואיתרנו את הישות '
            'המתאימה — הצעה, לא דיווח על שגיאה.',
        ask='במקרים של מזהה שגוי — לתקן את שדה 024. במקרים של מזהה מוצע — לשקול '
            'להוסיף אותו. עמודת "המזהה הנכון / המוצע" נושאת את הישות שלדעתנו '
            'הכותרת מתארת.',
        how='לכל שורה הוצאנו את הישות שהמזהה מפנה אליה, את תווית השם שלה ואת '
            'הקואורדינטות שלה, והשווינו לכותרת הרשומה ולנקודה שבה. כשהתווית והנקודה '
            'שתיהן אינן מתאימות — המזהה שגוי. חלק מן השורות כאן התגלו תוך כדי בדיקת '
            'הקואורדינטות, ולכן יש בהן גם אי־התאמה במיקום; היא מופיעה בעמודת המרחק.',
        evidence='עמודת "סוג הפנייה" אומרת אם מדובר בתיקון או בהצעה, ועמודת '
            '"המזהה שברשומה" מראה מה קיים היום.',
    ),
    dict(
        key='heb-homonym',
        tasks={'A8', 'A11', 'Z'},
        title='כותרת עברית אחת לשני מקומות',
        short='כותרת לשני מקומות',
        kind='judgment',
        why='שתי רשומות רשות נפרדות — שני מקומות ממשיים ושונים — נושאות בדיוק את '
            'אותה כותרת בעברית, אף שהשם הלטיני מבדיל ביניהן. התעתיק לעברית מאבד את '
            'ההבחנה: Ehningen ו־Eningen unter Achalm נעשים שניהם "אנינגן (גרמניה)", '
            'Lüben ו־Lübben שניהם "לובן (גרמניה)". התוצאה היא שאי אפשר להפנות לאחת '
            'מהן בעברית בלי להפנות גם לשנייה.',
        ask='להוסיף מבחין לכותרת העברית של כל אחד מן הצדדים. העמודות "הצעה לרשומה '
            'הנכנסת" ו"הצעה לרשומה הקיימת" נושאות הצעה קונקרטית לכל צד. '
            'ההצעות המסומנות "טיוטה" הן הצעות שלנו ולא הכרעה — הן נסמכות על '
            'החלוקה המנהלית בוויקינתונים, ואנו מבקשים את דעתכם עליהן.',
        how='המקרים אותרו בהשוואת הכותרות העבריות בין הרשומה הנכנסת ובין הרשומה '
            'שכבר מחזיקה את אותה כותרת. לכל זוג בדקנו את השם הלטיני, את מזהה '
            'הוויקינתונים ואת הקואורדינטות, כדי לוודא שמדובר בשני מקומות ולא '
            'בכפילות. שמות המחוזות בהצעות לקוחים מתוויות ויקינתונים בעברית, '
            'לא מתעתיק שלנו.',
        evidence='עמודת "מרחק" מראה כמה רחוקים המקומות זה מזה — עדות לכך שאינם '
                 'אותו מקום. עמודת "נימוק ההצעה" מסבירה על מה נשענת כל טיוטה.',
    ),
    dict(
        key='heb-spelling',
        tasks={'R', 'Z'},
        title='שגיאה באיות הכותרת העברית',
        short='איות הכותרת',
        kind='judgment',
        why='כאן אין עמימות ואין שני מקומות — פשוט האיות העברי של הכותרת שגוי, '
            'או שהכותרת מעלה שאלה של זהות. אלה ממצאים שעלו אגב בדיקות אחרות '
            'ונרשמו במהלך הסקירה.',
        ask='לתקן את האיות לפי העמודה "האיות המוצע", או — במקרה של שטרסבורג — '
            'להכריע בשאלה שבעמודת ההסבר.',
        how='כל מקרה נבדק מול השם הלטיני ברשומה ומול ויקינתונים. אלה מקרים '
            'בודדים שנרשמו ידנית, לא תוצר של סיווג אוטומטי.',
        evidence='עמודת "האיות ברשומה" מול "האיות המוצע", וההסבר שלצדן.',
    ),
    dict(
        key='heb-identity',
        tasks={'A8', 'A10', 'A11'},
        title='הכותרת העברית שייכת לרשומה אחרת',
        short='זהות הכותרת',
        kind='judgment',
        why='מקרים שבהם הבעיה אינה באיות אלא בשיוך: כותרת עברית שיושבת על הרשומה '
            'הלא נכונה, או שתי רשומות שהן למעשה מקום אחד ויש לאחדן. '
            'אלה אינם מקרים שדורשים מבחין — הם דורשים הכרעה מה הרשומה מתארת.',
        ask='לבדוק כל מקרה לגופו לפי ההערה שלצדו: לאחד את הרשומות, או להעביר את '
            'הכותרת העברית לרשומה שאליה היא שייכת.',
        how='אותרו במהלך סקירת הכפילויות ואומתו מול MARC מ־Alma OAI.',
        evidence='עמודת "הערת הסוקר" נושאת את הממצא המלא לכל שורה.',
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


# `note` is the reviewer's column in the app, and it holds two kinds of text:
# real prose about the record, and audit strings the bulk-apply button writes
# ("bulk: B3"). Only the prose belongs in a report to the library — the audit
# strings would put our internal queue codes in a column labelled "reviewer's
# note", 95 of 106 notes' worth.
MACHINE_NOTE = re.compile(r'^\s*bulk:\s*\w+\s*$')

# One note mixes a question to ourselves with a genuine finding. Sending it
# whole would open the line with "why was this reported?", which reads to the
# library as though we doubt our own report. The finding is kept; the question
# stays in decisions.json where it was asked.
NOTE_OVERRIDE = {
    '987007562247105171': 'הסוגר הסופי חסר בכותרת.',
}


def clean_note(rid, note):
    if rid in NOTE_OVERRIDE:
        return NOTE_OVERRIDE[rid]
    note = (note or '').strip()
    return '' if MACHINE_NOTE.match(note) else note


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
        # The three spelling rows were never flagged for the library — two sat
        # in the R research queue with "report to the library" written in the
        # note and no route out. Admit them explicitly.
        if not (r['for_nli'] == 'yes' or r['decision'] in NLI_DECISIONS
                or r['new_id'] in HEB_TAB_OF_ROW):
            continue
        # The Hebrew-naming argument goes in report #2 — both the queues that are
        # about heading form, and any rename-suggestion wherever it was recorded.
        heb_tab = HEB_TAB_OF_ROW.get(r['new_id'])
        if not heb_tab and (r['task'] in HEBREW_NAMING_TASKS
                            or r['decision'] == 'rename-suggestion'):
            skipped_heb += 1
            continue
        if r['task'] in OUR_BUG_TASKS:
            skipped_ours += 1
            continue
        tab = (heb_tab or (Z_TAB_OF_DECISION.get(r['decision']) if r['task'] == 'Z'
                           else TAB_OF_TASK.get(r['task'])))
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
            'note': clean_note(r['new_id'], r['note']),
            'decision': r['decision'],
            'period': r['period'],
            'recovered': bool(extra and extra.get('heb')),
            'wdKind': '', 'wdKindHe': '',
            # Hebrew-naming fields: a drafted proposal is marked as such so
            # nobody mistakes our suggestion for the review's verdict.
            'suggestNew': (NAME_DRAFTS.get(r['new_id']) or {}).get('new')
                          or r['suggested_new_name'],
            'suggestExisting': (NAME_DRAFTS.get(r['new_id']) or {}).get('existing')
                               or r['suggested_existing_name'],
            'suggestWhy': (NAME_DRAFTS.get(r['new_id']) or {}).get('why', ''),
            'suggestWarn': SUGGEST_WARNING.get(r['new_id'], ''),
            'isDraft': r['new_id'] in NAME_DRAFTS,
            'draftHe': 'טיוטה' if r['new_id'] in NAME_DRAFTS else '',
            'spellWas': (SPELLING_FIX.get(r['new_id']) or {}).get('was', ''),
            'spellNow': (SPELLING_FIX.get(r['new_id']) or {}).get('now', ''),
            'spellWhy': (SPELLING_FIX.get(r['new_id']) or {}).get('why', ''),
            'otherHeb': r['existing_heb'], 'otherRom': r['existing_rom'],
        })
    resolve_correct_point(out)
    reroute_wikidata(out)
    print('rows: %d  (Hebrew-naming held back for report #2: %d; our own bugs dropped: %d)'
          % (len(out), skipped_heb, skipped_ours))
    return out


# --------------------------------------------------------- the correct point
def resolve_correct_point(rows):
    """Which point the report offers as correct.

    Usually Kima's — the review's `keep-existing` verdict means exactly "Kima's
    point is right, NLI's is wrong". But in the `wd-disagrees` cases Wikidata
    backs neither side, so Kima's point is wrong too, and printing it under a
    header that says "the point we believe is correct" would hand the library a
    coordinate we do not believe in. Where the reviewer recorded a point by
    hand, that one wins.
    """
    manual = 0
    for r in rows:
        r['correctLatLon'] = r.get('manualLatLon') or r.get('kimaLatLon')
        if r.get('manualLatLon'):
            r['correctSource'] = 'manual'
            manual += 1
            # the distance has to measure to the point the column actually
            # shows, or the row states an error it does not demonstrate
            if r.get('nliLatLon'):
                r['dist'] = haversine(r['nliLatLon'], r['correctLatLon'])
        else:
            r['correctSource'] = 'kima'
    if manual:
        print('correct point: %d row(s) use the reviewer\'s own coordinates' % manual)


# ------------------------------------------------------- wikidata rerouting
WD_KIND_HE = {'wrong': 'מזהה שגוי', 'suggested': 'מזהה מוצע'}


def reroute_wikidata(rows):
    """Route a row by the correction it carries, not by the queue it was
    reviewed in.

    A Wikidata correction entered while working a coordinate queue was staying
    in the coordinate tab, so the library had to hunt for id errors in two
    places. Any row whose `correctWd` differs from its `nliWd` is an 024
    finding and belongs in the Wikidata tab.

    Two cases are deliberately excluded:

    * `correctWd == nliWd` — NLI's id is already right and the correction was
      recorded for *Kima's* id (the classifier bucket says so). There is
      nothing here for the library to change, so the value is cleared rather
      than shown: leaving it invites a "fix" to an id that is correct.
    * a row with no `correctWd` at all.

    `wdKind` then separates a defect from an offer: `wrong` where NLI holds an
    id that points elsewhere, `suggested` where NLI holds none and we found one.
    """
    moved = cleared = out = 0
    for r in rows:
        cw = (r.get('correctWd') or '').strip()
        nw = (r.get('nliWd') or '').strip()
        if not cw:
            # The rule cuts both ways: a B10 row carrying no id correction is
            # not an 024 finding either. Vargem Grande is a coordinate case
            # ("Wikidata agrees with neither point", the note gives the right
            # point) that only landed here because queue B10 feeds this tab.
            if r['tab'] == 'wikidata-id':
                r['tab'] = 'nli-coords'
                r['fromTab'] = 'wikidata-id'
                out += 1
            continue
        if cw == nw:
            r['correctWd'] = ''          # Kima-side fix — not the library's
            cleared += 1
            continue
        # An explicit Hebrew-tab assignment wins: פלאנס carries a correctWd, but
        # its finding is that two live NLI records describe one village. The id
        # is incidental; moving it would file a duplicate under "wrong id".
        if HEB_TAB_OF_ROW.get(r['id']):
            continue
        r['wdKind'] = 'wrong' if nw else 'suggested'
        r['wdKindHe'] = WD_KIND_HE[r['wdKind']]
        if r['tab'] != 'wikidata-id':
            r['fromTab'] = r['tab']
            r['tab'] = 'wikidata-id'
            moved += 1
    if moved or cleared or out:
        print('wikidata: %d row(s) rerouted into the 024 tab, %d out of it, '
              '%d Kima-side value(s) cleared' % (moved, out, cleared))


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
# Columns that stay in the workbook (hidden) but never render on the page.
HIDDEN_COLUMNS = {'bucketWhy', 'confidence'}

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
        ('nliLatLon', 'נקודת NLI'), ('correctLatLon', 'הנקודה שלדעתנו נכונה'),
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
        ('wdKindHe', 'סוג הפנייה'),
        ('nliWd', 'המזהה שברשומה'), ('correctWd', 'המזהה הנכון / המוצע'),
        ('nliLatLon', 'נקודת NLI'), ('kimaLatLon', 'נקודת כימה'), ('dist', 'מרחק (ק״מ)'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
    ],
    'duplicate-records': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('otherNliId', 'מזהה הרשומה השנייה'), ('kimaHeb', 'כותרת הרשומה השנייה'),
        ('nliWd', 'ויקינתונים משותף'), ('dist', 'מרחק בין הנקודות (ק״מ)'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'), ('otherNliUrl', 'קישור לשנייה'),
    ],
    'heb-homonym': [
        ('heb', 'הכותרת העברית המשותפת'), ('draftHe', 'מעמד ההצעה'),
        ('rom', 'הרשומה הנכנסת (לטינית)'), ('id', 'מזהה NLI'),
        ('suggestNew', 'הצעה לרשומה הנכנסת'),
        ('otherRom', 'הרשומה הקיימת (לטינית)'), ('otherNliId', 'מזהה הרשומה הקיימת'),
        ('suggestExisting', 'הצעה לרשומה הקיימת'),
        ('dist', 'מרחק (ק״מ)'), ('suggestWhy', 'נימוק ההצעה'),
        ('suggestWarn', 'לבדיקה לפני שליחה'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
    ],
    'heb-spelling': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('spellWas', 'האיות ברשומה'), ('spellNow', 'האיות המוצע'),
        ('spellWhy', 'הסבר'), ('url', 'קישור לרשומה'),
    ],
    'heb-identity': [
        ('heb', 'כותרת עברית'), ('rom', 'כותרת לטינית'), ('id', 'מזהה NLI'),
        ('otherNliId', 'הרשומה השנייה'), ('otherHeb', 'כותרת הרשומה השנייה'),
        ('note', 'הערת הסוקר'), ('url', 'קישור לרשומה'),
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
                  'suggestNew': 34, 'suggestExisting': 34, 'suggestWhy': 60,
                  'spellWas': 26, 'spellNow': 26, 'spellWhy': 60, 'otherHeb': 28,
                  'otherRom': 30, 'draftHe': 12,
                  'url': 34, 'otherNliUrl': 34, 'bucketWhy': 34, 'kimaHeb': 28}
        for i, (k, _) in enumerate(cols, start=1):
            ws.column_dimensions[get_column_letter(i)].width = widths.get(k, 16)
        # Internal working, kept for our own checking but hidden: the library
        # is told what the tab is in the side panel, and per-row classifier
        # reasoning only invites the question "what is a bucket?".
        for i, (k, _) in enumerate(cols, start=1):
            if k in HIDDEN_COLUMNS:
                ws.column_dimensions[get_column_letter(i)].hidden = True
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = 'A1:%s%d' % (get_column_letter(len(cols)), ws.max_row)
    # The side-panel prose, editable. Read back by read_xlsx() — the `key`
    # column is the join and must not be edited; everything right of it is
    # yours. Keep the column order: the reader matches on these headers.
    exp = wb.create_sheet('הסברים')
    exp.sheet_view.rightToLeft = True
    exp_cols = [('key', 'מפתח (לא לערוך)'), ('short', 'שם הלשונית'),
                ('title', 'כותרת'), ('why', 'מה קרה'),
                ('ask', 'מה מבוקש מן הספרייה'), ('how', 'איך נמצא'),
                ('evidence', 'העדות בטבלה')]
    exp.append([label for _, label in exp_cols])
    for c in range(1, len(exp_cols) + 1):
        cl = exp.cell(row=1, column=c)
        cl.fill, cl.font = head_fill, head_font
        cl.alignment = Alignment(vertical='center', wrap_text=True)
    for t in payload['tabs']:
        exp.append([t.get(k, '') for k, _ in exp_cols])
    for i, (k, _) in enumerate(exp_cols, start=1):
        exp.column_dimensions[get_column_letter(i)].width = \
            {'key': 18, 'short': 20, 'title': 40}.get(k, 62)
    for row in exp.iter_rows(min_row=2):
        for cl in row:
            cl.alignment = Alignment(vertical='top', wrap_text=True)
    exp.freeze_panes = 'B2'

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



# ---------------------------------------------------------------- read back
# Option A: the edited spreadsheet is the source of truth for the report.
# `--from-drive` (or `--from-xlsx <path>`) regenerates docs/ from the workbook
# instead of from decisions.json, so edits made in Drive reach the page.
#
# Rows are matched on the NLI record id, the one column that must never be
# edited. A row that has left the sheet is NOT deleted: it is kept in
# data.json with removed=True and hidden from the page, so an accidental
# deletion in Drive can never silently drop a finding from the report.

DRIVE_FILE_ID = '12urSRrUoT8BU6Kz4W6iEWakgUGEgnXa9'
ID_HEADER = 'מזהה NLI'


def _norm_header(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def read_xlsx(path):
    """Parse an edited workbook back into (rows_by_id, tab_prose)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    label_to_key = {label: key for cols in COLUMNS.values() for key, label in cols}

    prose = {}
    if 'הסברים' in wb.sheetnames:
        ws = wb['הסברים']
        head = [_norm_header(c.value) for c in ws[1]]
        want = {'מפתח (לא לערוך)': 'key', 'שם הלשונית': 'short', 'כותרת': 'title',
                'מה קרה': 'why', 'מה מבוקש מן הספרייה': 'ask', 'איך נמצא': 'how',
                'העדות בטבלה': 'evidence'}
        idx = {want[h]: i for i, h in enumerate(head) if h in want}
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[idx.get('key', 0)]:
                continue
            prose[str(row[idx['key']]).strip()] = {
                f: (str(row[i]).strip() if row[i] is not None else '')
                for f, i in idx.items() if f != 'key'}

    edited = {}
    for name in wb.sheetnames:
        if name in ('אודות', 'הסברים'):
            continue
        ws = wb[name]
        head = [_norm_header(c.value) for c in ws[1]]
        if ID_HEADER not in head:
            print('  ! sheet %r has no %r column — skipped' % (name, ID_HEADER))
            continue
        i_id = head.index(ID_HEADER)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[i_id] in (None, ''):
                continue
            rid = str(row[i_id]).strip()
            vals = {}
            for i, h in enumerate(head):
                key = label_to_key.get(h)
                if key and key != 'id':
                    v = row[i]
                    vals[key] = '' if v is None else str(v).strip()
            edited[rid] = vals
    return edited, prose


def apply_edits(payload, edited, prose):
    """Fold the spreadsheet's values back over the generated payload.

    Coordinate columns are read-only on this path. The sheet prints them at 5
    decimals, so reading them back would silently round the stored precision
    (Kima holds ~11) and every build would report 100 phantom "edits". They are
    derived from Kima and Wikidata, not from the reviewer's judgment, so the
    generated value always wins. To correct a point, fix it in the review app.
    """
    READ_ONLY = {'nliLatLon', 'kimaLatLon', 'fixedLatLon', 'manualLatLon', 'dist'}
    changed = touched = 0
    for r in payload['rows']:
        e = edited.get(r['id'])
        if e is None:
            r['removed'] = True          # left the sheet — kept, hidden, listed
            continue
        r['removed'] = False
        hit = False
        for key, v in e.items():
            if key in READ_ONLY:
                continue
            new = v
            if new != r.get(key) and not (new in ('', None) and r.get(key) in ('', None)):
                r[key] = new
                hit = True
                changed += 1
        touched += hit
    for t in payload['tabs']:
        p = prose.get(t['key'])
        if p:
            t.update({k: v for k, v in p.items() if v})
    live = [r for r in payload['rows'] if not r.get('removed')]
    gone = [r for r in payload['rows'] if r.get('removed')]
    counts = {}
    for r in live:
        counts[r['tab']] = counts.get(r['tab'], 0) + 1
    for t in payload['tabs']:
        t['n'] = counts.get(t['key'], 0)
    payload['tabs'] = [t for t in payload['tabs'] if t['n']]
    print('spreadsheet applied: %d values changed across %d rows' % (changed, touched))
    if gone:
        print('  %d row(s) no longer in the sheet — kept as removed, hidden from the page:'
              % len(gone))
        for r in gone:
            print('     %s  %s' % (r['id'], r['heb'] or r['rom'] or '—'))
    return payload


def fetch_drive(dest):
    """Download the edited workbook. Needs a Drive credential; the Claude Drive
    connector can also save it here by hand — see docs in the module header."""
    url = ('https://www.googleapis.com/drive/v3/files/%s?alt=media' % DRIVE_FILE_ID)
    tok = os.environ.get('GOOGLE_OAUTH_TOKEN', '')
    if not tok:
        raise SystemExit(
            'No GOOGLE_OAUTH_TOKEN set.\n'
            'Either export one, or download the sheet yourself and run:\n'
            '    python3 app/build_nli_report.py --from-xlsx <path-to.xlsx>')
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok})
    with urllib.request.urlopen(req, timeout=120) as fh, open(dest, 'wb') as out:
        out.write(fh.read())
    return dest


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
    # Option A: when an edited workbook is given, it wins. The generated rows
    # above become the scaffold; the sheet supplies the values.
    src = None
    if '--from-xlsx' in sys.argv:
        src = sys.argv[sys.argv.index('--from-xlsx') + 1]
    elif '--from-drive' in sys.argv:
        src = fetch_drive(os.path.join(APP_DIR, '.cache', 'edited-report.xlsx'))
    if src:
        print('reading edits from %s' % src)
        # keep the download link the existing page already advertises
        old = os.path.join(DOCS, 'data.json')
        if os.path.exists(old):
            payload['xlsx'] = json.load(open(old)).get('xlsx', '')
        edited, prose = read_xlsx(src)
        payload = apply_edits(payload, edited, prose)
        rows = payload['rows']

    json.dump(payload, open(os.path.join(DOCS, 'data.json'), 'w'),
              ensure_ascii=False, indent=1)
    live = sum(1 for r in rows if not r.get('removed'))
    print('wrote docs/data.json — %d rows in %d tabs' % (live, len(payload['tabs'])))
    # Rewriting the workbook from an edited workbook would fight the editor, so
    # the .xlsx is only regenerated on a normal build.
    xl = (None if src else
          write_xlsx(payload, os.path.join(DOCS, 'nli-report-%s.xlsx' % today.replace('-', ''))))
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
