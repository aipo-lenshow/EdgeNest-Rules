#!/usr/bin/env python3
"""Align pack contents with the upstream community lists.

Why this exists: a hand-kept domain list rots quietly. Services move, new ones
appear, and dead names sit in the list forever because nobody is watching —
`bard.google.com` survived in our AI pack long after the product shut down. The
community keeps a categorised list up to date every day; the sane move is to
follow it and keep only our own opinions on top.

    upstream category ∪ pack["add"] − pack["exclude"]  →  pack["suffixes"/"keywords"]

So `suffixes` / `keywords` in sources/*.json are GENERATED for any pack that
declares `upstream`. Edit `add` / `exclude` instead — a hand edit to the
generated lists is silently reverted on the next sync.

Source: v2fly/domain-list-community (MIT). Its format:

    example.com                 bare line = domain suffix
    domain:example.com          same thing, explicit
    full:host.example.com       exact host
    keyword:exam                substring match
    regexp:^ex.*\\.com$          regex
    include:other-category      splice in another category
    example.com @ads @cn        attributes (tags) on an entry
    include:google @ads         include ONLY entries tagged @ads

We map: domain/full → suffix, keyword → keyword, regexp → dropped (the client
has no regex matcher, and a silently ignored rule is worse than an absent one —
dropped ones are counted and reported).

    python3 scripts/sync_upstream.py                 # sync + report
    python3 scripts/sync_upstream.py --dry-run       # report only, no writes
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"

UPSTREAM_REPO = "v2fly/domain-list-community"
UPSTREAM_TARBALL = f"https://codeload.github.com/{UPSTREAM_REPO}/tar.gz/refs/heads/master"

# A suffix this broad would swallow half the internet if a category ever grew
# one by accident. Refuse rather than publish it.
FORBIDDEN_SUFFIXES = {"com", "net", "org", "io", "cn", "co", "app", "dev", "ai"}


def fetch_upstream(url: str) -> tuple[dict[str, list[str]], str]:
    """Download the upstream tree once and return {category: raw lines}.

    One tarball instead of a request per category: 1500 categories over the API
    would be rate-limited within a minute, and a half-fetched tree would produce
    a half-correct catalog — the worst outcome available.
    """
    with urllib.request.urlopen(url, timeout=120) as resp:
        blob = resp.read()
    data: dict[str, list[str]] = {}
    root_name = ""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/")
            if len(parts) < 3 or parts[1] != "data":
                continue
            root_name = root_name or parts[0]
            f = tar.extractfile(member)
            if f is None:
                continue
            data["/".join(parts[2:])] = f.read().decode("utf-8").splitlines()
    if not data:
        sys.exit("upstream tarball contained no data/ files — refusing to sync")
    return data, root_name


def parse_category(
    name: str,
    raw: dict[str, list[str]],
    want_attr: str | None = None,
    seen: set[str] | None = None,
) -> tuple[set[str], set[str], int]:
    """Resolve one category to (suffixes, keywords, dropped_regexps).

    `seen` breaks include cycles: upstream is a graph, not a tree, and one bad
    day upstream must not become an infinite loop here.
    """
    seen = seen if seen is not None else set()
    if name in seen:
        return set(), set(), 0
    seen.add(name)
    lines = raw.get(name)
    if lines is None:
        sys.exit(f"upstream category {name!r} does not exist — fix the mapping")

    suffixes: set[str] = set()
    keywords: set[str] = set()
    dropped = 0
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        entry, attrs = parts[0], {p[1:] for p in parts[1:] if p.startswith("@")}
        if want_attr and want_attr not in attrs and not entry.startswith("include:"):
            continue
        if entry.startswith("include:"):
            sub = entry[len("include:") :]
            # `include:x @attr` means "only the @attr-tagged part of x".
            sub_attr = next(iter(attrs)) if attrs else None
            s, k, d = parse_category(sub, raw, sub_attr, seen)
            suffixes |= s
            keywords |= k
            dropped += d
            continue
        if entry.startswith("regexp:"):
            dropped += 1
            continue
        if entry.startswith("keyword:"):
            keywords.add(entry[len("keyword:") :].lower())
            continue
        # `full:` is an exact host; we only have suffix matching, which also
        # covers the host itself (plus its subdomains — a deliberate widening,
        # never a narrowing).
        for prefix in ("domain:", "full:"):
            if entry.startswith(prefix):
                entry = entry[len(prefix) :]
                break
        entry = entry.strip(".").lower()
        if entry:
            suffixes.add(entry)
    return suffixes, keywords, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--url", default=UPSTREAM_TARBALL)
    args = ap.parse_args()

    raw, root_name = fetch_upstream(args.url)
    print(f"upstream: {UPSTREAM_REPO} ({root_name}), {len(raw)} categories")

    total_before = total_after = 0
    report: list[str] = []
    for path in sorted(SOURCES.glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        upstream = pack.get("upstream") or []
        if not upstream:
            continue  # hand-kept pack, left alone

        suffixes: set[str] = set()
        keywords: set[str] = set()
        dropped = 0
        for cat in upstream:
            s, k, d = parse_category(cat, raw)
            suffixes |= s
            keywords |= k
            dropped += d

        add = pack.get("add") or {}
        suffixes |= {v.lower() for v in (add.get("suffixes") or [])}
        keywords |= {v.lower() for v in (add.get("keywords") or [])}
        exclude = {v.lower() for v in (pack.get("exclude") or [])}
        suffixes -= exclude
        keywords -= exclude

        bad = suffixes & FORBIDDEN_SUFFIXES
        if bad:
            sys.exit(f"{path.name}: upstream produced a bare TLD suffix {bad} — "
                     "refusing to sync (it would route everything)")

        old = set(pack.get("suffixes") or []) | set(pack.get("keywords") or [])
        new = suffixes | keywords
        total_before += len(old)
        total_after += len(new)
        gained, lost = sorted(new - old), sorted(old - new)
        if gained or lost:
            report.append(
                f"{pack['id']}: {len(old)} → {len(new)} "
                f"(+{len(gained)} −{len(lost)})"
                + (f"\n    + {', '.join(gained[:12])}" + (" …" if len(gained) > 12 else "") if gained else "")
                + (f"\n    − {', '.join(lost[:12])}" + (" …" if len(lost) > 12 else "") if lost else "")
            )
        if dropped:
            report.append(f"    ({pack['id']}: {dropped} regexp entries dropped — unsupported)")

        pack["suffixes"] = sorted(suffixes)
        pack["keywords"] = sorted(keywords)
        if not args.dry_run:
            path.write_text(
                json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    print("\n".join(report) if report else "no changes")
    print(f"total entries: {total_before} → {total_after}")
    if args.dry_run:
        print("(dry run — nothing written)")


if __name__ == "__main__":
    main()
