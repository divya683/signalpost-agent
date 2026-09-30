#!/usr/bin/env python3
"""Build a deterministic, stratified validation corpus from the company universe.

Stratifies by the same stratum() bucketing used elsewhere in the codebase
(legal form x employee band x active/adverse status x web/no-web), so the
sample is genuinely representative rather than favorably biased toward
companies likely to have external coverage. Reproducible: same universe file
+ same seed always yields the same selected organisation numbers.
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.sampling import stratum  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", required=True, help="signalpost-universe.jsonl.gz")
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = []
    with gzip.open(args.universe, "rt", encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    rng = random.Random(args.seed)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[stratum(r)].append(r)

    per_bucket = max(1, args.count // len(buckets))
    selected = []
    for items in buckets.values():
        rng.shuffle(items)
        selected.extend(items[:per_bucket])
    rng.shuffle(selected)
    selected = selected[: args.count]

    with open(args.output, "w", encoding="utf-8") as f:
        for r in selected:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps({
        "universe_rows": len(rows),
        "strata": len(buckets),
        "requested": args.count,
        "selected": len(selected),
        "seed": args.seed,
    }, indent=2))


if __name__ == "__main__":
    main()
