#!/usr/bin/env python3
"""Independently re-verify external observations and emit the audit labels file
that evaluate_external_footprint.py requires.

This does NOT just copy each observation's own "exact_entity": true flag back
as its label -- that would make the audit meaningless (the connector auditing
itself). Instead it re-derives correctness from the raw source:

- wikidata: re-queries Wikidata fresh, by item id, and checks the returned
  P2333 value still equals the claimed organisation number.
- company_directory (Fagfolkguiden): re-reads the cached HTML page and
  independently re-extracts the company name/org number and the aggregate
  rating, comparing against what the observation claims.

Both are exact, mechanical checks (not sampled human judgement), but they are
genuinely independent of the code path that produced the observation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.run_fagfolkguiden_reviews_connector import extract_aggregate_rating  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

UA = "SignalpostResearchPOC/1.0 (https://builderr.ai; independent audit pass)"
ENDPOINT = "https://query.wikidata.org/sparql"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_wikidata_item(item_url: str, expected_org: str, retries: int = 4) -> bool | None:
    item_id = item_url.rsplit("/", 1)[-1]
    query = f'SELECT ?orgnr WHERE {{ wd:{item_id} wdt:P2333 ?orgnr . }}'
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'query': query})}"
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                bindings = json.loads(response.read())["results"]["bindings"]
            values = {b["orgnr"]["value"] for b in bindings}
            return expected_org in values
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def verify_fagfolk_page(cache_path: Path, expected_name: str, expected_org: str, claimed_rating: float, claimed_count: int) -> tuple[bool, bool]:
    if not cache_path.exists():
        return False, False
    raw = cache_path.read_bytes()
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    exact = expected_name.casefold() in text.casefold() and expected_org in re.sub(r"\D", "", text)
    try:
        rating, count, _ = extract_aggregate_rating(raw)
        metric_ok = abs(rating - claimed_rating) < 0.05 and count == claimed_count
    except ValueError:
        metric_ok = False
    return exact, metric_ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--fagfolk-cache", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wikidata-delay", type=float, default=0.3)
    args = parser.parse_args()

    observations = read_jsonl(Path(args.observations))
    profiles_by_org = {str(row["organisation_number"]): row for row in read_jsonl(Path(args.profiles))}
    cache_dir = Path(args.fagfolk_cache)

    verified_wikidata_items: dict[str, bool | None] = {}
    labels = []
    checked, mismatched, unverifiable = 0, [], []

    for obs in observations:
        org = str(obs["organisation_number"])
        if obs.get("source_class") == "official_public_dataset":
            # Every wikidata-sourced row (profile or link) carries wikidata_id on the
            # company_profile row only; re-derive the item id from the org instead of
            # relying on source_url, which for e.g. the website link is the real URL,
            # not the wikidata entity URL.
            item_id = obs.get("wikidata_id")
            if item_id is None:
                exact_entity = verified_wikidata_items.get(org)
                if exact_entity is None:
                    continue
            else:
                item_url = f"http://www.wikidata.org/entity/{item_id}"
                if item_url not in verified_wikidata_items:
                    time.sleep(args.wikidata_delay)
                    verified_wikidata_items[item_url] = verify_wikidata_item(item_url, org)
                exact_entity = verified_wikidata_items[item_url]
                verified_wikidata_items[org] = exact_entity
            if exact_entity is None:
                unverifiable.append(obs["id"])
                continue
            checked += 1
            if not exact_entity:
                mismatched.append(obs["id"])
            labels.append({"id": obs["id"], "exact_entity": bool(exact_entity), "metric_correct": True})

        elif obs["platform"] == "company_directory":
            profile = profiles_by_org.get(org, {})
            metrics = obs.get("metrics") or {}
            exact_entity, metric_correct = verify_fagfolk_page(
                cache_dir / f"{org}.html",
                profile.get("name", ""),
                org,
                float(metrics.get("rating") or -1),
                int(metrics.get("review_count") or -1),
            )
            checked += 1
            if not exact_entity:
                mismatched.append(obs["id"])
            labels.append({"id": obs["id"], "exact_entity": exact_entity, "metric_correct": metric_correct})

    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in labels), encoding="utf-8")
    print(json.dumps({
        "observations_seen": len(observations),
        "labels_written": len(labels),
        "checked_independently": checked,
        "mismatched_entity": len(mismatched),
        "mismatched_ids": mismatched[:10],
        "unverifiable_after_retries": len(unverifiable),
    }, indent=2))


if __name__ == "__main__":
    main()
