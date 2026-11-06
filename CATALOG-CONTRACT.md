# MaaLLMWiki catalog contract (v1)

**中文摘要：** 每个 `vX.Y.Z` 快照 tag（带注释 tag，位于默认分支的某个提交上）对应一个
`maa-llm-wiki-catalog-vX.Y.Z.zip` 发布产物；产物内的 `catalog-manifest.json` 锁定 Wiki 提交
（`wiki_revision`）、目录版本（`catalog_version`）、四个上游来源（MaaFramework 与 Go/Rust/C# 三个绑定）的 40 位提交 SHA，以及每个打包
文件的体积与 SHA-256。manifest 的格式版本是 `api_version: "maa-llm-wiki-catalog/v1"`：v1 内只允许
向后兼容的新增字段，消费者必须忽略未知字段；删除/重命名字段或改变语义需要升到 v2。消费方应下载
**带版本**的产物（不可变），运行 `uv run maa-wiki-verify-bundle` 校验，并用发布页的 `SHA256SUMS`
（`sha256sum -c`）与 build provenance 证明（`gh attestation verify`）确认下载完整性和构建来源；
发布页另附零依赖校验脚本 `verify_bundle.py`（仅需 Python 3.10+，可离线运行，非 attestation 主体）。
每个版本的 `index.md` 还列出相对上一注册版本的被索引产物变更（新增 / 内容变更 / 删除，按 git blob
判定；属导航而非行为变更，列表有截断）。机器抽取的变更事实（API/schema/协议级，附原文引用；非运行时
语义）见 `machine-changes.md`（§7.1），人工撰写的 `behaviour-changes.md` 是可选的解释层。
`-latest.zip` 只是便利别名，内容会随新版本变化，不应用于复现。浏览与版本差异工具见 §7，覆盖边界与
已知局限见 §8。

This document is the consumer-facing contract for catalog snapshots. It is the authoritative
description of what the publish workflow produces and what consumers may rely on. The
machine-readable schema is `schemas/catalog-bundle-manifest.schema.json`; the measured coverage
gaps are stated in §8; the repository-wide rules are in `AGENTS.md`.

## 1. What a snapshot is

A snapshot is an annotated Git tag named `vMAJOR.MINOR.PATCH` on a commit of the default branch. The
tag commit is the Wiki revision whose committed catalog data the bundle carries. Each snapshot tag
published by the current workflow has exactly one GitHub Release with four assets (older releases
carry fewer: two before `SHA256SUMS` was introduced, three before the standalone verifier was added):

| Asset | Meaning |
|-------|---------|
| `maa-llm-wiki-catalog-vX.Y.Z.zip` | The immutable versioned bundle for that tag. This is the primary, **attested** subject. |
| `maa-llm-wiki-catalog-latest.zip` | A convenience copy of the newest published bundle. It is a byte-identical copy of the versioned zip and is overwritten by every release, so it is **not** reproducible. |
| `SHA256SUMS` | `sha256sum` output covering both zip names above; verify with `sha256sum -c SHA256SUMS`. |
| `verify_bundle.py` | Dependency-free (standard library only) copy of the in-repo verifier for consumers without `uv` or a checkout. A convenience asset; not attested (§5.3). |

The build-provenance attestation is **not** a release asset: it is stored in this repository's
immutable attestation store (§5).

The release body is generated from the catalog, not written by hand. Its sections state the upstream
versions the snapshot pins (Upstream snapshot), the upstream releases that appeared since the
previous snapshot (New upstream releases), the machine-extracted facts and any curated behaviour
entries for those releases (Machine-extracted changes, Curated behaviour changes), per-source counts
of indexed material that moved (Indexed material moved), how many catalog files the snapshot itself
added, removed or changed (Catalog files changed), the exact verification commands, the
released assets with their digests, sizes and file counts, and documentation links including a
compare URL for the change range. The publish workflow is scheduled twice a day (03:17 and 15:17
UTC) and can also be dispatched manually.

The bundle contains the catalog data (`sources/`, `generated/`, `schemas/`), the manifest
(`catalog-manifest.json`), and the consumer documents that describe and license it (`START-HERE.md`,
the READMEs, this contract, `CONTRIBUTING.md`, `SECURITY.md`, `docs/operations.md` with its Chinese
mirror, `LICENSE`, `LICENSE-DATA`, `NOTICE`). It contains no Python code, no workflows, and no upstream
source code.
`generated/` includes the rendered navigation pages described in §7.1 (see also §3).

The catalog pins three external binding sources beside MaaFramework: Go, Rust and C#. Each is
independently pinned with its own inventory and compatibility metadata, and none inherits the
MaaFramework repository revision. The C# binding is distributed via NuGet (`Maa.Framework`); its
stable releases align with MaaFramework 5.x tags from `v5.1.0` on (prereleases start at
`v5.0.0-preview.1`), and each release declares its framework
version in `src/Directory.Packages.props` at the pinned commit.

Tags are created and published only by `.github/workflows/publish-catalog.yml`. The workflow refuses
to commit outside `sources/`, `generated/`, `schemas/`, refuses to publish after touching the two
hand-authored catalogs, and refuses to reuse an existing tag that names a different commit.

A maintainer can deliberately re-issue a snapshot when only packaging or pipeline changed: a manual
`workflow_dispatch` with `force=true` publishes even when the catalog data is unchanged. The
resulting tag still names the catalog contents carried by the bundle — those contents may be
identical to the previous snapshot — while the release assets and build-provenance attestation are
rebuilt; the workflow still refuses a dirty working tree and still runs every validation, build,
verification, checksum and attestation step.

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
  directories, new schema files, new generated pages). Consumers MUST ignore unknown manifest fields
  and unknown zip entries they do not need. Removing or renaming a field, changing the meaning of an
  existing field, or changing the bundle layout breaks v1 and requires
  `api_version: "maa-llm-wiki-catalog/v2"`.
- A tag with no Release is not consumable: `v0.1.2` predates the publish workflow and is documented
  as an exception (§7.4; it is deliberately not reused). Consumers should discover bundles through
  Releases, not through `git tag`.

## 3. `catalog-manifest.json`

| Field | Type | Contract |
|-------|------|----------|
| `api_version` | string | Always `"maa-llm-wiki-catalog/v1"` for this contract. |
| `catalog_version` | string \| absent | `vX.Y.Z` equal to the release tag. Absent in bundles produced before the field was introduced. |
| `wiki_revision` | 40-char hex string | The tagged Wiki commit; `git rev-parse vX.Y.Z^{commit}` equals this value for bundles published by the current workflow. |
| `working_tree_clean` | boolean | `true` for every workflow-published bundle; the builder refuses to build from a dirty tree without `--allow-dirty`. |
| `sources` | array | One entry per indexed upstream source: `source_id` (`maafw`, `maa-framework-go`, `maa-framework-rs`, `maa-framework-csharp`), `version`, and the full 40-character `revision` it was indexed at. |
| `files` | array | Every bundled file except the manifest: `path` (POSIX, repo-relative), `size_bytes`, `sha256` (lowercase hex). Sorted by `path`. Includes the rendered navigation pages of §7.1. |

The manifest is written with an explicit `wiki_revision`, so a bundle is self-describing: given only
the zip, a consumer can identify the exact catalog data it contains. For bundle tags **v0.1.18 and
later**, the current builder produces a deterministic zip: entry timestamps, file modes, entry order
and the zip host field (`create_system`) are fixed, so a clean rebuild of the same committed tree
produces a **byte-identical zip across platforms**, as long as the same Python and zlib toolchain is
used for compression. This is verified for `v0.1.18`: a clean Windows rebuild from its tag reproduces
the published artifact byte-for-byte (SHA-256
`4df3fc3d684f1ccfd5164eddf1a3e187bdf618d70f7dac0d12c58099a7f7fda3`). Bundles published before
`v0.1.18` do **not** carry this guarantee — see §8.5.

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
- Older tags have a documented history: see §7.4 before consuming anything older than `v0.1.3`.

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

### 5.1 Release-level integrity: checksums

Download `SHA256SUMS` alongside the bundle, then check it in the directory that contains the
downloaded assets:

```bash
sha256sum -c SHA256SUMS
```

The file lists both download names, so it verifies whichever asset you fetched. The `-latest.zip`
alias is copied from the versioned bundle before the checksum file is written, so both lines have
the same digest for a given release. `SHA256SUMS` is itself a release asset but is **not** an
attested subject: it is a convenience index. The authoritative integrity binding is the provenance
attestation on the versioned zip (§5.2), which in turn covers every file hash recorded in the
bundle's manifest.

### 5.2 Release-level integrity: build provenance

The versioned bundle is the primary attested subject. Verify it with GitHub CLI (network access and
a published release/attestation record are required):

```bash
gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki
```

The publish workflow mints a short-lived OIDC token, records a keyless Sigstore build-provenance
attestation for the versioned zip digest, and only then tags and uploads the release. A successful
verification means the artifact digest was produced by **this repository's publish workflow at the
attested commit** — not that the catalog content is correct or that the publisher acted in good
faith. The attestation is meaningful only relative to this repository's workflow, and it is not a
long-lived project signing key.

Limits of this check:

- it needs network access and the published attestation record, so it cannot be verified offline or
  from the zip alone;
- the `-latest` alias, `SHA256SUMS` and `verify_bundle.py` are convenience artifacts and are **not**
  attested subjects;
- releases published before provenance attestation was introduced have no attestation, so the first
  release produced with this step is the first one that can be verified this way.

### 5.3 Zero-dependency verification (release asset)

Each release also carries `verify_bundle.py`, a plain standard-library script that needs only a
Python 3 interpreter (3.10 or newer, standard library only) — no `uv`, no repository checkout and no
network access. It is a convenience copy of `src/maa_llm_wiki/verify_bundle.py`; the copy in a
release is the verifier that was current when that release was published. Download it next to the
bundle and `SHA256SUMS`, then run:

```bash
python verify_bundle.py \
  --bundle maa-llm-wiki-catalog-vX.Y.Z.zip \
  --expect-version vX.Y.Z \
  --expect-revision <40-char wiki revision> \
  --checksums SHA256SUMS
```

It performs the same manifest/zip/checksum/expectation checks as `maa-wiki-verify-bundle` and exits
non-zero with an `error: ...` line on failure. `verify_bundle.py` is a convenience artifact and is
**not** an attested subject — only the versioned zip is attested (§5.2) — and `SHA256SUMS` covers
the two zip download names only, not the script.

## 6. Guarantees and non-guarantees

Guaranteed for bundles published by the current workflow:

- The release asset named `maa-llm-wiki-catalog-vX.Y.Z.zip` belongs to tag `vX.Y.Z`; that tag names
  the commit recorded as `wiki_revision`; `catalog_version` names the tag.
- Every file listed in the manifest matches its recorded size and SHA-256; there are no unlisted zip
  entries.
- The bundle was built from a clean, committed tree, and the tagged tree is exactly the catalog that
  passed the publish job's machine gates before tagging: `maa-wiki-extract-changes --check` (the
  committed machine catalog equals a fresh extraction), `maa-wiki-validate`, the repository's
  test/lint/type checks, `maa-wiki-verify-bundle`, checksums, and the provenance attestation. A
  failure in any gate blocks the tag and release; there is no human sign-off step in the pipeline.
- The two hand-authored catalogs (`sources/maa-framework/source-map.yaml` and
  `sources/maa-framework/semantic-changes.yaml`) are changed only by explicit maintainer commits;
  automation refuses to modify them.
- Every source reference is a full 40-character commit SHA, never a moving branch.
- From the first release published with provenance attestation, the versioned zip carries a keyless
  Sigstore build-provenance attestation created by the publish workflow; `gh attestation verify` ties
  the asset digest to this repository's workflow and commit, and a `SHA256SUMS` asset covers both
  download names.

Not guaranteed (measured coverage in §8):

- Completeness or correctness of upstream coverage. The catalog tracks MaaFramework 5.x plus the
  independently pinned Go, Rust and C# bindings; it does not infer or verify upstream behavior changes.
- That every upstream behavior change is reflected in `semantic-changes.yaml`. The semantic review
  queue is a best-effort review aid: it detects content-level changes offline by comparing the
  artifact `blob` ids recorded in consecutive inventories (`maa-wiki-report-semantic-gaps`), with
  `--repository <MaaFramework clone>` available as an optional cross-check (§7.3). It only covers
  indexed paths and is not a complete changelog.
- Runtime verification of binding compatibility (`status: declared` is textual evidence only).
- Availability, refresh cadence, or response times; there is no SLA and the bundle is republished
  only when catalog data changes.
- Provenance is not correctness or intent: the attestation proves which workflow and commit produced
  the versioned zip, not that the catalog data is accurate or that the publisher acted in good faith.
  It is meaningful only relative to this repository's workflow; the `-latest` alias and `SHA256SUMS`
  are not attested subjects.
- The `-latest.zip` alias contents at a later point in time; only the versioned asset is immutable.

## 7. Navigating, diffing and change detection

### 7.1 Rendered navigation pages (recommended entry point)

The bundle ships three rendered navigation pages under `generated/maa-framework/`, all linked from
`generated/maa-framework/index.md`:

| Page | Contents |
|------|----------|
| `topics.md` | The curated routing topics: for every topic, each variant with its `applies_to` release, pinned revision, file links, symbols and literal search terms. |
| `behaviour-changes.md` | The curated semantic changes, grouped by the release in which behaviour first changed, with links pinned to that release's commit. Optional interpretation layer. |
| `machine-changes.md` | The machine-extracted change facts: enum values, public functions, callback messages, JSON-schema properties/enums/defaults/required, interface protocol versions and binding API names — one record per mechanically detected change, with the verbatim upstream line and its indexed paths. |
| `machine-symbols.md` | The same facts indexed by symbol instead of by release: for every recorded symbol, the release that first introduced it and the later releases that touched it. Use it to answer "which release introduced X". |

Use `topics.md` for topic-level or cross-version routing questions ("where is feature X documented
in this release"), `machine-symbols.md` for "which release introduced symbol X" questions (one row
per symbol, with the first appearance and later movement), `machine-changes.md` for the per-release
record with upstream evidence, and `behaviour-changes.md` for curated "when did behaviour X change"
narrative.
Together they are the readable view of the catalogs, so a consumer does not need to know the YAML
layout:

- `sources/maa-framework/source-map.yaml` and `sources/maa-framework/semantic-changes.yaml` remain
  the **authoritative hand-authored sources**; automation refuses to modify them, and a change
  reaches a snapshot only through an explicit maintainer commit;
- `sources/maa-framework/machine-changes.yaml` is generated by the sync from upstream diffs and
  checked by the publish gate; it is not hand-authored;
- the three pages are **generated views**, rebuilt by the sync; do not treat edits to them as data;
- they are ordinary bundle files inside `generated/`, covered by the manifest `size_bytes`/`sha256`
  entries, and are additive within `api_version: ".../v1"`.

Each version's `index.md` also ends with a **"Changed since …"** section whose heading names the
previous registered release (the first indexed release says there is no previous inventory to compare
against). It lists the indexed artifacts that were added, content-changed (by git blob id, falling
back to title/summary for pre-blob inventories) or removed between the two releases, with counts. It
is navigation rendered from the inventories — capped at 20 entries per list with an "… and K more"
line — and records movement of indexed **material**, not behaviour changes: `maa-wiki-diff` (§7.2)
prints the complete, uncapped list.

`machine-changes.md` is the machine layer: it is extracted mechanically from `git diff` between
consecutive registered releases, and every record carries the verbatim upstream line and the indexed
paths it came from. It covers API/schema/protocol-level facts only and cannot state runtime
semantics, intent, or whether a change matters. Release pairs whose indexed paths changed but
produced no structured record are listed explicitly as `unclassified` entries, which makes the
extractor's coverage gap visible. The curated `behaviour-changes.md` is the optional interpretation
layer on top: it explains significance but adds no detection.

### 7.2 Diffing two releases: `maa-wiki-diff`

To see what changed in the indexed artifacts between two releases:

```bash
# markdown (default)
uv run maa-wiki-diff --from 5.14.3 --to 5.15.0
# machine readable, stable key order
uv run maa-wiki-diff --from 5.14.3 --to 5.15.0 --format json
# external binding sources work the same way (default --source is maafw)
uv run maa-wiki-diff --from 1.26.0 --to 1.27.0 --source maa-framework-rs
```

It reports **added / removed / changed** indexed artifacts between the two inventories, grouped by
artifact kind with counts. "Changed" means a different git blob id when both inventories record one,
falling back to the title/summary comparison for older inventories. `maa-wiki-diff` compares the
**git blob ids recorded in the inventories themselves**, so it works from a published bundle alone —
no upstream clone and no network access are needed. The corollary is a limitation: for artifacts
whose inventory entry has no `blob` (bundles published before the field was introduced), the tool
falls back to titles/summaries and therefore does **not** detect a content-only change. An unknown
version or source exits non-zero with the uniform `error: ...` line. The JSON form is stable
(`sort_keys=True`) and suitable for tooling.

### 7.3 Offline content-hash change detection

Every artifact in `sources/*/inventories/*.yaml` records its git blob id (`blob`), the immutable
content hash of the upstream file at the pinned revision. `maa-wiki-report-semantic-gaps` uses those
hashes to detect **content-level** changes offline, without an upstream clone: it compares blob ids
across consecutive inventories and reports releases whose indexed artifacts changed content even when
titles and summaries did not move. `--repository <MaaFramework clone>` remains available as an
optional cross-check that additionally diffs file content between tags.

An **empty report means the review queue is empty** — nothing changed relative to the newest
recorded semantic-change entry — which is the expected state while the catalog is current. The
detector still cannot see paths outside the indexed set (`docs/`, `tools/`, `include/`,
`source/binding/`) and cannot detect upstream tag mutation; it is a review aid, not a changelog
(§8.1).

### 7.4 Legacy snapshot tags

- `v0.1.0` and `v0.1.1` predate the current single-job publish pipeline but **do carry release
  bundles** (`maa-llm-wiki-catalog-v0.1.0.zip`, `...v0.1.1.zip`). They may omit fields and gates
  introduced later (for example `catalog_version`), so treat them as historical.
- `v0.1.2` is a tag with **no GitHub Release at all**. It is not a consumable snapshot and its
  version number is not reused. Discovery goes through Releases (§4), never through `git tag`.

## 8. Known gaps and limitations

**Last verified: 2026-11-05** (catalog `v0.1.14`, MaaFramework 5.15.0). This section states what the
catalog does not cover or guarantee. It deliberately does not hardcode volatile coverage counts —
"last verified" is the date of the descriptions below, and §8.6 re-derives every number from the
data files. If a number disagrees with the files, the files win.

### 8.1 Semantic-change coverage is incomplete

- `sources/maa-framework/semantic-changes.yaml` lists recorded behaviour changes for a curated
  subset of the indexed stable releases; it is not a release-by-release changelog. §8.6 re-derives
  the current entry count and the number of distinct covered versions.
- The synthetic `vX.Y.Z` snapshot versions of this repository are not upstream MaaFramework
  releases; only the 5.x numbers are.
- Detection is content-aware but bounded: blob ids make content edits visible for indexed paths,
  paths outside `docs/`, `tools/`, `include/` and `source/binding/` remain invisible, and upstream
  tag mutation is not detected. An empty report means the review queue is empty, the expected state
  while the catalog is current.
- The report is a review aid, not a changelog: each item is a suspected trigger. A release without
  an entry may still have changed behaviour, and an entry may describe no functional change.
- The machine layer (`machine-changes.md` / `machine-changes.yaml`, §7.1) is **extraction, not
  interpretation**: it records mechanically detected API/schema/protocol facts with verbatim quotes
  and cannot state runtime semantics, intent, or whether a change matters. `behaviour-changes.md`
  remains an optional curated interpretation layer and is not required for detection.
- Machine-layer coverage is bounded by the extractor's fixed rules. Release pairs whose indexed paths
  changed but produced no structured record are recorded explicitly as `unclassified` entries; that
  count is the visible coverage measure and §8.6 re-derives it.

### 8.2 Source-map coverage is partial and version-pinned

- `sources/maa-framework/source-map.yaml` is a curated subset of routing topics, not a complete API
  map; the rendered `topics.md` (§7.1) is its readable view.
- Variants are pinned per release. A variant proves that the listed paths, symbols and terms existed
  at that pinned commit; it says nothing about later releases. A topic whose newest variant predates
  the newest indexed release is intentionally pinned until a newer variant is reviewed. §8.6
  re-derives the current topic/variant counts.
- If a question cannot be routed through the source map, cite the upstream file at its pinned commit
  directly.

### 8.3 Binding compatibility is declared, not verified

- `sources/compatibility/bindings.yaml` ties Go, Rust and C# binding releases to MaaFramework
  versions using textual evidence: a release link or badge in the binding's README or workspace
  manifest at its pinned commit. For the C# binding the declared framework version is read from
  `src/Directory.Packages.props`. `status: declared` means "the binding's own documentation claims
  this", not "this combination was built, loaded and run".
- The file mixes `declared` entries with `unknown` entries where the textual evidence could not be
  tied to a MaaFramework version; §8.6 re-derives the split. `unknown` means "not established",
  never "incompatible".
- No runtime compatibility matrix has been executed. Treat compatibility as a testing starting
  point, never as a support guarantee.
- Three external binding sources are registered: Go, Rust and C#. Each is independently pinned with
  its own inventory and compatibility metadata; none inherits the MaaFramework repository revision.
  The C# binding is distributed via NuGet (`Maa.Framework`), its releases align with MaaFramework 5.x
  stable tags from `v5.1.0` on (prereleases from `v5.0.0-preview.1`), and each release declares
its framework version in
  `src/Directory.Packages.props` at the pinned commit. Java is obsolete upstream and is not indexed;
  in-tree Python/NodeJS binding APIs follow the MaaFramework revision.

### 8.4 Version scope and upstream change detection

- The publish workflow indexes **MaaFramework 5.x only** (`CATALOG_MAJOR`); a higher upstream major
  makes the sync fail loudly instead of silently freezing the catalog. The catalog stays on 5.x
  until a maintainer deliberately bumps `CATALOG_MAJOR`.
- Upstream tag mutation is not detected: the sync re-reads tags and rewrites the release catalogs,
  so a moved or deleted upstream tag changes the next snapshot silently unless a hand-authored entry
  still references it. Take release identity from the pinned 40-character commit SHA, never from the
  tag name.
- Prerelease movement can produce snapshots of its own, so a catalog release does not imply a new
  stable MaaFramework release.
- The twice-daily schedule is best-effort; GitHub may delay or skip scheduled runs.

### 8.5 Distribution and operations

- **GitHub Releases is the only distribution channel**; there is no other mirror operated by this
  project. The jsDelivr URL used by the agent skill mirrors the Git tree for plain files — an
  unofficial convenience with cache delay, outside this contract.
- `maa-llm-wiki-catalog-latest.zip` is overwritten by every release; pin the versioned asset for
  anything reproducible.
- Bundles published by the current workflow carry **keyless Sigstore build provenance** created by
  the publish workflow (`actions/attest-build-provenance`), not a long-lived project signing key.
  `gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki` checks the
  attestation against GitHub's attestation store: it proves which workflow and commit produced the
  versioned zip, not intent or correctness, is only meaningful relative to this repository's
  workflow, and cannot be verified offline. The `-latest` alias and `SHA256SUMS` are convenience
  artifacts and are not attested subjects.
- **Cross-platform rebuild equality is guaranteed only from `v0.1.18`.** Bundles published before it
  were produced by a builder that left the zip host field at the platform default, so a rebuild on a
  different platform can produce the same content with a different SHA-256. Where a `SHA256SUMS`
  asset exists (`v0.1.17` onward), it still matches the published bytes; only cross-platform rebuild
  equality is not guaranteed for those older bundles.
- **Failure alerting is an issue, not a monitor.** Any failed publish run opens or updates an
  issue labelled `pipeline-failure` naming the failed steps, and the next successful run closes it.
  A run that never starts (disabled workflow, skipped schedule, hosting outage) produces nothing.
- **No SLA**: no availability, response-time or refresh guarantee. The workflow runs twice a day and
  publishes only when catalog data changes.

### 8.6 How to re-derive these numbers

```bash
# entries, distinct versions, topics, indexed releases
uv run python -c "from pathlib import Path; from maa_llm_wiki.validation import load_semantic_changes, load_source_map, load_release_catalog; r=Path('.'); c=load_semantic_changes(r); print('entries', len(c.changes), 'versions', len({x.first_version for x in c.changes}), 'topics', len(load_source_map(r).topics), 'releases', len(load_release_catalog(r).releases))"
uv run maa-wiki-validate
uv run maa-wiki-report-semantic-gaps --output /tmp/semantic-gaps.md
# optional cross-check against a pinned MaaFramework clone:
uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework --output /tmp/semantic-gaps.md
# machine-layer coverage gap: release pairs whose indexed paths changed with no structured fact
grep -c 'kind: unclassified' sources/maa-framework/machine-changes.yaml
grep -c 'status: declared' sources/compatibility/bindings.yaml
grep -c 'status: unknown' sources/compatibility/bindings.yaml
```

## 9. Licence of the bundle

Catalog data in the bundle is licensed under CC BY 4.0 (`LICENSE-DATA`); short upstream
documentation excerpts remain under their upstream licences (LGPL-3.0 for the MaaXYZ projects, see
`NOTICE`). The repository code is MIT (`LICENSE`). Redistributing a bundle must keep the attribution
notices; it does not relicense the upstream excerpts.
