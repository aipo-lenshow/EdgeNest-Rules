#!/usr/bin/env python3
"""The month's checklist: what the daily automation cannot decide for itself.

The daily sync follows upstream, and the guard stops it when the diff looks
like an accident. Neither can judge *meaning* — whether a pack still matches
what people do, whether a hand-kept vendor list has fallen behind, whether an
entry only we carry is still worth carrying. That is the standing manual job,
and this prints its current state so the monthly issue is a list of specific
things rather than a reminder to "check the rules".

    python3 scripts/monthly_report.py > report.md
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"


def main() -> None:
    hand_kept: list[tuple[str, int]] = []
    followed: list[tuple[str, int, int, list[str]]] = []
    excludes: list[tuple[str, list[str]]] = []
    total = 0

    for path in sorted(SOURCES.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        count = len(pack.get("suffixes", [])) + len(pack.get("keywords", []))
        total += count
        if not pack.get("upstream"):
            hand_kept.append((pack["id"], count))
            continue
        add = pack.get("add") or {}
        own = len(add.get("suffixes", [])) + len(add.get("keywords", []))
        followed.append((pack["id"], count, own, pack["upstream"]))
        if pack.get("exclude"):
            excludes.append((pack["id"], pack["exclude"]))

    print("The daily sync keeps the followed packs current on its own. These are")
    print("the parts it cannot judge — worth twenty minutes once a month.\n")

    print("## 1. Hand-kept packs — nobody upstream is watching these\n")
    print("No upstream category matches them at a usable granularity (the vendor")
    print("categories cover each vendor's entire surface, China-served endpoints")
    print("included). They only change when someone changes them.\n")
    for pid, count in hand_kept:
        print(f"- [ ] **{pid}** — {count} entries: still complete? anything retired?")

    print("\n## 2. The overlay — entries only we carry\n")
    print("Upstream may have grown a category for a service we were carrying by")
    print("hand. When it has, drop ours: a duplicate can never be retired, since")
    print("upstream removing it leaves our copy behind.\n")
    print("```")
    print("python3 scripts/prune_overlay.py --dry-run   # needs a plain resolver")
    print("```\n")
    for pid, count, own, cats in followed:
        if own:
            print(f"- [ ] **{pid}** — {own} of {count} are ours "
                  f"(follows: {', '.join(cats)})")

    if excludes:
        print("\n## 3. Deliberate exclusions — still deliberate?\n")
        print("Each of these is us overruling upstream. Worth re-reading: the")
        print("reason may have expired.\n")
        for pid, items in excludes:
            print(f"- [ ] **{pid}**: {', '.join(items)}")

    print("\n## 4. Coverage\n")
    print("- [ ] Any service you used this month that routed the wrong way?")
    print("- [ ] Any pack that no longer matches what people actually do?")
    print("- [ ] The standing `domain-review` issue — anything real in it?")
    print(f"\nCatalog today: {total} entries across "
          f"{len(hand_kept) + len(followed)} packs "
          f"({len(followed)} follow upstream, {len(hand_kept)} hand-kept).")


if __name__ == "__main__":
    main()
