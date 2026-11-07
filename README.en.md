# MaaLLMWiki

**English** | [中文](README.md)

MaaLLMWiki provides machine-readable, versioned source catalogs for Maa ecosystem knowledge: it helps
a model select and find original documentation, schemas, public APIs, and source code, and does not
author or replace those sources. Catalog snapshots are published as verifiable catalog bundles; the
consumer contract is `CATALOG-CONTRACT.md`.

## Scope

Included: complete version-pinned MaaFramework documentation/schema/native-API/in-tree-binding indexes;
independently versioned Go, Rust and C# binding indexes with compatibility evidence; topic routing;
machine-extracted API declaration changes between releases and an index of the upstream commits.

Excluded: project-specific documentation and Pipeline configuration; raw artifacts, logs, and
benchmark answers; full copies of MaaFramework documentation or source trees (the index keeps titles,
auto-extracted first-paragraph excerpts, and pinned links only); tutorials, best practices, and
diagnostic methodology; unverified model-generated conclusions.

The Go, Rust and C# bindings are registered as independent external sources, each with its own pinned
inventory and compatibility evidence; the C# binding is distributed via NuGet (`Maa.Framework`) and
its stable releases align with MaaFramework 5.x tags from `v5.1.0` on, and its prereleases start at `v5.0.0-preview.1`. Java is marked obsolete upstream and
is not a default API source. The native public API is the C/C++ headers; in-tree Python/NodeJS
binding APIs follow the MaaFramework version.

## Pick a version in 30 seconds

1. **Which MaaFramework version** → the Current snapshot block at the top of
   `generated/maa-framework/index.md`, or any row in its list;
2. **What is in that version** → that version's `index.md`: per-domain file counts and a Navigation
   block (previous/next release, top-level pages);
3. **Which release introduced a field/API/enum** → `generated/maa-framework/machine-symbols.md`
   (element to the release that introduced it and its later changes); what changed in one release is
   in `machine-changes.md`, and behaviour changes behind unchanged declarations are found through
   `upstream-commits.md`;
4. **What moved between two releases** → the `Changed since` summary on the version page, or
   `uv run maa-wiki-diff --from <old> --to <new>`;
5. **Need a citable source** → the page links are pinned to 40-character commits; quote the
   upstream source, not the index.

## Using the catalog

1. Download the versioned `maa-llm-wiki-catalog-vX.Y.Z.zip` from the Releases API or release page,
   together with that release's `SHA256SUMS` and `verify_bundle.py`. The zip starts with `START-HERE.md` and carries its own README,
   contract, operations guide and licence files, so it is readable offline once extracted.
2. Verify in order:
   - `sha256sum -c SHA256SUMS`
   - `gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`
   - `python verify_bundle.py --bundle maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --checksums SHA256SUMS`
3. The convenience alias
   `https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip`
   is overwritten by every release and is not reproducible; historical releases may lack it. Only the
   versioned zip carries an attestation; the alias, `SHA256SUMS` and the script are not attested.
4. Compare indexed material between two releases with
   `uv run maa-wiki-diff --from <old> --to <new>`; that tool gives the full untruncated list.
5. Install the agent skill from `skills/maallmwiki/SKILL.md` (MaaTutorial's `maafw-*` skills defer factual questions to it):
   `npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global`

If Python 3 is unavailable or you prefer uv, use
`uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z]` or
`uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle <zip>`;
details are in `docs/operations.md`.

Published release bodies are generated from the catalog itself and summarise the upstream snapshot,
new upstream releases, machine facts, and verification commands; see `docs/operations.md`.

## What is inside

```text
generated/maa-framework/index.md
  -> topics.md · machine-changes.md · machine-symbols.md · upstream-commits.md
  -> <version>/index.md            # includes "Changed since <previous indexed release>"
       -> documentation/ · bindings/ · native-api/ · schemas.md
```

Each version directory provides domain navigation; `topics.md` is the curated topic routes,
`machine-changes.md` and `machine-symbols.md` hold declaration changes extracted mechanically from the
upstream files (by release and by element), and `upstream-commits.md` lists the upstream commits by
release. `generated/maa-framework-{go,rs,csharp}/` provides
the equivalent Go/Rust/C# binding indexes. Page meanings, manifest semantics and the full layout are
in `docs/operations.md`.

`Changed since` in a version index lists indexed-file movement only; declaration changes are in
`machine-changes.md`, and behaviour changes are found through `upstream-commits.md` and the commit
diffs.

## Read more

| Want | Where |
| --- | --- |
| Guarantees, verification rules, known gaps (§8) | [`CATALOG-CONTRACT.md`](CATALOG-CONTRACT.md) |
| How to change the catalog/code, content boundaries, required checks | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Pipeline, snapshot lifecycle, failure handling, development commands | [`docs/operations.md`](docs/operations.md) |
| Security and private reporting | [`SECURITY.md`](SECURITY.md) |
| Licensing and attribution | [`LICENSE`](LICENSE), [`LICENSE-DATA`](LICENSE-DATA), [`NOTICE`](NOTICE) |

Snapshots are produced twice a day (best-effort); a failing pipeline opens a deduplicated
`pipeline-failure` issue that closes on the next successful run.

## Licence

- Code (Python sources, tests, workflows, and build tooling) is MIT-licensed: see `LICENSE`.
- Catalog data (metadata, inventories, generated navigation pages, schemas, and release bundles) is
  licensed under CC BY 4.0: see `LICENSE-DATA`.
- Short excerpts of MaaXYZ upstream documentation remain under their upstream licence (LGPL-3.0): see
  `NOTICE`.

Keep those attribution notices when redistributing catalog data or excerpts; this repository's
licences do not relicense upstream material.
