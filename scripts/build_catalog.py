#!/usr/bin/env python3
"""Assemble sources/*.json into the catalog document clients download.

The catalog is the whole product of this repo: one file, published on the
`rule-set` branch, carrying both the pack metadata and the domain lists. Packs
travel in SOURCE form (suffix / keyword lists) rather than as a compiled .srs —
clients let the user retarget individual domains, which a compiled set can't
express.

    python3 scripts/build_catalog.py --out dist/catalog.json

Ordering is explicit (ORDER below), not alphabetical: it's the order the packs
appear in the client's list, and grouping AI / platform / lifestyle together is
the only thing that makes a 16-row switch list readable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"

# Display order in the client. A pack missing from here still ships (appended,
# so a new pack is never silently dropped) — it just lands at the end until
# someone places it.
ORDER = [
    "ai_core",
    "ai_ide",
    "ai_emerging",
    "ai_media",
    "ai_billing",
    "apple_overseas",
    "ms_services",
    "google_services",
    "dev_infra",
    "ai_cn_direct",
    "short_video",
    "streaming",
    "social_app",
    "forum",
    "knowledge",
    "gaming",
]

REQUIRED = ("id", "nameZh", "nameEn", "defaultOutbound")


def load_pack(path: pathlib.Path) -> dict:
    pack = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED:
        if not pack.get(key):
            sys.exit(f"{path.name}: missing required field {key!r}")
    if pack["id"] != path.stem:
        sys.exit(f"{path.name}: id {pack['id']!r} does not match the file name")
    if pack["defaultOutbound"] not in ("proxy", "direct"):
        sys.exit(f"{path.name}: defaultOutbound must be 'proxy' or 'direct'")
    suffixes = sorted(set(pack.get("suffixes") or []))
    keywords = sorted(set(pack.get("keywords") or []))
    if not suffixes and not keywords:
        # An empty pack renders as a switch that routes nothing. Clients refuse
        # a catalog containing one, so catch it here where the diff is visible.
        sys.exit(f"{path.name}: pack has no entries")
    return {
        "id": pack["id"],
        "nameZh": pack["nameZh"],
        "nameEn": pack["nameEn"],
        "descZh": pack.get("descZh", ""),
        "descEn": pack.get("descEn", ""),
        "defaultOutbound": pack["defaultOutbound"],
        "defaultOn": bool(pack.get("defaultOn")),
        "suffixes": suffixes,
        "keywords": keywords,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist/catalog.json")
    args = ap.parse_args()

    packs = {p.stem: load_pack(p) for p in sorted(SOURCES.glob("*.json"))}
    ordered = [packs.pop(k) for k in ORDER if k in packs]
    ordered += [packs[k] for k in sorted(packs)]  # unplaced packs, never dropped

    # Cross-pack duplicate check: the client merges packs sharing an outbound
    # into one route rule, so a domain in two packs with DIFFERENT outbounds is
    # a coin flip at match time. Same-outbound duplicates are merely redundant.
    seen: dict[str, tuple[str, str]] = {}
    for pack in ordered:
        for entry in pack["suffixes"] + pack["keywords"]:
            prev = seen.get(entry)
            if prev and prev[1] != pack["defaultOutbound"]:
                sys.exit(
                    f"{entry!r} appears in {prev[0]} ({prev[1]}) and "
                    f"{pack['id']} ({pack['defaultOutbound']}) — conflicting routing"
                )
            seen[entry] = (pack["id"], pack["defaultOutbound"])

    now = dt.datetime.now(dt.timezone.utc)
    # Date PLUS a digest of the content. Clients compare this string to decide
    # whether a download is worth writing, so a bare date would make the second
    # change on any given day invisible to every device — the update would be
    # refused as "same version" and nobody would see why. It is also what the
    # publish step compares to decide whether there is anything to publish —
    # the file itself is never byte-identical between runs, since generatedAt
    # moves every time.
    digest = hashlib.sha256(
        json.dumps(ordered, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:8]
    catalog = {
        "schema": 1,
        "version": f"{now:%Y%m%d}.{digest}",
        "generatedAt": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "packs": ordered,
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = sum(len(p["suffixes"]) + len(p["keywords"]) for p in ordered)
    print(f"{out}: {len(ordered)} packs, {total} entries")


if __name__ == "__main__":
    main()
