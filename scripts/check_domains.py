#!/usr/bin/env python3
"""Report pack entries whose name no longer resolves. ADVISORY ONLY.

What this can and cannot tell you, measured rather than assumed:

  • It CAN spot a name the DNS authority says is gone (NXDOMAIN).
  • It CANNOT spot a retired service whose domain still answers DNS — the
    common case. `bard.google.com` is the example that started this: the
    product is long gone, the name resolves fine.
  • Failure to resolve is NOT the judge. getaddrinfo fails identically for a
    zone that is gone and for a live zone whose apex simply carries no address
    record — and suffix entries are full of the latter (`twimg.com`,
    `microsoftonline.com`, every CDN-only domain). Measured on real data:
    resolution alone flagged 230 entries, of which 32 were actually gone.
    Only the authoritative rcode tells them apart, so a name is reported only
    when dig confirms NXDOMAIN.
  • An earlier version also flagged "resolves, but every request redirects
    elsewhere", reasoning that a redirect means the service moved. On real
    data that produced 74 findings against 2 real ones, and nearly all 74 were
    entries that MUST stay: `fbcdn.net`, `youtu.be`, `t.me`, `sndcdn.com`,
    `pinimg.com`. Traffic genuinely goes to those hosts; only a browser's HEAD
    request gets redirected. That check is gone. A checker that cries wolf
    daily is worse than no checker — it trains everyone to ignore the issue.

So: findings are a prompt to look, never an instruction to delete. A name can
be NXDOMAIN from one network and healthy from another, and a suffix entry
matches subdomains — an apex with no record of its own is perfectly normal.

    python3 scripts/check_domains.py --json report.json

Exits 0 with findings; the workflow decides what to do with them.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import socket
import subprocess
import sys

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


def nxdomain(name: str) -> bool:
    try:
        out = subprocess.run(
            ["dig", "+time=3", "+tries=2", "SOA", name],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return False  # tool failure: assume healthy, never cry wolf
    return "status: NXDOMAIN" in out


def probe(domain: str) -> dict | None:
    # A routing suffix matches subdomains, so the apex having no record of its
    # own means nothing. Screen cheaply first (apex AND the conventional www.
    # host both absent), then report only what the authority confirms is gone.
    if resolves(domain) or resolves(f"www.{domain}"):
        return None
    if not nxdomain(domain):
        return None
    return {"domain": domain, "status": "nxdomain"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    entries: list[tuple[str, str]] = []  # (pack id, domain)
    for path in sorted(SOURCES.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        # Keywords are substrings, not hosts — nothing to resolve.
        for d in pack.get("suffixes") or []:
            entries.append((pack["id"], d))

    findings: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        futures = {pool.submit(probe, d): (pid, d) for pid, d in entries}
        for fut in concurrent.futures.as_completed(futures):
            pid, _ = futures[fut]
            hit = fut.result()
            if hit:
                findings.append({"pack": pid, **hit})

    findings.sort(key=lambda f: (f["pack"], f["domain"]))
    for f in findings:
        print(f"{f['pack']}: {f['domain']} [{f['status']}]")
    print(f"\nchecked {len(entries)} domains, {len(findings)} to review",
          file=sys.stderr)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(findings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
