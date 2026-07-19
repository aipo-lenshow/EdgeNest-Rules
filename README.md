# edgenest-rules

中文说明: [README_CN.md](./README_CN.md)

Routing rule data for the EdgeNest client, published as a single catalog file.

Clients read `catalog.json` from the `rule-set` branch. Everything on `main` is
source: one JSON file per pack, plus the scripts that assemble and check them.

## Why this repo exists

The pack data used to live inside the app as source code, which meant a single
stale domain could only be fixed by shipping a new release — the slowest path
for the fastest-moving data the client carries. Here, a one-line change reaches
users the same day, and the app keeps working exactly as before if this repo is
unreachable.

## Layout

```
sources/<pack>.json   one pack: metadata + domain lists (edit these)
scripts/              assemble + validate; advisory domain review
rule-set (branch)     catalog.json — the published artifact
```

## The catalog

```jsonc
{
  "schema": 1,          // shape version; a client refuses one it doesn't know
  "version": "20260720", // content revision, compared before writing to disk
  "generatedAt": "2026-07-20T03:00:00Z",
  "packs": [
    {
      "id": "ai_core",
      "nameZh": "…", "nameEn": "…",
      "descZh": "…", "descEn": "…",
      "defaultOutbound": "proxy",   // "proxy" | "direct"
      "defaultOn": true,
      "suffixes": ["openai.com", "…"],
      "keywords": ["openai"]
    }
  ]
}
```

Packs ship as **domain lists, not compiled rule-set binaries**. Clients let a
user retarget an individual domain inside a pack, which needs the entries
themselves; a compiled set can't be taken apart again.

## Editing

```bash
# edit sources/<pack>.json, then:
python3 scripts/build_catalog.py --out dist/catalog.json
```

The build fails — before anything is published — on a missing required field,
an `id` that disagrees with its file name, a pack with no entries, and on the
same domain appearing in two packs with **different** default outbounds (the
client merges packs by outbound, so that would make matching a coin flip).

Pushing to `main` publishes. A daily run republishes and re-checks; a run whose
catalog is byte-identical publishes nothing.

## Domain review

`scripts/check_domains.py` reports entries whose name no longer resolves, and
the workflow keeps one standing issue with the current list.

Read it as a prompt to look, never as an instruction to delete. What it can and
cannot see is documented at the top of the script — briefly: it catches a name
that has stopped resolving, and it cannot catch a retired service whose domain
still answers DNS, which is the more common way an entry goes stale.

## Curation

Packs are organized by what the user is doing — AI chat, developer
infrastructure, knowledge and academia, streaming — not by vendor. Names and
descriptions are neutral and describe the traffic being grouped. Keep new packs
in that shape.

## License

AGPL-3.0, matching the client.
