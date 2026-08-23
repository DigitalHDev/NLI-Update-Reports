<!-- Title: Report redesign — findings from checking every reported case against live NLI -->

Hi @GilShalit — over the last few days I went through the accumulated reports
systematically and checked a large part of them against NLI's live data, rather than
case by case as we have been doing in #1. Some of what came out changes how I read the
reports, and I think a few of it points at changes worth making in the runner itself.

This issue is a summary so the individual proposals have context; the actual requests are
in separate issues, linked at the bottom. None of them is urgent — I would rather agree on
what is worth doing than have you start on any of it.

## How I checked

NLI's IIIF MARC endpoint is reachable directly and needs no credentials, only a browser
`User-Agent` (a default `curl`/`urllib` agent gets a 403 from Cloudflare, which is
probably why this looked closed off before):

```
https://iiif.nli.org.il/IIIFv21/marc/authority/<recordId>
```

I fetched every record id appearing in the reports, cached the responses, and compared
them against what Kima holds. Scripts and outputs are in `app/analyze_dups.py`,
`app/dup-analysis.tsv`.

## The case census

Parsing both the current run and `backup/`, deduplicated by record id — 1,953 cases:

| category | n |
|---|---:|
| location move >5 km | 1281 |
| record has ≥2 coordinate fields, one already matching Kima | 335 |
| variant duplicate-key | 171 |
| id announced but MARC not served (`nli-gone` + `missing-marc`) | 109 |
| place duplicate-key | 42 |
| repoint blocked by another MAZAL_ID | 12 |
| broken geography | 3 |

## The three findings that matter

**1. We *can* tell a deleted record from a never-existing one.** In #1 you wrote, about
the missing-MARC cases, "maybe the change deletion, but we cannot know for sure." It turns
out the endpoint does distinguish them, just not through HTTP status in the way one would
expect — it has three response states, and I verified the distinction against a
deliberately bogus id as a control. Details and a reproducible test in the linked issue.
This is the one finding I would most like you to check independently, because a fair
amount follows from it.

**2. About a quarter of the report is unactionable by construction.** Not wrong —
correctly reporting something that turns out to need no action. 335 "location move" rows
are records carrying two coordinate fields where one of them already agrees with Kima,
and 145 of the 171 variant duplicates are collisions *inside a single record*, where Kima
already points at that very NLI id. Two separate issues, both narrow.

**3. The duplicate-key reports are a Hebrew-vs-Roman uniqueness mismatch.** This answers
the question I asked you in #1 about Ishigaki. In the 30 cases where both NLI records are
live, the Roman forms differ in **30 out of 30**, while the Hebrew forms collide in 27 of
them. NLI enforces uniqueness on the primary Roman form; Kima's unique index is on
`primary_heb_full`. Two entirely valid NLI authorities therefore collide in Kima whenever
their Hebrew renderings coincide — most often because Hebrew flattens every administrative
tier to `מחוז` while the Roman spells it out (Voivodeship / Powiat / Okres / Kraj /
Bezirk / Landkreis / oblast / raion / gubernia).

That is mainly something for me to take to NLI, and I am preparing a disambiguation
proposal for them. The part that concerns the runner is narrower: the report could tell us
which script the collision occurred in, and identify both sides — see the linked issue.

Also worth knowing, though it needs nothing from you: 7 of the duplicate cases are Kima
holding an id NLI has since withdrawn, and 64 cases show name drift between Kima's stored
form and NLI's current `151` within the same script. Both are consequences of NLI
announcing updates but never announcing deletions or merges. I intend to raise that with
NLI directly.

## Proposals

- [ ] #_ — distinguish *absent* from *suppressed* records
- [ ] #_ — don't report a location move when another `034` already matches
- [ ] #_ — upsert variants instead of insert
- [ ] #_ — report both sides of a duplicate as structured fields
- [ ] #_ — stable case keys so decisions survive a re-run

One question that is not a proposal: re-running the same period does not reproduce the
same output — I see roughly 20% different rows on 2025H1. Is that expected? It matters
because it means I cannot use "this row disappeared in the new run" as evidence that a
case was resolved, which I had been assuming I could.
