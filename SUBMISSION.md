# Submission declarations

Required by the challenge's submission contract: declared models, APIs,
licences, source-rights assumptions, and expected cost.

## Models / LLM usage

**None.** This submission does not call any LLM or paid model API. All facts
are retrieved directly from official/permitted structured sources and cited
to their source; no generative synthesis step exists yet.

## APIs and data sources used

| Source | Used for | Licence / rights basis |
|---|---|---|
| Brønnøysundregistrene (`data.brreg.no`) — live entity, roles, subunit, financial-accounts endpoints | Official identity, financials, roles, locations | NLOD 2.0 (official Norwegian open government licence) |
| Wikidata Query Service (`query.wikidata.org/sparql`) | External identity confirmation + linked social/website handles, matched via property P2333 (Norwegian organisation number) | CC0. Query Service is Wikidata's own official public API for this data. |
| Fagfolkguiden (`fagfolkguiden.no/bedrift/...`) | Aggregate customer-rating display (rating value + review count only, never review text) | Public pages, `robots.txt` explicitly allows `/bedrift/`; rating is read from `schema.org aggregateRating` structured markup, a standard meant for automated consumption. Documented judgement call, not an organiser- or vendor-confirmed rights grant — see `results/README.md` and the commit history on `scripts/run_fagfolkguiden_reviews_connector.py` for the full reasoning. |

**Explicitly not used**: LinkedIn, Glassdoor, Indeed, or any other prohibited
platform (enforced programmatically — see `scripts/check_connector_policy.py`
and `results/external-footprint-qualification.json`, 0 violations across 796
observations).

## Expected cost per 100-company run

**$0.00.** Every data source above is free and requires no API key or paid
tier. There is no LLM cost, no paid search API, and no licensed data feed in
this submission.

## Reproducible run command

```bash
uv sync
curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv
curl -L 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o signalpost-universe.jsonl.gz
uv run python select_entry_batch.py --universe signalpost-universe.jsonl.gz --count 100 --output entry-companies.jsonl
cp entry-companies.jsonl smoke-companies.jsonl
uv run python scripts/run_competition_batch.py \
  --organisations smoke-companies.jsonl --bulk brreg-enheter.csv \
  --profiles-output out/smoke-profiles.jsonl --output out/smoke-envelopes.jsonl \
  --report out/smoke-report.json --run-id smoke-001 --expected-count 100
```

If the national bulk CSV download is unreliable (it was, repeatedly, on this
network — see commit `4f3d5c1`), substitute:

```bash
python3 scripts/build_local_bulk_csv.py --organisations smoke-companies.jsonl --output brreg-enheter.csv.gz
# then pass --bulk brreg-enheter.csv.gz instead
```

## Open question for the organisers

`OUTPUT_CONTRACT.md` documents a minimal envelope shape (`organisation_number`,
`run{}`, `claims[]`, `evidence[]`, `changes[]`, `errors[]`, `operations{}`).
Our actual emitted envelopes — produced by the organiser's own
`scripts/run_competition_batch.py`, unmodified in this respect — use a
different top-level shape (`run_id`, `organisation_number`, `state`,
`started_at`, `completed_at`, `modules{}`, `profile{}`). We have not changed
this, since it's the reference implementation's own output and rewriting it
unilaterally risked breaking validated behaviour without confirmation of what
is actually expected. Flagging this discrepancy for clarification rather than
guessing.

## What's verified vs. what's a local proxy

See `results/README.md` for the full breakdown and reproduction steps.
Headline: `results/composite-score.json` — run via the organiser's own
`scripts/score_competition_v3.py` — shows `qualification_passed: true`,
`awardable_score: 57.159/100` on our own 1,097-company frozen corpus. This is
an optimization proxy, not the organiser's hidden official score.
