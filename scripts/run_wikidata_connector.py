#!/usr/bin/env python3
"""Exact-entity Wikidata connector for Signalpost.

Matches Norwegian companies to Wikidata items via the authoritative external-ID
property P2333 ("Norwegian organisation number"), not name/fuzzy matching, so
identity is exact by construction. Wikidata content is CC0; the Query Service
is Wikidata's own official public API for this data -- acquisition_mode is
therefore "official_api" and rights_status "approved".

Coverage is expected to be sparse: only larger/notable companies tend to have
Wikidata items. Run against a sample skewed toward larger employers for a
meaningful hit rate, not a uniform random sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "SignalpostResearchPOC/1.0 (https://builderr.ai; bounded qualification run)"

# Social/profile properties worth recording when present, all official Wikidata
# external-id / URL properties with clear semantics.
LINK_PROPERTIES = {
    "P856": ("company_site", "company_profile"),
    "P2002": ("x", "profile_handle"),
    "P2013": ("facebook", "profile_handle"),
    "P2003": ("instagram", "profile_handle"),
    "P2397": ("youtube", "profile_handle"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_query(orgs: list[str]) -> str:
    values = " ".join(f'"{org}"' for org in orgs)
    props = " ".join(f"OPTIONAL {{ ?item wdt:{prop} ?{name}_{i} . }}" for i, (prop, (name, _)) in enumerate(LINK_PROPERTIES.items()))
    return f"""
    SELECT ?orgnr ?item ?itemLabel {" ".join(f"?{name}_{i}" for i, (prop, (name, _)) in enumerate(LINK_PROPERTIES.items()))} WHERE {{
      VALUES ?orgnr {{ {values} }}
      ?item wdt:P2333 ?orgnr .
      {props}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,no,nb". }}
    }}
    """


def run_query(orgs: list[str]) -> list[dict]:
    query = build_query(orgs)
    url = f"{ENDPOINT}?{urllib.parse.urlencode({'query': query})}"
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())["results"]["bindings"]


def to_observations(bindings_for_org: list[dict], retrieved_at: str) -> list[dict]:
    """Build observations for one org from ALL its bindings.

    Multiple parallel OPTIONALs in the SPARQL query produce a cross-product row
    per combination of multi-valued properties (e.g. two Facebook links, three
    YouTube links -> 6 rows), not one row per company. We must union each
    property's distinct values across all bindings for the org, not treat each
    binding as an independent company match -- otherwise a multi-valued property
    both duplicates the profile observation and silently drops sibling values.
    """
    first = bindings_for_org[0]
    org = first["orgnr"]["value"]
    item_url = first["item"]["value"]
    item_id = item_url.rsplit("/", 1)[-1]
    label = first.get("itemLabel", {}).get("value", "")
    digest = hashlib.sha256(json.dumps(bindings_for_org, sort_keys=True).encode()).hexdigest()
    common = {
        "organisation_number": org,
        "platform": "wikidata",
        "retrieved_at": retrieved_at,
        "content_sha256": digest,
        "exact_entity": True,
        "identity_proof": [{"type": "wikidata_property_p2333_organisation_number", "value": org}],
        "acquisition_mode": "official_api",
        "rights_status": "approved",
        "source_class": "official_public_dataset",
    }
    observations = [{
        **common,
        "id": f"wikidata-profile-{org}-{item_id}",
        "signal_type": "company_profile",
        "source_url": item_url,
        "evidence_span": label,
        "wikidata_id": item_id,
        "label": label,
    }]
    for i, (prop, (platform, signal_type)) in enumerate(LINK_PROPERTIES.items()):
        values = {
            binding[f"{platform}_{i}"]["value"]
            for binding in bindings_for_org
            if binding.get(f"{platform}_{i}", {}).get("value")
        }
        for value in sorted(values):
            observations.append({
                **common,
                "id": f"wikidata-link-{org}-{prop}-{hashlib.sha256(value.encode()).hexdigest()[:12]}",
                "platform": platform,
                "signal_type": signal_type,
                "source_url": value if value.startswith("http") else item_url,
                "evidence_span": f"Wikidata {prop} claim on {label}",
                "declared_value": value,
            })
    return observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organisations", required=True, help="JSONL with organisation_number per line")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--batch-size", type=int, default=150)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    orgs = [
        json.loads(line)["organisation_number"]
        for line in Path(args.organisations).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    all_observations: list[dict] = []
    matched_orgs: set[str] = set()
    errors = []
    batches = batched(orgs, args.batch_size)
    for index, batch in enumerate(batches, start=1):
        retrieved_at = utc_now()
        try:
            bindings = run_query(batch)
            by_org: dict[str, list[dict]] = {}
            for binding in bindings:
                by_org.setdefault(binding["orgnr"]["value"], []).append(binding)
            for org, org_bindings in by_org.items():
                all_observations.extend(to_observations(org_bindings, retrieved_at))
                matched_orgs.add(org)
        except Exception as exc:
            errors.append({"batch": index, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        print(f"  batch {index}/{len(batches)}: {len(matched_orgs)} matched so far", end="\r")
        if index < len(batches):
            time.sleep(args.delay)

    print()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in all_observations), encoding="utf-8")
    report = {
        "connector": "wikidata_exact_orgnr_p2333_v1",
        "companies_queried": len(orgs),
        "companies_matched": len(matched_orgs),
        "hit_rate": round(len(matched_orgs) / len(orgs), 4) if orgs else 0,
        "observations": len(all_observations),
        "batches": len(batches),
        "errors": errors,
        "claim_boundary": "Exact-entity match via authoritative external-ID property P2333. CC0 data, official Wikidata Query Service.",
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
