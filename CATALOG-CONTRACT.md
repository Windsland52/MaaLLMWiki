# MaaLLMWiki catalog contract (v1)

**中文摘要：** 每个 `vX.Y.Z` 快照 tag（带注释 tag，位于默认分支的某个提交上）对应一个
`maa-llm-wiki-catalog-vX.Y.Z.zip` 发布产物；产物内的 `catalog-manifest.json` 锁定 Wiki 提交
（`wiki_revision`）、目录版本（`catalog_version`）、三个上游来源的 40 位提交 SHA，以及每个打包
文件的体积与 SHA-256。manifest 的格式版本是 `api_version: "maa-llm-wiki-catalog/v1"`：v1 内只允许
向后兼容的新增字段，消费者必须忽略未知字段；删除/重命名字段或改变语义需要升到 v2。消费方应下载
**带版本**的产物（不可变）并运行 `uv run maa-wiki-verify-bundle` 校验；`-latest.zip` 只是便利别名，
内容会随新版本变化，不应用于复现。覆盖边界与已知局限见 §7。

This document is the consumer-facing contract for catalog snapshots. It is the authoritative
description of what the publish workflow produces and what consumers may rely on. The
machine-readable schema is `schemas/catalog-bundle-manifest.schema.json`; the measured coverage
gaps are stated in §7; the repository-wide rules are in `AGENTS.md`.

## 1. What a snapshot is

A snapshot is an annotated Git tag named `vMAJOR.MINOR.PATCH` on a commit of the default branch. The
tag commit is the Wiki revision whose committed catalog data the bundle carries. Each snapshot tag
has exactly one GitHub Release with two assets:

| Asset | Meaning |
|-------|---------|
| `maa-llm-wiki-catalog-vX.Y.Z.zip` | The immutable versioned bundle for that tag. |
| `maa-llm-wiki-catalog-latest.zip` | A convenience copy of the newest published bundle. It is overwritten by every release, so it is **not** reproducible. |

The bundle contains only catalog data: `sources/`, `generated/`, `schemas/`, and
`catalog-manifest.json`. It contains no Python code, no workflows, and no upstream source code.

Tags are created and published only by `.github/workflows/publish-catalog.yml`. The workflow refuses
to commit outside `sources/`, `generated/`, `schemas/`, refuses to publish after touching the two
hand-authored catalogs, and refuses to reuse an existing tag that names a different commit.

## 2. Versioning rules

- `vX.Y.Z` is the catalog version. The publish workflow increments the patch component by default;
  the minor/major components move only when a maintainer deliberately creates such a tag.
- A snapshot tag is immutable. If a publish is interrupted after the tag exists but before the
  release upload, the next run re-publishes the same tag from the same commit; it never moves a tag.
  Such a tag may briefly exist without a Release; consumers should treat "tag present but no
  Release" as an in-progress publish and wait for the next scheduled run rather than building from
  the tag itself.
- `catalog_version` in the manifest equals the tag name (including the leading `v`). Bundles
  produced before this field existed omit it; consumers must treat it as optional.
- `api_version` is `"maa-llm-wiki-catalog/v1"` and changes only for a breaking manifest change.
  **v1 stability rule:** additions are allowed within v1 (new optional manifest fields, new bundle
  directories, new schema files). Consumers MUST ignore unknown manifest fields and unknown zip
  entries they do not need. Removing or renaming a field, changing the meaning of an existing field,
  or changing the bundle layout breaks v1 and requires `api_version: "maa-llm-wiki-catalog/v2"`.
- A tag with no Release is not consumable: `v0.1.2` predates the publish workflow and is documented
  as an exception (it is deliberately not reused). Consumers should discover bundles through
  Releases, not through `git tag`.

## 3. `catalog-manifest.json`

| Field | Type | Contract |
|-------|------|----------|
| `api_version` | string | Always `"maa-llm-wiki-catalog/v1"` for this contract. |
| `catalog_version` | string \| absent | `vX.Y.Z` equal to the release tag. Absent in bundles produced before the field was introduced. |
| `wiki_revision` | 40-char hex string | The tagged Wiki commit; `git rev-parse vX.Y.Z^{commit}` equals this value for bundles published by the current workflow. |
| `working_tree_clean` | boolean | `true` for every workflow-published bundle; the builder refuses to build from a dirty tree without `--allow-dirty`. |
| `sources` | array | One entry per indexed upstream source: `source_id` (`maafw`, `maa-framework-go`, `maa-framework-rs`), `version`, and the full 40-character `revision` it was indexed at. |
| `files` | array | Every bundled file except the manifest: `path` (POSIX, repo-relative), `size_bytes`, `sha256` (lowercase hex). Sorted by `path`. |

The manifest is written with an explicit `wiki_revision`, so a bundle is self-describing: given only
the zip, a consumer can identify the exact catalog data it contains. The bundle zip is deterministic
(fixed entry timestamps, fixed file mode, sorted entries), so the same committed tree produces
byte-identical bundle content across rebuilds.

## 4. Discovery

Official discovery is the GitHub Releases API on `Windsland52/MaaLLMWiki`:

- newest published bundle (follows GitHub's "latest release" semantics, which excludes drafts and
  prereleases):
  `https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest`
- a specific snapshot: `https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/tags/vX.Y.Z`
- direct stable alias download (convenience only):
  `https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip`
- direct immutable download:
  `https://github.com/Windsland52/MaaLLMWiki/releases/download/vX.Y.Z/maa-llm-wiki-catalog-vX.Y.Z.zip`

Rules of thumb:

- Pin the versioned asset and record its `vX.Y.Z` tag for anything reproducible; the `-latest` alias
  is overwritten in place.
- Do not derive the catalog version from `main`; the default branch may be ahead of the newest tag.
- The repository tree is also readable through the jsDelivr CDN for plain files (see the agent
  skill), but that is a mirror of the Git tree, not a release channel; it is not covered by this
  contract.

## 5. Verification

`maa-wiki-verify-bundle` is implemented in this repository and works offline (it reads only the
zip):

```bash
# from a checkout of this repository, with Python 3.13 and uv installed
uv sync --locked
uv run maa-wiki-verify-bundle \
  --bundle maa-llm-wiki-catalog-vX.Y.Z.zip \
  --expect-version vX.Y.Z \
  --expect-revision <40-char wiki revision>
```

It aggregates all problems and exits non-zero with a single `error: ...` line if any check fails.
Checks performed:

1. `catalog-manifest.json` parses and validates as a catalog-bundle manifest
   (`schemas/catalog-bundle-manifest.schema.json`).
2. Every `files` entry exists in the zip with matching `size_bytes` and `sha256`.
3. The zip contains no entry outside `{catalog-manifest.json} ∪ manifest file paths`.
4. When supplied, `--expect-version` equals `catalog_version` and `--expect-revision` equals
   `wiki_revision`.

`--expect-version` and `--expect-revision` are optional individually; supplying them ties the
downloaded bytes to the tag and commit you intended to consume. The workflow runs the same
verification against the freshly built bundle before uploading it.

## 6. Guarantees and non-guarantees

Guaranteed for bundles published by the current workflow:

- The release asset named `maa-llm-wiki-catalog-vX.Y.Z.zip` belongs to tag `vX.Y.Z`; that tag names
  the commit recorded as `wiki_revision`; `catalog_version` names the tag.
- Every file listed in the manifest matches its recorded size and SHA-256; there are no unlisted zip
  entries.
- The bundle was built from a clean, committed tree, and the tagged tree is exactly the catalog that
  was validated by the required checks before tagging.
- The two hand-authored catalogs (`sources/maa-framework/source-map.yaml` and
  `sources/maa-framework/semantic-changes.yaml`) are human-reviewed; automation refuses to modify
  them.
- Every source reference is a full 40-character commit SHA, never a moving branch.

Not guaranteed (measured coverage in §7):

- Completeness or correctness of upstream coverage. The catalog tracks MaaFramework 5.x and the Go
  and Rust bindings; it does not infer or verify upstream behavior changes.
- That every upstream behavior change is reflected in `semantic-changes.yaml`. The semantic review
  queue is a best-effort review aid: it now compares artifact content between consecutive releases
  (`maa-wiki-report-semantic-gaps --repository <MaaFramework clone>`, `git diff --numstat`) in
  addition to titles/summaries, but only for indexed paths, and it is not a complete changelog.
- Runtime verification of binding compatibility (`status: declared` is textual evidence only).
- Availability, refresh cadence, or response times; there is no SLA and the bundle is republished
  only when catalog data changes.
- Authenticity beyond HTTPS and GitHub's release integrity. The bundle is not signed (yet); the
  manifest's hashes detect corruption, not a compromised publisher.
- The `-latest.zip` alias contents at a later point in time; only the versioned asset is immutable.


## 7. Known gaps and limitations

**Last verified: 2026-11-05** (catalog `v0.1.14`, MaaFramework 5.15.0). Every number below was
re-derived from the catalog files on that date; §7.6 re-derives them. If a number disagrees with the
data files, the data files win.

### 7.1 Semantic-change coverage is incomplete

- `sources/maa-framework/semantic-changes.yaml` holds **33 entries covering 17 of the 55 indexed
  stable releases** (5.5.0, 5.8.0, 5.9.0, 5.10.0, 5.10.2, 5.10.3, 5.11.0, 5.11.1, 5.11.2, 5.12.1,
  5.12.3, 5.13.0, 5.13.1, 5.14.0, 5.14.1, 5.14.3, 5.15.0). It is a curated subset, not a
  release-by-release changelog.
- The synthetic `vX.Y.Z` snapshot versions of this repository are not upstream MaaFramework
  releases; only the 5.x numbers are.
- `maa-wiki-report-semantic-gaps --repository <clone>` compares artifact content between consecutive
  release tags (`git diff --numstat`) in addition to titles and first paragraphs, so edits deeper
  inside an indexed file are visible. It still cannot see paths outside the indexed set (`docs/`,
  `tools/`, `include/`, `source/binding/`) and cannot detect upstream tag mutation. An empty report
  means the review queue is empty, which is the expected state while the catalog is current.
- The report is a review aid, not a changelog: each item is a suspected trigger. A release without an
  entry may still have changed behaviour, and an entry may describe no functional change.

### 7.2 Source-map coverage is partial and version-pinned

- `sources/maa-framework/source-map.yaml` holds **11 topics and 18 variants** — a curated subset of
  routing topics, not a complete API map.
- Variants are pinned per release (**8 at 5.11.2, 5 at 5.13.0, 3 at 5.15.0, one each at 5.12.3 and
  5.14.3**). A variant proves that the listed paths, symbols and terms existed at that commit; it
  says nothing about later releases. A topic whose newest variant predates the newest indexed release
  is intentionally pinned until a newer variant is reviewed.
- If a question cannot be routed through the source map, cite the upstream file at its pinned commit
  directly.

### 7.3 Binding compatibility is declared, not verified

- `sources/compatibility/bindings.yaml` ties Go/Rust binding releases to MaaFramework versions using
  textual evidence: a release link or badge in the binding's README or workspace manifest at its
  pinned commit. `status: declared` means "the binding's own documentation claims this", not "this
  combination was built, loaded and run".
- The current file has **56 `declared` and 22 `unknown` entries**. `unknown` means "not established",
  never "incompatible".
- No runtime compatibility matrix has been executed. Treat compatibility as a testing starting point,
  never as a support guarantee.
- Only the Go and Rust bindings are registered as external sources. C# and Java are not indexed
  (Java is obsolete upstream; C# has no registered source with a pinned revision). In-tree
  Python/NodeJS binding APIs follow the MaaFramework revision.

### 7.4 Version scope and upstream change detection

- The publish workflow indexes **MaaFramework 5.x only** (`CATALOG_MAJOR`); a higher upstream major
  makes the sync fail loudly instead of silently freezing the catalog. The catalog stays on 5.x until
  a maintainer deliberately bumps `CATALOG_MAJOR`.
- Upstream tag mutation is not detected: the sync re-reads tags and rewrites the release catalogs, so
  a moved or deleted upstream tag changes the next snapshot silently unless a hand-authored entry
  still references it. Take release identity from the pinned 40-character commit SHA, never from the
  tag name.
- Prerelease movement can produce snapshots of its own, so a catalog release does not imply a new
  stable MaaFramework release.
- The daily schedule is best-effort; GitHub may delay or skip scheduled runs.

### 7.5 Distribution and operations

- **GitHub Releases is the only distribution channel**; there is no other mirror operated by this
  project. The jsDelivr URL used by the agent skill mirrors the Git tree for plain files — an
  unofficial convenience with cache delay, outside this contract.
- `maa-llm-wiki-catalog-latest.zip` is overwritten by every release; pin the versioned asset for
  anything reproducible.
- Bundles are **not signed**. `maa-wiki-verify-bundle` detects corruption and manifest/zip
  inconsistency, not a compromised publisher.
- **No SLA**: no availability, response-time or refresh guarantee. The workflow runs daily and
  publishes only when catalog data changes.

### 7.6 How to re-derive these numbers

```bash
# entries, distinct versions, topics, indexed releases
uv run python -c "from pathlib import Path; from maa_llm_wiki.validation import load_semantic_changes, load_source_map, load_release_catalog; r=Path('.'); c=load_semantic_changes(r); print('entries', len(c.changes), 'versions', len({x.first_version for x in c.changes}), 'topics', len(load_source_map(r).topics), 'releases', len(load_release_catalog(r).releases))"
uv run maa-wiki-validate
uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework --output /tmp/semantic-gaps.md
grep -c 'status: declared' sources/compatibility/bindings.yaml
grep -c 'status: unknown' sources/compatibility/bindings.yaml
```
## 8. Licence of the bundle

Catalog data in the bundle is licensed under CC BY 4.0 (`LICENSE-DATA`); short upstream
documentation excerpts remain under their upstream licences (LGPL-3.0 for the MaaXYZ projects, see
`NOTICE`). The repository code is MIT (`LICENSE`). Redistributing a bundle must keep the attribution
notices; it does not relicense the upstream excerpts.
