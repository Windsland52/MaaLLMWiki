# START HERE

This zip is a **MaaLLMWiki catalog snapshot**: a machine-readable, version-pinned index of
MaaFramework material (documentation, JSON schemas, public APIs and the Go/Rust/C# binding APIs).
It points at the upstream sources; it does not replace them.

## What is inside

| Path | What it is |
| --- | --- |
| `catalog-manifest.json` | The snapshot itself: `catalog_version` (the release tag), `wiki_revision`, source versions and commits, and every file with its size and SHA-256. |
| `generated/` | Rendered navigation pages. Start at `generated/maa-framework/index.md` for the version list, then `generated/maa-framework/<version>/index.md`. |
| `generated/maa-framework/machine-symbols.md` | Which release introduced a declared API element, and its later changes. |
| `generated/maa-framework/machine-changes.md` | Declared API elements added, removed, modified or deprecated in each release, with upstream text. |
| `generated/maa-framework/upstream-commits.md` | The upstream commits between consecutive releases, for behaviour changes that no declaration shows. |
| `sources/` | The committed catalog data the pages were rendered from (inventories, release registries, compatibility metadata, the curated source map, machine changes and the upstream commit index). |
| `schemas/` | JSON Schemas for the data files above. |
| `README.md`, `CATALOG-CONTRACT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/operations*.md`, `LICENSE`, `LICENSE-DATA`, `NOTICE` | What this is, what it guarantees, how to work on it, and the licences. |

## Verify before you trust

The versioned zip is immutable and attested; the digest is also printed in the release body.

```bash
sha256sum -c SHA256SUMS
gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki
python verify_bundle.py --bundle maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --checksums SHA256SUMS
```

`verify_bundle.py` needs only a Python 3 interpreter and the two files next to it.

## How to use it with a model

- Ask the question against a **named MaaFramework version**; the catalog has no "latest" alias,
  so choose the version first.
- Resolve each fact to the pinned upstream commit that the page links to, and quote that source
  rather than the catalog index.
- For "which version introduced it", read `machine-symbols.md`; for "what changed in this
  release", read `machine-changes.md`. Both compare declarations only: for a behaviour change, find
  the commit in `upstream-commits.md` and read its diff at the pinned SHA.

## Licence

Catalog data (metadata, inventories, rendered pages, schemas, this bundle) is CC BY 4.0 — see
`LICENSE-DATA`. Short excerpts from MaaXYZ upstream repositories keep their upstream licence
(LGPL-3.0) — see `NOTICE`. The catalog's own code is MIT (`LICENSE`).
