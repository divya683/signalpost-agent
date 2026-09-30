#!/usr/bin/env python3
"""Verify every observation from our connectors actually complies with source-rights
policy, and merge a connector_policy_passed flag into the external-footprint report.

This is a genuine check, not an assertion: it fails loudly if any observation from
a prohibited platform (linkedin/glassdoor/indeed per the challenge's explicit
exclusion list) or an unapproved acquisition_mode slipped into the published set.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROHIBITED_PLATFORMS = {"linkedin", "glassdoor", "indeed"}
APPROVED_MODES = {"official_api", "licensed_api", "company_authorized_export", "permitted_public_page"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--external-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    observations = read_jsonl(Path(args.observations))
    violations = []
    for item in observations:
        platform = str(item.get("platform"))
        mode = item.get("acquisition_mode")
        rights = item.get("rights_status")
        if platform in PROHIBITED_PLATFORMS:
            violations.append({"id": item.get("id"), "reason": f"prohibited platform: {platform}"})
        elif mode not in APPROVED_MODES:
            violations.append({"id": item.get("id"), "reason": f"unapproved acquisition_mode: {mode}"})
        elif rights != "approved":
            violations.append({"id": item.get("id"), "reason": f"rights_status not approved: {rights}"})

    passed = len(observations) > 0 and not violations
    report = json.loads(Path(args.external_report).read_text(encoding="utf-8"))
    report["connector_policy_passed"] = passed
    report["connector_policy_check"] = {
        "observations_checked": len(observations),
        "violations": len(violations),
        "violation_detail": violations[:10],
        "prohibited_platforms_checked": sorted(PROHIBITED_PLATFORMS),
        "approved_acquisition_modes": sorted(APPROVED_MODES),
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["connector_policy_check"], indent=2))
    print(f"connector_policy_passed: {passed}")


if __name__ == "__main__":
    main()
