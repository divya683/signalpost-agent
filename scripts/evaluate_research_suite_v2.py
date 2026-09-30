#!/usr/bin/env python3
"""Evaluate the richer v2/v3 research-agent suites (qa_cases/screen_cases/oracle format).

These suites ship in tests/fixtures/ but no evaluator in the starter kit
actually consumes them -- evaluate_research_agent.py only understands the
older single_company/screens/expected_organisation_numbers shape. This fills
that gap: qa_cases check answer_profile() cites enough facts and covers each
required_claims label; screen_cases check parse_screen_query()'s inferred
filter/sort plan matches the oracle (these suites test the query parser's
plan, not literal result membership); unsupported_cases check abstention.

Extension suites (base_suite: <parent>) hold qa_cases only, meant to be run
against a disjoint set of companies to catch overfitting -- run them with
the same --input as long as it also contains those organisation numbers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.research import answer_profile, parse_screen_query, screen_profiles  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_qa(profile: dict, case: dict) -> dict:
    result = answer_profile(profile, case["question"])
    facts = result["facts"]
    cited = all(item.get("source_url") and item.get("retrieved_at") and item.get("content_sha256") for item in facts)
    claim_labels = {item["claim"] for item in facts}
    required = set(case.get("required_claims", []))
    covered = required <= claim_labels
    enough = len(facts) >= case["minimum_facts"]
    return {
        "id": case["id"],
        "organisation_number": case["organisation_number"],
        "facts_found": len(facts),
        "minimum_facts": case["minimum_facts"],
        "enough_facts": enough,
        "all_cited": cited,
        "required_claims": sorted(required),
        "missing_claims": sorted(required - claim_labels),
        "passed": enough and cited and covered,
    }


def filters_match(actual: list[dict], expected: list[dict]) -> bool:
    def norm(items: list[dict]) -> list[tuple]:
        return sorted((item["field"], item["operator"], item["value"]) for item in items)
    return norm(actual) == norm(expected)


def sort_match(actual: dict | None, expected: dict | None) -> bool:
    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    return (actual.get("field"), actual.get("direction"), actual.get("limit")) == (
        expected.get("field"), expected.get("direction"), expected.get("limit"),
    )


def check_screen(case: dict) -> dict:
    plan = parse_screen_query(case["query"])
    oracle = case["oracle"]
    ok_filters = filters_match(plan["filters"], oracle.get("filters", []))
    ok_sort = sort_match(plan.get("sort"), oracle.get("sort"))
    return {
        "id": case["id"],
        "query": case["query"],
        "filters_match": ok_filters,
        "sort_match": ok_sort,
        "passed": ok_filters and ok_sort,
    }


def check_unsupported(rows: list[dict], case: dict) -> dict:
    result = screen_profiles(rows, case["query"])
    return {"id": case["id"], "query": case["query"], "abstained": result["abstained"], "passed": result["abstained"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="profiles JSONL (must include every org referenced by the suite)")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = read_jsonl(Path(args.input))
    by_org = {row["organisation_number"]: row for row in rows}
    suite = json.loads(Path(args.suite).read_text(encoding="utf-8"))

    qa_results, missing_orgs = [], []
    for case in suite.get("qa_cases", []):
        org = case["organisation_number"]
        if org not in by_org:
            missing_orgs.append(org)
            continue
        qa_results.append(check_qa(by_org[org], case))

    screen_results = [check_screen(case) for case in suite.get("screen_cases", [])]
    unsupported_results = [check_unsupported(rows, case) for case in suite.get("unsupported_cases", [])]

    report = {
        "corpus": suite.get("corpus"),
        "base_suite": suite.get("base_suite"),
        "profiles_available": len(rows),
        "qa_cases_total": len(suite.get("qa_cases", [])),
        "qa_cases_evaluated": len(qa_results),
        "qa_cases_missing_profile": missing_orgs,
        "qa_pass_rate": round(sum(r["passed"] for r in qa_results) / len(qa_results), 4) if qa_results else None,
        "qa_results": qa_results,
        "screen_cases_total": len(screen_results),
        "screen_pass_rate": round(sum(r["passed"] for r in screen_results) / len(screen_results), 4) if screen_results else None,
        "screen_results": screen_results,
        "unsupported_total": len(unsupported_results),
        "unsupported_pass_rate": round(sum(r["passed"] for r in unsupported_results) / len(unsupported_results), 4) if unsupported_results else None,
        "unsupported_results": unsupported_results,
        "all_passed": (
            all(r["passed"] for r in qa_results)
            and all(r["passed"] for r in screen_results)
            and all(r["passed"] for r in unsupported_results)
            and not missing_orgs
        ),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("_results")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
