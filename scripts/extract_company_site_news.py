#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.content_rules import validate_news_item  # noqa: E402


NEWS_PATH = re.compile(r"/(?:news|press|aktuelt|nyheter|artikler|blog)(?:/|$)", re.I)


def observation(profile: dict) -> dict | None:
    website = (profile.get("evidence") or {}).get("website") or {}
    value = website.get("value") or {}
    identity = value.get("identity_assessment") or {}
    if website.get("status") != "available" or not identity.get("publishable"):
        return None
    # A news post is read out of the site body, so it speaks for whoever owns
    # the site. A parent group's or shared brand site that merely mentions this
    # company cannot supply its activity.
    if not identity.get("own_site_confirmed"):
        return None
    pages = [
        page for page in (value.get("pages") or [])
        if NEWS_PATH.search(urlparse(str(page.get("url") or "")).path)
    ]
    if not pages:
        return None
    # Prefer a real dated article. Section indexes, navigation labels, product
    # pages, and anything carrying only a modified timestamp are rejected
    # outright rather than published as activity.
    validated = [(page, validate_news_item(page)) for page in pages]
    accepted = [(page, check) for page, check in validated if check["publishable"]]
    if not accepted:
        return None
    accepted.sort(key=lambda item: (item[1]["published_at"] or "", str(item[0].get("url") or "")), reverse=True)
    page, check = accepted[0]
    url = str(page.get("url") or "")
    digest = str(page.get("content_sha256") or "")
    if len(digest) != 64:
        return None
    org = str(profile["organisation_number"])
    title = str(page.get("title") or "").strip()
    return {
        "id": "company-site-news-" + hashlib.sha256(f"{org}|{url}".encode()).hexdigest()[:24],
        "organisation_number": org,
        "platform": "company_site",
        "signal_type": "public_post",
        "source_url": url,
        "retrieved_at": website.get("retrieved_at"),
        "published_at": check["published_at"],
        "content_sha256": digest,
        "exact_entity": True,
        "identity_proof": [
            {"type": "website_identity_gate", "score": identity.get("score"), "method": identity.get("method")},
            {"type": "site_ownership_confirmed", "value": identity.get("ownership_basis")},
            {"type": "publication_date_basis", "value": check["date_basis"]},
        ],
        "acquisition_mode": "permitted_public_page",
        "rights_status": "approved",
        "source_class": "company_site",
        "evidence_span": title[:1200],
        "metrics": {
            "candidate_news_pages": len(pages),
            "accepted_after_rules": len(accepted),
            "interpretation": "Company-owned dated post; not independent sentiment.",
        },
        "strategy": "company_site_activity",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract company-owned activity from exact-site bounded news pages.")
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    profiles = [json.loads(line) for line in Path(args.profiles).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [item for profile in profiles if (item := observation(profile))]
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    report = {
        "connector": "exact_company_site_news_activity_v1",
        "profiles": len(profiles),
        "companies_with_activity": len(rows),
        "observations": len(rows),
        "claim_boundary": "Company-owned activity only; never treated as independent sentiment.",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
