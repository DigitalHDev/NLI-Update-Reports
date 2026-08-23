# What to do with the NLI update reports — decision memo

Written 2026-08-11, after the live-NLI analysis (see `app/dup-analysis.tsv`, `app/disambiguation.tsv`).
Revised 2026-08-23: the `nli-gone` / `missing-marc` reading was wrong — those ids are live on NLI
and fetch via Alma OAI-PMH; the IIIF endpoint simply never carried them (issue #9). Passages
affected are marked **[revised]**. Consolidated per-category table: `issue-categories.md`.

Current case census as the app parses it (1,953 cases across both runs):

| category | n | what it really is |
|---|---:|---|
| `location-move` | 1281 | NLI coordinates differ from Kima's by >5 km |
| `multi-034` | 335 | record has ≥2 coordinate sources, **one already matches Kima** |
| `dup-variants` | 171 | variant-string collision — 145 of them *inside a single record* |
| `nli-gone-possibly` / `-suggest-delete` | 47 / 44 | **[revised]** IIIF MARC endpoint does not serve the id — but Alma OAI does; false alarms |
| `dup-places-diff` (+ 5 unresolved) | 37 (+5) | two NLI authorities colliding on one Hebrew heading |
| `missing-marc` | 18 | same as `nli-gone`, but reported as a failure — **[revised]** likewise false |
| `repoint-blocked` | 12 | incoming record wants a Kima place another MAZAL_ID owns |
| `bad-geography` | 3 | malformed geometry |

The single most useful reframing: **roughly a quarter of these rows are artefacts of how the
runner reports, not things a human should ever see.** Sorting the piles by "who fixes this"
— the library, Kima, or Gil's runner — is what the rest of this memo does.

---

## a. What to report to NLI

Three separate approaches, deliberately **not** bundled into one message. They have different
audiences (systems vs cataloguing) and very different confidence levels.

### A1. Ask for a deletion / succession channel — highest structural value

This is the ask worth making first, because it is the one that stops the problem recurring.

The weekly feed announces new and updated ids and **never announces deletions, merges or
suppressions**. Kima consequently holds ids NLI no longer serves. The evidence is clean and
worth quoting verbatim, because it distinguishes two states NLI itself appears not to
distinguish in its API:

- `absent` — HTTP **200** with body `Identifier does not exist in repository`.
  All **109** of the `nli-gone` + `missing-marc` ids are in this state on the **IIIF**
  endpoint. **[revised 2026-08-23]** This is *not* evidence that NLI never had the record:
  all 93 checked are live on the NLI site and fetch via Alma OAI-PMH
  (`.../view/oai/972NNL_INST/request?verb=GetRecord&metadataPrefix=marc21`). The IIIF
  endpoint has incomplete coverage and reports a record it does not carry as nonexistent.
  So `absent` on IIIF means "ask OAI", never "deleted". Worth mentioning to NLI as an
  endpoint bug, but it is not a deletion-channel finding.
- `suppressed` — HTTP **500**, `String index out of range: -2`. The id *is* known to the
  repository but cannot be serialised. **7** of the duplicate cases are in this state; they
  are the deleted-or-merged records.

Two concrete requests:
1. Publish deletions/merges in the feed, or expose the successor in the MARC (a `682` / a
   redirect). Right now the only way to find the successor — as with **דרום סודאן**,
   `987011102591205171` → `987012803472805171` — is to guess by heading.
2. The HTTP 500 is a bug: a suppressed record should return a clean, documented status.
   Any consumer keying on HTTP status reads the `absent` 200 as success and the `suppressed`
   500 as an outage.

### A2. Hebrew primary-form disambiguation — the policy ask, with 30 worked examples

The finding to lead with: **NLI enforces uniqueness on the primary Roman form, not on the
Hebrew form.** In the 30 cases where both ids are live, the Roman forms differ 30/30 while the
Hebrew collides 27/30. The dominant mechanism is that Hebrew flattens every administrative
tier to `מחוז` while the Roman spells it out (Voivodeship / Powiat / Okres / Kraj / Bezirk /
Landkreis / Stadtkreis / oblast / raion / gubernia).

Present it as one policy request — *apply the Roman uniqueness constraint to the Hebrew 151
too* — supported by `app/disambiguation.tsv`, which proposes both sides of each collision.
The 30 split into two kinds that deserve different fixes, and the file should be re-sorted
along this line before it goes out (the current `action` column is a heuristic first pass and
mis-files the tier cases — e.g. זלין for `Zlínský kraj` vs `Zlín` — as "distinct"):

- **~14 administrative-tier collisions** — `Suwałki (Powiat)` vs `Suvalkskai︠a︡ gubernīi︠a︡`,
  `Osh oblasty` vs `Osh`, `Minskai︠a︡ voblastsʹ` vs `Minski rai︠o︡n`, `Pardubice (Okres)` vs
  `Pardubický kraj`, the Landkreis/Stadtkreis/Bezirk pairs. Fix: a Hebrew tier qualifier.
  **The tier vocabulary in `disambiguate.py` (נפה / עיר / מחוז / פלך / אובלסט…) is a
  suggestion of mine, never confirmed — it is a curatorial call and should be NLI's or yours,
  not the script's.** Better still, ask NLI to adopt a fixed tier vocabulary rather than
  approving 14 ad-hoc strings.
- **~11 genuine homographs** — two different places whose Hebrew transliteration coincides:
  `Osterwieck`/`Osterwick`, `Lüben`/`Lübben`, `Hochstätten`/`Hochstetten`, `Elba`/`Alba`,
  `Kaba`/`Káva`, `Ehningen`/`Eningen unter Achalm`, `Cherniïv`/`Chernihiv`,
  `Ishigaki-shi`/`Ishigaki Island`. Fix: a Roman-form parenthetical, or a finer geographic
  qualifier. These are the ones a cataloguer must actually look at.

### A3. A short errata list — high confidence only, kept separate

Sending these mixed into A2 weakens A2. Keep them to cases you are sure of:

- **טרבזון** — the record is `Ardeşen (Turkey)` but the Hebrew heading says Trabzon, a
  different town ~108 km away. Straightforward error.
- **מושבה היוונית** — `Moshavah ha-Yevanit` vs `Greek Colony` (Jerusalem): transliteration and
  translation of the same place, catalogued as two authorities.
- **Five probable internal NLI duplicates** — same location, different Roman forms:
  `Dobrich`/`Tolbukhin` (the same city before and after 1990),
  `Bashkia e Vlorës`/`Vlorë`, `El Albaicín`/`Albaicín`,
  `Tulkarem (Sub-District)`/`Tulkarem`. Flag as *possible* duplicates, not as certain.
  `Bobigny`/`Bouvignies` is in this bucket only because their coordinates agree — they are
  different French communes, so that one is more likely an NLI **coordinate** error than a
  duplicate, and should be reported as such.
- Hold back the **64 same-script name-drift cases** (`ביסטראןןיץ` vs `ביסטרוביץ`,
  `Osterwick` vs `Osterwieck`) until each is attributed. Most are Kima's stale copy of an
  older authority file, not NLI errors; only the ones where NLI's *own* current form is
  malformed belong in an errata report.

---

## b. What to do with the other Kima updates

Route by category, and be willing to close most of these without human review.

**Close in bulk, no human review:**

- `multi-034` (335) — the record carries two coordinate sources and one of them already
  matches Kima to within 1 km. There is nothing to move. Dismiss all; fix upstream (see C3).
- `dup-variants`, `same-id` subset (145 of 171) — Kima already points at that very record;
  the collision is *within* one record's variant list. No cross-record duplication exists.
  Dismiss all; the real fix is an upsert in Kima's importer (C3).

**Mechanical, small, do them:**

- The **7 suppressed ids** — repoint to the live successor. `דרום סודאן` is the worked
  pattern: repoint 22805 to `987012803472805171`, take NLI's `جنوب السودان` as the Arabic
  primary, keep `السودان الجنوبية (السودان)` as a variant, coordinates 7,30 → 8,30.
- The **91 `nli-gone` + 18 `missing-marc`** — **[revised 2026-08-23]** all false: the
  records are live and fetch via Alma OAI (93/93 verified, including the 16 transient
  IIIF 520s). **Do nothing in Kima** — no unlink, no delete. Dismiss the cases in the app,
  and have the runner fetch MARC from OAI instead (issue #9). Re-run `missing-marc` through
  OAI to confirm none remain.

**Needs a rule before it needs a human — `location-move` (1281):**

This is the big pile and it should not be worked case-by-case. Note there are **no** moves
under 5 km at all (the runner's threshold), and the distribution is:
5–25 km: 88 · 25–100 km: 553 · 100–500 km: 353 · >500 km: 287.

Proposed rule, in priority order:
1. If the NLI record and the Kima place agree on an external id (Wikidata / GeoNames),
   **take NLI's coordinates**.
2. If they disagree on the external id, or the move is **>500 km** (287 cases), treat it as a
   **link error, not a move** — almost certainly the Kima place is bound to the wrong NLI id.
   These should be re-matched, not relocated.
3. In the 5–25 km band (88), the usual cause is administrative-centroid vs settlement point.
   Take NLI's, since Kima's aim is to mirror the authority.
4. The 25–500 km middle (906) is the only genuine review queue — and even there, sort by
   whether the two records' *names* still agree, which collapses most of it.

Remember the standing constraint: **Kima's job here is to match NLI ids perfectly**, so the
default when NLI and Kima merely disagree is to follow NLI, and to report upstream when NLI
is wrong rather than to diverge silently.

**Small manual piles:** `repoint-blocked` (12), `bad-geography` (3), `dup-places` unresolved
(5), the 11 genuine homographs from A2. That is ~31 cases of real human work — the number the
whole exercise should be reduced to.

**One positive deliverable, not a problem pile:** harvest `551 $w a` (earlier heading) across
the corpus — Transjordan→ירדן, Dutch East Indies→אינדונזיה, Ruanda-Urundi→רואנדה+בורונדי.
These are free historical variant donations to Kima and exactly what Kima collects.
`parse_marc()` in `server.py` currently drops `551`; `analyze_dups.py` already parses it.

---

## c. Improving Gil's reporting mechanism

Ordered by how much noise each removes.

1. **Stop emitting the two artefact classes.** `multi-034` (335) should never be reported as a
   location move — compare Kima's point against *all* `034` coordinate sets in the record, not
   the first. `dup-variants` same-id (145) should never be reported at all — the importer
   should upsert variants instead of insert. That is **480 of 1,953 rows**, a quarter of the
   report, gone at source.
2. **Model the three MARC states explicitly.** The runner currently keys on the prose
   `RecordId does not exist in repository`, which is the endpoint's `absent` 200-with-error-body
   with a word changed. It has no representation for `suppressed` (HTTP 500), which is the
   state that actually means *deleted/merged*. Every id check should return one of
   `live` / `absent` / `suppressed`, and suppressed ids should trigger a successor search.
   **[revised]** And the check must run against Alma OAI, not IIIF — on IIIF `absent` is
   mostly a coverage gap (issue #9).
3. **Emit structured rows, not English prose.** Today `categorize()` regexes phrases and
   `DUP_KEY_RE` scrapes a raw SQL duplicate-key string. A duplicate row should carry both
   sides as fields: incoming NLI id, colliding heading, owning Kima place id, its current
   MAZAL_ID, and the script the collision occurred in. That last field alone would have
   surfaced the Hebrew-vs-Roman uniqueness mismatch on day one.
4. **Make the report append-only and case-keyed.** A re-run overwrites the root files, so a
   row that stops failing silently disappears and decisions attached to it are orphaned;
   re-running the same period produces ~20% different output, so diffing two runs cannot be
   used to infer "resolved". Give each case a stable key — `(recordId, kimaPlaceId, category)`
   — and record `firstSeenRun` / `lastSeenRun` rather than rewriting the file.
5. **Carry a proposed action and a confidence per row.** The report currently states a problem;
   what a reviewer needs is a proposal to accept or reject. Even a crude
   `suggestedAction` + `confidence` turns 1,953 rows into a sorted queue.
6. **Compare like script with like.** `heb`↔`heb`, `rom`↔`lat`, `arab`↔`ara`. Cross-script
   comparison is what generates the false name-drift hits.

---

## d. Redesigning the local review app

The app's current shape — browse a flat category list, one case at a time, decision keyed by
`recordId` in `decisions.json` — is right for 50 cases and unusable for 1,953. Four changes.

**1. Replace categories with three queues.** Categories describe the runner's internal
taxonomy; a reviewer needs to know who acts. Route every case by rule into:

- **Auto** — resolvable without judgment (the 480 artefacts, the 109 false `nli-gone` dismissals, the 7 repoints).
  Shown as a count with a sample and a single "apply all" button, not as 596 cards.
- **Review** — genuine judgment (~31 hard cases plus the `location-move` middle band).
- **Outbound to NLI** — the A2/A3 piles, which are not Kima edits at all and should never
  have shared a queue with them.

**2. Bulk actions, and a rule preview.** Select-all-in-bucket, apply one decision to N rows.
Better: let a rule be *written* (e.g. "move >500 km and Wikidata mismatch → relink, not move"),
show how many rows it catches and a random sample of them, then commit it. The
`location-move` pile is only tractable this way.

**3. Fix the `stale` flag — it is actively misleading.** It conflates *superseded by the
re-run* with *in a period the re-run never reached*. The root run covers only 20240610–20250630;
`backup/` reaches 2026-06-30, so the newest evidence lives only there. Concretely: 210 of the
213 duplication cases are marked `stale` and 201 of them are simply past the re-run cutoff —
the freshest data in the repo. The `רק הריצה הנוכחית` / `current=1` filter hides almost all of
it. Replace the single boolean with two explicit facts: `lastSeenRun` and
`beyondRerunCutoff`, and default the filter to *neither hidden*.

**4. Three exports instead of one decisions file.** `decisions.json` stays the source of
truth, but the app should emit:

- `kima-apply.tsv` — the Kima-side edits, in whatever shape the Kima import wants;
- `nli-report.tsv` — the library-facing report (A2 + A3), Hebrew-facing, with both sides'
  ids and the proposed heading;
- `runner-bugs.md` — the C-list, regenerated with live counts, so the feedback to Gil is
  evidence rather than assertion.

**Keep as-is:** the NLI-vs-Kima side-by-side card with the map, and the MARC disk cache in
`app/.cache/nli_marc/` with status re-derived from the cached body (a reclassification needs no
refetch — that property is worth preserving through any rewrite).

**Add to the evidence panel:** the live/absent/suppressed badge, `551 $w a` heading succession,
and same-script-only diff highlighting between Kima's primary and NLI's `151`.

---

## Suggested order of work

1. Suppress the 480 artefact rows in the app (queue routing) — biggest immediate relief.
2. Dismiss the 109 false `nli-gone` cases and apply the 7 repoints (after confirming the 7 via OAI). Mechanical, fully evidenced.
3. Send A1 (deletion channel) to NLI — it is independent of everything else and unblocks the future.
4. Curate `disambiguation.tsv` by hand — re-sort tier vs homograph, decide the Hebrew tier
   vocabulary — then send A2 + A3.
5. Write the `location-move` rules, preview them, apply.
6. Send the runner-bugs list to Gil with the counts from step 1.
