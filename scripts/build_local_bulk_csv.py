#!/usr/bin/env python3
"""Build a small gzip CSV shaped like the BRREG bulk export, from the live per-entity API.

Local dev/testing helper only: the national bulk download (~147MB) has been unreliable over
this network. iter_bulk() only needs a gzip CSV with the right columns for the requested
organisation numbers, so we fetch those rows individually from the same authoritative live
API and assemble an equivalent file. Not a substitute for the full file in the official run.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "SignalpostResearchPOC/1.0 (https://builderr.ai; bounded qualification run)"
FIELDNAMES = [
    "organisasjonsnummer", "navn", "organisasjonsform.kode", "antallAnsatte",
    "konkurs", "underAvvikling", "forretningsadresse.kommune",
    "forretningsadresse.kommunenummer", "naeringskode1.kode",
    "naeringskode1.beskrivelse", "hjemmeside", "sisteInnsendteAarsregnskap",
]


def fetch(org: str) -> dict | None:
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"  {org}: HTTP {exc.code}")
        return None
    except Exception as exc:
        print(f"  {org}: {type(exc).__name__}: {exc}")
        return None


def to_row(entity: dict) -> dict:
    address = entity.get("forretningsadresse") or {}
    industry = entity.get("naeringskode1") or {}
    form = entity.get("organisasjonsform") or {}
    return {
        "organisasjonsnummer": entity.get("organisasjonsnummer", ""),
        "navn": entity.get("navn", ""),
        "organisasjonsform.kode": form.get("kode", ""),
        "antallAnsatte": entity.get("antallAnsatte", ""),
        "konkurs": str(bool(entity.get("konkurs"))).lower(),
        "underAvvikling": str(bool(entity.get("underAvvikling"))).lower(),
        "forretningsadresse.kommune": address.get("kommune", ""),
        "forretningsadresse.kommunenummer": address.get("kommunenummer", ""),
        "naeringskode1.kode": industry.get("kode", ""),
        "naeringskode1.beskrivelse": industry.get("beskrivelse", ""),
        "hjemmeside": entity.get("hjemmeside", ""),
        "sisteInnsendteAarsregnskap": entity.get("sisteInnsendteAarsregnskap", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organisations", required=True, help="JSONL batch with organisation_number per line")
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    orgs = [
        json.loads(line)["organisation_number"]
        for line in Path(args.organisations).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rows, missing = [], []
    for index, org in enumerate(orgs, start=1):
        entity = fetch(org)
        if entity is None:
            missing.append(org)
        else:
            rows.append(to_row(entity))
        if index < len(orgs):
            time.sleep(args.delay)
        print(f"  fetched {index}/{len(orgs)}", end="\r")

    print(f"\nfetched {len(rows)} rows, {len(missing)} missing: {missing}")
    with gzip.open(args.output, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
