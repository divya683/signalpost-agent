#!/usr/bin/env python3
"""Exact-orgnr connector for DIBK's central-approval register (Sentral Godkjenning).

DIBK (Direktoratet for byggkvalitet, the Norwegian Building Authority) runs a
free, open REST API over the register of construction enterprises holding
central government approval -- named directly in the challenge's own
permitted-sources list. No signup, no API key, robots.txt is unrestricted.

Matches by exact organisation number against DIBK's own enterprise id, so
identity is exact by construction, the same guarantee the Wikidata connector
relies on. Coverage is inherently narrow: only construction-trade companies
can hold this approval at all, so most input companies will correctly get
no match rather than a false one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "SignalpostResearchPOC/1.0 (https://builderr.ai; bounded qualification run)"
ENDPOINT = "https://sgregister.dibk.no/api/enterprises/{org}.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch(org: str) -> dict | None:
    url = ENDPOINT.format(org=org)
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.sgpub.v1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def to_observation(org: str, record: dict, retrieved_at: str) -> dict:
    status = record.get("status") or {}
    areas = record.get("valid_approval_areas") or []
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    area_summary = ", ".join(sorted({a.get("subject_area", "") for a in areas if a.get("subject_area")})[:6])
    if status.get("approved"):
        span = f"Central approval active, valid until {status.get('approval_period_to', 'unknown')}: {area_summary}"
    else:
        span = "Registered in the central-approval register but no currently active approval"
    return {
        "id": f"dibk-credential-{org}-{digest[:16]}",
        "organisation_number": org,
        "platform": "dibk",
        "signal_type": "credential",
        "source_url": f"https://sgregister.dibk.no/enterprises/{org}",
        "retrieved_at": retrieved_at,
        "content_sha256": digest,
        "exact_entity": True,
        "identity_proof": [{"type": "dibk_exact_organisation_number_lookup", "value": org}],
        "acquisition_mode": "official_api",
        "rights_status": "approved",
        "source_class": "official_credential_register",
        "evidence_span": span,
        "approved": bool(status.get("approved")),
        "approval_period_to": status.get("approval_period_to"),
        "approval_certificate_url": status.get("approval_certificate"),
        "approval_area_count": len(areas),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organisations", required=True, help="JSONL with organisation_number per line")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    orgs = [
        json.loads(line)["organisation_number"]
        for line in Path(args.organisations).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    observations, errors = [], []
    matched = 0
    for index, org in enumerate(orgs, start=1):
        try:
            record = fetch(org)
            if record is not None:
                observations.append(to_observation(org, record, utc_now()))
                matched += 1
        except Exception as exc:
            errors.append({"organisation_number": org, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        print(f"  {index}/{len(orgs)}: {matched} matched so far", end="\r")
        if index < len(orgs):
            time.sleep(args.delay)

    print()
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations), encoding="utf-8")
    report = {
        "connector": "dibk_central_approval_exact_orgnr_v1",
        "companies_queried": len(orgs),
        "companies_matched": matched,
        "hit_rate": round(matched / len(orgs), 4) if orgs else 0,
        "observations": len(observations),
        "errors": errors,
        "claim_boundary": "Exact-entity match via DIBK's own enterprise lookup by organisation number. Official government API, open robots.txt, no signup.",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
