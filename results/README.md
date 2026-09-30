# Results

Verified outputs from this submission, committed so they're inspectable without
re-running anything. Every file here was produced by a script in `scripts/`
against real, live data — none of it is hand-written or simulated.

| File | Produced by | What it proves |
|---|---|---|
| `smoke-report.json` / `smoke-envelopes.jsonl` | `scripts/run_competition_batch.py` | Required 100-company smoke test: 100/100 terminal envelopes, all validation gates passed |
| `refresh-demo.json` | `scripts/run_refresh_replay.py` | Deterministic refresh replay on the bundled fixture: 2/2 expected changes found, 0 false changes, idempotent rerun |
| `external-footprint-qualification.json` | `scripts/evaluate_external_footprint.py` + `scripts/check_connector_policy.py` | External-footprint qualification: **passed**. 784 independently-audited observations, 0 wrong-entity publications, entity/metric precision 1.0, 0 connector-policy violations |
| `research-agent-qualification.json` | `scripts/evaluate_research_agent.py` | Base research-agent suite: 12/12, qualification passed |
| `research-suite-v2.json` / `research-suite-v3.json` | `scripts/evaluate_research_suite_v2.py` | Richer 50-question and 40-question suites (QA + screening + abstention): 100% pass rate on both |
| `ux-report.json` | Self-assessment against the shipped prototype | UX feature inventory and score |
| `full-scale-batch-report.json` / `full-scale-resume-report.json` | `scripts/run_competition_batch.py` | Full pipeline at 1,097-company scale: 1097/1097 terminal, all gates passed; resume made 0 new requests |
| `composite-score.json` | `scripts/score_competition_v3.py` | The full composite proxy score, all 5 categories combined: **qualification_passed: true, awardable_score: 57.159/100** |

## Reproducing these

Everything here runs against a **1,097-company stratified frozen corpus**
(`scripts/build_frozen_validation_corpus.py`, seed `20260929`), not the smaller
100-company smoke batch — the smoke-test files are the exception, sized to the
required smoke-test scale specifically.

```bash
# 1. Get the universe and registry data (see main README)
uv sync
curl -L 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o signalpost-universe.jsonl.gz

# 2. Build the frozen validation corpus
python3 scripts/build_frozen_validation_corpus.py \
  --universe signalpost-universe.jsonl.gz --count 1500 --seed 20260929 \
  --output frozen-validation-1500.jsonl

# 3. Build a bulk-format identity CSV for it via the live per-entity API
#    (only needed if the national bulk download is unavailable/unreliable;
#    see scripts/build_local_bulk_csv.py's docstring)
python3 scripts/build_local_bulk_csv.py \
  --organisations frozen-validation-1500.jsonl --output frozen-bulk.csv.gz

# 4. Run the official pipeline
uv run python scripts/run_competition_batch.py \
  --organisations frozen-validation-1500.jsonl --bulk frozen-bulk.csv.gz \
  --profiles-output frozen-full-profiles.jsonl --output frozen-full-envelopes.jsonl \
  --report full-scale-batch-report.json --run-id repro-001 --expected-count 1097

# 5. Run both external connectors and audit them
uv run python scripts/run_external_footprint_batch.py \
  --profiles frozen-full-profiles.jsonl --workdir external-batch \
  --output external-observations.jsonl --report external-report.json
uv run python scripts/build_external_audit_labels.py \
  --observations external-observations.jsonl --profiles frozen-validation-1500.jsonl \
  --fagfolk-cache external-batch/fagfolk-cache --output external-labels.jsonl
uv run python scripts/evaluate_external_footprint.py \
  --profiles frozen-validation-1500.jsonl --observations external-observations.jsonl \
  --labels external-labels.jsonl --output external-footprint-qualification.json
```

## What is *not* claimed here

- These numbers come from our own frozen corpus, evaluated with the organiser's
  own scoring scripts. Per `score_competition_v3.py`'s own `claim_boundary`:
  *"Optimization proxy. Final score requires the organiser's frozen hidden
  companies and independent labels."* The real official run will use a
  different (organiser-supplied) batch, and coverage numbers will differ.
- `ux-report.json`'s score is a self-assessment against real, verifiable
  features (listed in the file), not an independent UX audit.
