# Drafts for Gil — how to file these

These are draft GitHub issues proposing changes to the update runner, based on the
live-NLI analysis (see `../REVIEW-PLAN.md` for the full reasoning, including the parts
that concern NLI and Kima rather than the runner).

**Posted 2026-08-11** as issues #2–#7. The files are kept as the source text; edit the
issues on GitHub from here on, not these files.

| file | issue |
|---|---|
| `00-overview.md` | [#2](https://github.com/DigitalHDev/NLI-Update-Reports/issues/2) |
| `01-nli-record-states.md` | [#3](https://github.com/DigitalHDev/NLI-Update-Reports/issues/3) |
| `02-multi-034.md` | [#4](https://github.com/DigitalHDev/NLI-Update-Reports/issues/4) |
| `03-variant-upsert.md` | [#5](https://github.com/DigitalHDev/NLI-Update-Reports/issues/5) |
| `04-duplicate-report-fields.md` | [#6](https://github.com/DigitalHDev/NLI-Update-Reports/issues/6) |
| `05-stable-case-keys.md` | [#7](https://github.com/DigitalHDev/NLI-Update-Reports/issues/7) |

## Recommended mechanism

Issue #1 ("Update failures") has been working well as a *case-by-case triage thread* —
you post a puzzling record, Gil explains what the runner did. Keep it for that. It is
the wrong container for change requests, though: five distinct proposals buried in a
30-comment thread cannot be prioritised, assigned, closed, or referenced later, and Gil
cannot tell which ones you consider settled.

So: **keep #1 as the triage thread, and open one focused issue per proposed change.**
Each of the drafts below is self-contained — Gil has not seen any of this analysis, so
each one restates what the runner does today, what the evidence is, and what the change
would be, without assuming he has read the others.

Post `00-overview.md` first as a tracking issue, then the rest, then edit the overview to
link their numbers.

```sh
gh issue create --title "..." --body-file proposals/01-nli-record-states.md
```

Suggested labels: `runner-change`, and `noise-reduction` on 02 and 03 (the two that
delete report rows rather than add information).

### Two things worth doing beyond issues

1. **Commit the analysis artefacts** (`app/dup-analysis.tsv`, `app/disambiguation.tsv`,
   `app/analyze_dups.py`) so the issues can link to files in the repo instead of pasting
   numbers Gil has to take on trust. The scripts also show exactly how each figure was
   derived, which matters for the ones that contradict earlier answers.
2. **Propose the report format as a versioned file** — `REPORT-SPEC.md` in this repo,
   changed by pull request. Issues 04 and 05 are really both requests to change the
   report's *contract*; a spec file makes that contract explicit, lets Gil object to a
   concrete diff rather than to prose, and gives the consuming app something stable to
   code against. This is the highest-leverage single suggestion in the set, and worth
   raising with Gil before writing the spec unilaterally — it is a change to how you two
   work, not just to the runner.

GitHub Discussions is *not* worth enabling here. The open-ended conversation already
happens in #1 and by email; splitting it across another surface will cost more than it
returns.

## The drafts

| file | proposed change | rows removed / information added |
|---|---|---|
| `00-overview.md` | tracking issue — what the analysis found | — |
| `01-nli-record-states.md` | distinguish *absent* from *suppressed* when NLI won't serve a record | answers "deleted or not?" — currently unanswerable |
| `02-multi-034.md` | compare Kima against **all** `034` fields, not one | −335 rows |
| `03-variant-upsert.md` | upsert variants instead of insert | −145 rows |
| `04-duplicate-report-fields.md` | report both sides of a duplicate as fields | answers your Ishigaki questions from #1 |
| `05-stable-case-keys.md` | append-only reports with stable case keys | makes decisions survive re-runs |

Together 02 and 03 remove **480 of 1,953 rows** — a quarter of the report — without
losing any information.
