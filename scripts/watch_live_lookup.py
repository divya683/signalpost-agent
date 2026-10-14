#!/usr/bin/env python3
"""Run the real pipeline against one organisation number, live, printing each
network call as it happens.

This is the same code path scripts/run_competition_batch.py uses for every
company in a batch -- nothing here is pre-built, cached, or simulated. It
exists so a person can watch the agent work on a single company in real
time: pick any Norwegian organisation number, including one not in the
committed 1,097-company sample, and see every live HTTP call, its timing,
and the cited answer it produces.

Usage:
    uv run python scripts/watch_live_lookup.py --org 923609016
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import profiles_from_live  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.research import answer_profile  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402

OVERVIEW_QUESTION = "Who leads this company and what financial facts and locations are available?"
MODULES = {"registry_live", "financials", "financial_history", "roles", "group", "locations"}


def step(label: str) -> float:
    print(f"-> {label} ...", flush=True)
    return time.monotonic()


def done(start: float, detail: str = "") -> None:
    elapsed = time.monotonic() - start
    suffix = f" ({detail})" if detail else ""
    print(f"   done in {elapsed:.2f}s{suffix}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="Any 9-digit Norwegian organisation number")
    parser.add_argument("--question", default=OVERVIEW_QUESTION)
    args = parser.parse_args()
    org = "".join(ch for ch in args.org if ch.isdigit())

    overall_start = time.monotonic()

    start = step(f"Fetching identity from the live Brønnøysund registry for {org}")
    profiles, registry_metadata = profiles_from_live([org])
    done(start, registry_metadata.get("source", ""))
    profile = profiles[0]
    if profile.get("evidence", {}).get("registry", {}).get("status") == "not_found":
        print(f"\n{org} was not found in the registry. Nothing further to fetch.")
        return
    print(f"   Identity confirmed: {profile.get('name')} ({profile.get('municipality')})")

    start = step("Fetching financials, roles, group structure and subunits")
    records, metrics = fetch_official_modules(org, MODULES)
    profile["evidence"].update(records)
    done(start, f"{len(metrics)} requests")

    start = step(f"Visiting the registry-listed website: {profile.get('website') or '(none registered)'}")
    website_record, website_metrics = fetch_website(profile.get("website"))
    profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
    done(start, f"{website_metrics['requests']} requests")

    start = step(f"Answering: {args.question!r}")
    answer = answer_profile(profile, args.question)
    done(start)

    total = time.monotonic() - overall_start
    print(f"\nTotal elapsed: {total:.2f}s\n")
    print("=" * 60)
    print(f"ANSWER ({len(answer['facts'])} cited facts)")
    print("=" * 60)
    for fact in answer["facts"]:
        print(f"- {fact['claim']}: {fact['value']}")
        print(f"    source: {fact['source_url']}")
        print(f"    retrieved: {fact['retrieved_at']}")
    if answer.get("unsupported_or_uncertain"):
        print("\nUnsupported or uncertain:")
        for item in answer["unsupported_or_uncertain"]:
            print(f"- {item}")


if __name__ == "__main__":
    main()
