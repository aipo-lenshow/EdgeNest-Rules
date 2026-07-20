#!/usr/bin/env python3
"""Decide whether a freshly built catalog is safe to publish unattended.

The daily sync exists so nobody has to watch it. That is exactly why it needs a
brake: an upstream mistake — a category emptied, a merge that drops half a list
— would otherwise reach every device's routing table within the day, silently.

So: small movements publish themselves; anything large stops and asks. The
thresholds are about SHAPE, not correctness (no script can judge correctness):

  • a pack losing more than MAX_LOSS entries, or more than MAX_LOSS_RATIO of
    itself, is the signature of an upstream breakage, not of curation;
  • a pack that empties is always wrong — the client refuses such a catalog
    anyway, so publishing it would ship a catalog nobody can load;
  • total growth beyond MAX_GROWTH_RATIO usually means a mapping picked up a
    vendor's whole surface rather than one product.

    python3 scripts/guard_changes.py --new dist/catalog.json --old previous.json
      exit 0  → safe, publish
      exit 10 → hold: report on stdout, for an issue body
      exit 1  → the inputs themselves are broken

The first build (no previous catalog) always passes: there is nothing to
compare against, and refusing would mean the repo can never bootstrap.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

MAX_LOSS = 25          # entries a single pack may lose unattended
MAX_LOSS_RATIO = 0.30  # …or this share of itself, whichever is smaller
MAX_GROWTH_RATIO = 3.0 # total catalog growth in one run


def entries(pack: dict) -> set[str]:
    return {f"s:{v}" for v in pack.get("suffixes", [])} | {
        f"k:{v}" for v in pack.get("keywords", [])
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--old")
    args = ap.parse_args()

    try:
        new = json.loads(pathlib.Path(args.new).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read the new catalog: {e}")

    old_path = pathlib.Path(args.old) if args.old else None
    if not old_path or not old_path.exists() or not old_path.read_text().strip():
        print("no previous catalog — nothing to compare, publishing")
        return
    try:
        old = json.loads(old_path.read_text(encoding="utf-8"))
    except ValueError:
        print("previous catalog is unreadable — treating this as a bootstrap")
        return

    old_packs = {p["id"]: p for p in old.get("packs", [])}
    new_packs = {p["id"]: p for p in new.get("packs", [])}

    holds: list[str] = []
    lines: list[str] = []
    old_total = new_total = 0

    for pid in sorted(set(old_packs) | set(new_packs)):
        o = entries(old_packs[pid]) if pid in old_packs else set()
        n = entries(new_packs[pid]) if pid in new_packs else set()
        old_total += len(o)
        new_total += len(n)
        gained, lost = n - o, o - n
        if not gained and not lost:
            continue
        lines.append(f"- **{pid}**: {len(o)} → {len(n)} (+{len(gained)} −{len(lost)})")
        if lost:
            lines.append(f"  - removed: {', '.join(sorted(x[2:] for x in lost)[:40])}")
        if gained:
            lines.append(f"  - added: {', '.join(sorted(x[2:] for x in gained)[:40])}")

        if pid not in new_packs:
            holds.append(f"pack `{pid}` disappeared entirely")
            continue
        if not n:
            holds.append(f"pack `{pid}` is empty")
            continue
        if o and len(lost) > min(MAX_LOSS, max(1, int(len(o) * MAX_LOSS_RATIO))):
            holds.append(
                f"pack `{pid}` lost {len(lost)} of {len(o)} entries "
                f"(limit {min(MAX_LOSS, max(1, int(len(o) * MAX_LOSS_RATIO)))})"
            )

    if old_total and new_total > old_total * MAX_GROWTH_RATIO:
        holds.append(
            f"catalog grew {old_total} → {new_total} "
            f"(more than {MAX_GROWTH_RATIO}×)"
        )

    print(f"### catalog {old.get('version','?')} → {new.get('version','?')}")
    print(f"total entries: {old_total} → {new_total}\n")
    print("\n".join(lines) if lines else "no content change")

    if holds:
        print("\n### held back — needs a look\n")
        for h in holds:
            print(f"- {h}")
        print(
            "\nNothing was published. Review the diff above; if it is legitimate, "
            "re-run the workflow manually (`workflow_dispatch`) — a manual run "
            "publishes regardless of these limits."
        )
        sys.exit(10)


if __name__ == "__main__":
    main()
