#!/usr/bin/env python3
"""Publish individual job adverts found on a company's own confirmed website.

Only one advert at a time, and only from a site whose ownership is confirmed.
A careers landing page, a search link into the national job portal, a parent's
vacancy list, and an advert naming a different employer are all rejected by
norway_company_agent.content_rules.validate_job_ad, which is where those rules
live and are tested.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.content_rules import validate_job_ad  # noqa: E402


def observations(profile: dict) -> tuple[list[dict], dict]:
    website = (profile.get("evidence") or {}).get("website") or {}
    value = website.get("value") or {}
    identity = value.get("identity_assessment") or {}
    stats = {"candidates": 0, "rejected": 0}
    if website.get("status") != "available" or not identity.get("publishable"):
        return [], stats
    # An advert read off a site belongs to whoever owns that site, so a parent,
    # franchise, or managing agent's careers page cannot supply this company's
    # vacancies.
    if not identity.get("own_site_confirmed"):
        return [], stats

    own_host = (urlparse(str(value.get("final_url") or "")).hostname or "")
    org = str(profile["organisation_number"])
    results = []
    for page in value.get("pages") or []:
        check = validate_job_ad(page, own_site_host=own_host, company_name=profile.get("name"))
        url = str(page.get("url") or "")
        digest = str(page.get("content_sha256") or "")
        if not check["publishable"]:
            # Only count pages that at least looked like a careers URL, so the
            # rejection figure means something.
            if "not under a jobs section" not in " ".join(check["reasons"]):
                stats["candidates"] += 1
                stats["rejected"] += 1
            continue
        stats["candidates"] += 1
        if len(digest) != 64:
            stats["rejected"] += 1
            continue
        results.append({
            "id": "company-site-job-" + hashlib.sha256(f"{org}|{url}".encode()).hexdigest()[:24],
            "organisation_number": org,
            "platform": "company_site",
            "signal_type": "job_posting",
            "source_url": url,
            "retrieved_at": website.get("retrieved_at"),
            "content_sha256": digest,
            "exact_entity": True,
            "identity_proof": [
                {"type": "website_identity_gate", "score": identity.get("score"), "method": identity.get("method")},
                {"type": "site_ownership_confirmed", "value": identity.get("ownership_basis")},
                {"type": "single_advert_rules", "value": check["method"]},
            ],
            "acquisition_mode": "permitted_public_page",
            "rights_status": "approved",
            "source_class": "company_site",
            "evidence_span": str(page.get("title") or "")[:1200],
            "strategy": "company_site_single_job_advert",
        })
    return results, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.profiles).read_text(encoding="utf-8").splitlines() if line.strip()]
    items, candidates, rejected, companies = [], 0, 0, set()
    for profile in rows:
        found, stats = observations(profile)
        candidates += stats["candidates"]
        rejected += stats["rejected"]
        if found:
            companies.add(profile["organisation_number"])
        items.extend(found)

    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in items), encoding="utf-8")
    report = {
        "connector": "company_site_single_job_advert_v1",
        "profiles_seen": len(rows),
        "candidate_career_pages": candidates,
        "rejected_not_single_advert": rejected,
        "published_adverts": len(items),
        "companies_with_an_advert": len(companies),
        "claim_boundary": (
            "One advert per captured page, only from a site whose ownership is confirmed "
            "for this organisation number. Careers landing pages, national job-portal "
            "searches, off-domain adverts, and adverts naming another employer are rejected."
        ),
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
