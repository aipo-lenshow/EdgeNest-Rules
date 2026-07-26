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

## Where pack content comes from

Most packs are **aligned with upstream every day** rather than kept by hand.
Each such pack declares which upstream categories it follows, plus our own
overlay:

```jsonc
"upstream": ["openai", "anthropic"],   // followed daily
"add":      { "suffixes": [...] },     // ours; upstream doesn't carry these
"exclude":  ["klingai.com"],           // ours; drop even if upstream has it
"suffixes": [...]                      // GENERATED — do not hand-edit
```

    pack = (upstream categories) ∪ add − exclude

Upstream is [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)
(MIT): a community-maintained, per-service categorisation that moves daily.
Following it is what keeps a dead name from sitting in a pack until someone
notices — `bard.google.com` outlived its product in our AI pack for months.

Three vendors stay hand-kept on purpose: upstream's `apple` (1807 entries),
`google` (1082) and `microsoft` (753) categories cover each vendor's entire
surface, including endpoints served inside China. Our packs are the handful of
services a user actually thinks about, so following those categories would
inflate a 16-entry pack a hundredfold and change how it routes.

`regexp:` entries are dropped on import — the client has no regex matcher, and
a rule that is silently ignored is worse than one that is absent. The sync
reports how many it dropped.

## Editing

```bash
# a hand-kept pack: edit sources/<pack>.json directly
# an upstream-followed pack: edit its "add" / "exclude", never "suffixes"
python3 scripts/sync_upstream.py --dry-run   # what upstream would change
python3 scripts/sync_upstream.py             # apply it
python3 scripts/build_catalog.py --out dist/catalog.json
```

The build fails — before anything is published — on a missing required field,
an `id` that disagrees with its file name, a pack with no entries, and on the
same domain appearing in two packs with **different** default outbounds (the
client merges packs by outbound, so that would make matching a coin flip).

Pushing to `main` publishes what you wrote — a push never runs the upstream
sync, so your change is never mixed with overnight upstream movement.

## The daily run, and its guard

03:00 UTC: sync with upstream → build → **check the diff is sane** → publish.

`scripts/guard_changes.py` guards the publish. An unattended daily edit of
everyone's routing needs one: an upstream mistake — a category emptied, a merge that drops
half a list — would otherwise reach every device within the day, silently. It
holds the publish and opens an issue with the diff when

- a pack loses more than 25 entries, or more than 30% of itself,
- a pack empties or disappears,
- the catalog more than triples in one run.

Thresholds measure the *size* of a change, not whether its contents are right;
no script can judge the latter. A manual run (`workflow_dispatch`) counts as
reviewed and publishes regardless.

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

Pack content is derived from
[v2fly/domain-list-community](https://github.com/v2fly/domain-list-community),
licensed MIT.
