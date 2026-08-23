<!-- Title: Distinguish "never existed" from "withdrawn" when NLI won't serve a record -->

@GilShalit — this follows up on the missing-MARC exchange in #1, where you wrote:

> there is nothing to add, no MARC is returned, and the reported message is given. Maybe
> the change deletion, but we cannot know for sure.

I think we can know, and the runner is already talking to the endpoint that tells us. It
returns **three** distinct states, and the two failure states do not differ in the way one
would expect — one of them is an HTTP 200 with an error body, the other an HTTP 500.

## Reproducible test

```sh
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
for id in 987012803472805171 987007560271905171 987011102591205171 999999999999999999; do
  printf '%s -> ' $id
  curl -s -A "$UA" -w 'HTTP %{http_code}\n' -o /tmp/m \
    "https://iiif.nli.org.il/IIIFv21/marc/authority/$id"
  head -c 90 /tmp/m; echo
done
```

Output as of 2026-08-11:

| id | HTTP | body | meaning |
|---|---|---|---|
| `987012803472805171` | 200 | `<record …>` | **live** |
| `987007560271905171` | 200 | `<error>Identifier does not exist in repository</error>` | **absent** |
| `987011102591205171` | **500** | `<error>… String index out of range: -2 …</error>` | **suppressed** |
| `999999999999999999` (control) | 200 | `<error>Identifier does not exist in repository</error>` | **absent** |

The control is the important row. A made-up id that NLI has never heard of returns the
*same* 200/absent response as our missing-MARC cases — so "absent" means the repository
has no knowledge of this id at all.

The 500 is different. `String index out of range: -2` is a serialisation failure on a
record the repository *does* know about: it is found, then fails to render. That is the
shape a withdrawn, deleted or merged authority takes. `987011102591205171` is the old
דרום סודאן record that NLI removed after I reported it as a duplicate — exactly the case
you and I could not previously classify.

## What this gives us

I probed all 109 ids the reports flag as missing or gone: **every one is `absent`, none is
`suppressed`.** So those are not deletions — NLI announced ids it has never served, which
is a question for NLI, not something to handle by deleting Kima places. Meanwhile 7 of the
duplicate-key cases resolve to `suppressed` ids, and those *are* withdrawn records where
Kima should be repointed to the successor.

Without the distinction both piles look identical, and the safe-looking response (delete
the Kima place) is wrong for all 109 of them.

## Proposed change

1. Have the id check return one of `live` / `absent` / `suppressed` rather than a boolean
   plus a message, and put that state in the report as a field.
2. Two things to watch out for in the implementation:
   - **Do not key on HTTP status.** `absent` is a 200, so a status check reads it as
     success and then fails on parsing. I suspect this is why the current message reads
     `RecordId does not exist in repository` — that is the endpoint's own error body
     (`Identifier does not exist…`) surfaced as text, which means the runner is already
     seeing this state and simply has no name for it.
   - `suppressed` is a 500, so any retry-on-5xx logic will retry it pointlessly and may
     currently be misreporting it as a transient network failure.
3. When a record comes back `suppressed`, it is worth searching NLI for the successor
   heading — for דרום סודאן the replacement is `987012803472805171` and the fix is
   mechanical. If that is more than you want to build, just emitting the `suppressed`
   state is most of the value; I can do the successor lookup on my side.

Worth sanity-checking the 500 against a couple of ids you know were deleted, in case the
pattern is less clean than my sample suggests.
