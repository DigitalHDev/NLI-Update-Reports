<!-- Title: Duplicate-key reports should identify both sides, and say which script collided -->

@GilShalit — this is the concrete version of what I asked in #1 ("can we make the report
automatically extract the ID of the duplicate other?"), now that I know what the answer
would have told us.

## What the report gives us today

```
addPlaceRecord: error for place 987013405241405171 after step 3: An error occurred while
saving the entity changes. See the inner exception for details. --> Cannot insert duplicate
key row in object 'dbo.Places' with unique index 'IX_Places_primary_heb_full'. The
duplicate key value is (פלאנס (ספרד)). The statement has been terminated.
```

That is a SQL exception passed through as prose. To do anything with it I regex the
duplicate-key value out of the message, query the Kima API for the place holding that
Hebrew string, read its `MAZAL_ID`, and fetch both records' MARC. Every consumer of these
reports has to reimplement that, and it only works at all because the index name happens
to encode which column collided.

## What the fields would be

For each duplicate-key failure:

- the incoming NLI record id (already present)
- **the colliding Kima place id and its current `MAZAL_ID`** — the "duplicate other"
- the colliding value, and **which field/script it collided in** (`primary_heb_full`,
  `primary_rom_full`, …) as a field rather than encoded in an index name
- both sides' current primary forms in each script

The runner is better placed to emit these than I am to reconstruct them: it has the Kima
row in hand at the moment the insert fails, whereas I am guessing at it afterwards from a
string. My resolution fails outright on 31 of 213 cases.

## Why the script field in particular

Having that field would have surfaced the following on the first report rather than after
a full analysis. Across the 30 duplicate cases where both NLI records are live:

- the two records' primary **Roman** forms differ in **30 of 30**
- their primary **Hebrew** forms collide in **27 of 30**

NLI enforces uniqueness on the Roman form; Kima's unique index is on `primary_heb_full`.
So these are not duplicate places at all — they are two valid, distinct NLI authorities
whose Hebrew renderings coincide. The commonest reason is that Hebrew flattens every
administrative tier to `מחוז` while the Roman spells it out: `Suwałki (Poland : Powiat)`
vs `Suvalkskai︠a︡ gubernīi︠a︡ (Poland)`, `Osh oblasty` vs `Osh`, `Minskai︠a︡ voblastsʹ` vs
`Minski rai︠o︡n`, `Zlínský kraj` vs `Zlín`.

Consequences, so we are reading these rows the same way:

- **A duplicate-key failure on the Hebrew index is not evidence of a duplicate in NLI.**
  Most of the time both records are correct and should both exist in Kima.
- The fix is a disambiguation request to NLI, which I am preparing — not a merge in Kima.
- A handful *are* real NLI problems (`Ardeşen (Turkey)` carrying the Hebrew heading
  טרבזון, a town 108 km away; `Moshavah ha-Yevanit` and `Greek Colony` for one place) and
  those go to NLI too, but as errata rather than as duplicates.
- 7 more are Kima holding an id NLI has since withdrawn — see the record-states issue.

## A question rather than a request

Given that most Hebrew collisions are legitimate, is `IX_Places_primary_heb_full` the
right constraint for Kima to enforce at all? Uniqueness on the NLI record id is the
invariant we actually care about. I am not proposing you change it — that is a Kima
schema decision and not yours alone — but if the index stays, these failures will keep
arriving at roughly the current rate, and it would be better to route them straight to an
"NLI disambiguation needed" queue than to treat each as an import error.
