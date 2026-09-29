#!/usr/bin/env python3
"""Run all approved external-footprint connectors over one batch and merge results.

Orchestrates the connectors that are actually cleared for publication
(acquisition_mode in PUBLISHABLE_ACQUISITION_MODES) -- currently Wikidata
(exact orgnr match, P2333) and Fagfolkguiden (exact-page embedded ratings).
Experimental/quarantined connectors (LinkedIn, YouTube, Google News RSS) are
intentionally not included here; they contribute zero publishable score today.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.external_footprint import aggregate_footprint, validate_observation  # noqa: E402


def run(cmd: list[str]) -> None:
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", required=True, help="profiles-output from run_competition_batch.py")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--output", required=True, help="merged observations JSONL")
    parser.add_argument("--report", required=True, help="merged coverage report")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    profiles = read_jsonl(Path(args.profiles))
    orgs = [str(row["organisation_number"]) for row in profiles]

    # The two connectors expect different --organisations formats (JSONL rows vs.
    # plain org-number lines). Derive both from --profiles so callers only pass one file.
    orgs_jsonl = workdir / "orgs.jsonl"
    orgs_jsonl.write_text("".join(json.dumps({"organisation_number": org}) + "\n" for org in orgs), encoding="utf-8")
    orgs_txt = workdir / "orgs.txt"
    orgs_txt.write_text("\n".join(orgs) + "\n", encoding="utf-8")

    wikidata_output = workdir / "wikidata-observations.jsonl"
    wikidata_report = workdir / "wikidata-report.json"
    print("Running Wikidata connector...")
    run([
        python, str(ROOT / "scripts/run_wikidata_connector.py"),
        "--organisations", str(orgs_jsonl),
        "--output", str(wikidata_output),
        "--report", str(wikidata_report),
    ])

    fagfolk_output = workdir / "fagfolk-observations.jsonl"
    fagfolk_report = workdir / "fagfolk-report.json"
    fagfolk_cache = workdir / "fagfolk-cache"
    print("Running Fagfolkguiden connector...")
    run([
        python, str(ROOT / "scripts/run_fagfolkguiden_reviews_connector.py"),
        "--profiles", args.profiles,
        "--organisations", str(orgs_txt),
        "--output", str(fagfolk_output),
        "--cache", str(fagfolk_cache),
        "--report", str(fagfolk_report),
    ])

    merged = read_jsonl(wikidata_output) + read_jsonl(fagfolk_output)
    seen_ids: set[str] = set()
    deduped = []
    for item in merged:
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        deduped.append(item)

    rejections = [(item["id"], validate_observation(item)) for item in deduped if validate_observation(item)]
    summary = aggregate_footprint(deduped)

    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in deduped), encoding="utf-8")
    report = {
        "connectors_run": ["wikidata_exact_orgnr_p2333_v1", "fagfolkguiden_embedded_google_reviews_v1"],
        "companies_in_batch": len(orgs),
        "merged_observations": len(deduped),
        "duplicate_ids_dropped": len(merged) - len(deduped),
        "validation_rejections": len(rejections),
        "rejection_detail": rejections[:20],
        "companies_with_any_external_signal": len({row["organisation_number"] for row in deduped}),
        "aggregate_footprint": summary,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("aggregate_footprint", "rejection_detail")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
