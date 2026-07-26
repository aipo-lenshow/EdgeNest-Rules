#!/usr/bin/env python3
"""Keep the hand-kept overlay (`add`) from silently becoming the new rot.

Two ways `add` grows stale, both invisible without this:

  1. **Upstream caught up.** An entry we added ourselves later shows up in the
     upstream category too. Keeping our copy changes nothing about routing, but
     it means the entry can never be retired: upstream dropping it has no
     effect, because the local copy keeps it alive.
  2. **The name died.** An entry only we carry, whose domain no longer resolves
     at all. Upstream cleanup can't reach it — it isn't upstream's.

So: drop from `add` anything upstream already covers, then drop anything left
that no longer resolves. Both only ever touch `add` — upstream-derived entries
are never edited here, and `exclude` is left alone (it is a deliberate opinion
about an entry we do NOT want, and stays valid whether or not the name lives).

    python3 scripts/prune_overlay.py --dry-run
    python3 scripts/prune_overlay.py --skip-dns   # dedupe only, no lookups

DNS is advisory by nature — see check_domains.py's header. A name is only
dropped when the apex AND `www.` both fail to resolve, and a transient resolver
error counts as healthy. Run it from a network that can actually reach the
open internet, or the "dead" list is just a list of what your DNS is blocking.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sync_upstream import (  # noqa: E402
    UPSTREAM_TARBALL,
    fetch_upstream,
    parse_category,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"


def resolves(name: str) -> bool:
    try:
        socket.getaddrinfo(name, None)
        return True
    except socket.gaierror:
        return False
    except Exception:
        return True  # transient failure: assume healthy, never cry wolf


def zone_exists(domain: str) -> bool:
    """Is the DNS zone still delegated (NS/SOA present)?

    The signal that matters for a *suffix* entry. Plenty of live vendors carry
    no A record on the apex and serve everything from subdomains — judging them
    by the apex alone marks a working rule dead. A zone that is gone is gone.
    Any failure of the tool itself counts as alive: never cry wolf.
    """
    for rr in ("NS", "SOA"):
        try:
            out = subprocess.run(
                ["dig", "+short", "+time=3", "+tries=2", rr, domain],
                capture_output=True, text=True, timeout=12,
            ).stdout.strip()
        except Exception:
            return True
        if out:
            return True
    return False


def dns_is_trustworthy() -> bool:
    """Refuse to judge liveness through a tunnel that fabricates answers.

    A fake-ip resolver (the client's own, 198.18.0.0/15) answers EVERY name,
    and answers differently depending on our own routing rules — so a dead
    domain looks alive, a live one looks dead, and which is which depends on
    the very rules being checked. Measured, not assumed: a nonsense name that
    resolves means the resolver is inventing answers.
    """
    probe = "edgenest-nonexistent-probe-zq7x1.example"
    try:
        socket.getaddrinfo(probe, None)
    except socket.gaierror:
        return True
    except Exception:
        return True
    return False


def is_dead(domain: str) -> bool:
    if resolves(domain) or resolves(f"www.{domain}"):
        return False
    return not zone_exists(domain)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-dns", action="store_true")
    ap.add_argument("--url", default=UPSTREAM_TARBALL)
    args = ap.parse_args()

    raw, _ = fetch_upstream(args.url)

    packs: list[tuple[pathlib.Path, dict]] = []
    for path in sorted(SOURCES.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if pack.get("upstream") and pack.get("add"):
            packs.append((path, pack))

    # ── 1. drop what upstream already carries ────────────────────────────────
    to_check: dict[str, list[str]] = {}  # domain -> pack ids still holding it
    dedup_total = 0
    for path, pack in packs:
        upstream_s: set[str] = set()
        upstream_k: set[str] = set()
        for cat in pack["upstream"]:
            s, k, _ = parse_category(cat, raw)
            upstream_s |= s
            upstream_k |= k
        add = pack["add"]
        kept_s = [d for d in add.get("suffixes", []) if d not in upstream_s]
        kept_k = [d for d in add.get("keywords", []) if d not in upstream_k]
        dropped = (len(add.get("suffixes", [])) - len(kept_s)) + (
            len(add.get("keywords", [])) - len(kept_k)
        )
        dedup_total += dropped
        add["suffixes"], add["keywords"] = kept_s, kept_k
        print(f"{pack['id']}: add {len(kept_s) + len(kept_k)} left "
              f"(−{dropped} now covered upstream)")
        for d in kept_s:
            to_check.setdefault(d, []).append(pack["id"])

    # ── 2. drop what no longer resolves ──────────────────────────────────────
    dead: set[str] = set()
    if not args.skip_dns and to_check and not dns_is_trustworthy():
        print("\nDNS here answers for names that do not exist (a tunnel with "
              "fake-ip is in the path) — liveness cannot be judged from this "
              "machine. Re-run with --skip-dns, or run it somewhere with a "
              "plain resolver.", file=sys.stderr)
        sys.exit(2)
    if not args.skip_dns and to_check:
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            futures = {pool.submit(is_dead, d): d for d in to_check}
            for fut in concurrent.futures.as_completed(futures):
                if fut.result():
                    dead.add(futures[fut])
        if dead:
            print("\nno longer resolves — dropping from add:")
            for d in sorted(dead):
                print(f"  {d}  ({', '.join(to_check[d])})")
        else:
            print("\nevery remaining add entry still resolves")

    for path, pack in packs:
        add = pack["add"]
        add["suffixes"] = [d for d in add["suffixes"] if d not in dead]
        if not args.dry_run:
            path.write_text(
                json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    left = sum(len(p["add"]["suffixes"]) + len(p["add"]["keywords"]) for _, p in packs)
    print(f"\noverlay: −{dedup_total} duplicate, −{len(dead)} dead, {left} genuinely ours")
    if args.dry_run:
        print("(dry run — nothing written)")


if __name__ == "__main__":
    main()
