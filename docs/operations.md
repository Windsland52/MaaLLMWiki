# MaaLLMWiki operations

This document is for operators and contributors who need the full picture of how the catalog is
navigated, produced, published and recovered. Consumer guarantees and verification rules live in
[`CATALOG-CONTRACT.md`](../CATALOG-CONTRACT.md); contributor rules and the required checks live in
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Layout and navigation

### Generated tree

The bundle and this repository contain the same generated navigation under `generated/`:

```text
generated/maa-framework/index.md
  -> topics.md                     # curated topic routes (rendered from source-map.yaml)
  -> behaviour-changes.md          # curated behaviour changes (rendered from semantic-changes.yaml)
  -> machine-changes.md            # machine-extracted change facts (generated from upstream diffs)
-> machine-symbols.md            # the same facts indexed by symbol
  -> <version>/index.md            # ends with a "Changed since <previous indexed release>" section
       -> documentation/index.md -> {en-us,zh-cn,tools}.md
       -> documentation/diagrams.md        # since 5.10.3
       -> bindings/index.md -> {python,nodejs,readmes}.md
       -> native-api/index.md -> {framework,toolkit,agents}.md
       -> native-api/control-units.md      # since 5.10.0
       -> schemas.md
```

`documentation/diagrams.md` and `native-api/control-units.md` exist only in releases that first
contained them; other version directories do not have those files. `generated/maa-framework-{go,rs,csharp}/`
holds the equivalent version/domain indexes for the Go, Rust and C# bindings.

Each generated entry carries a title, a first-paragraph excerpt, and a link to the original source at
a pinned commit; the catalog does not copy upstream full text and needs no manual chunking,
embedding, or vector database. MaaFramework source remains in its own Git repository and is searched
at the selected immutable revision.

Three external binding sources are registered beside MaaFramework: Go, Rust and C#. Each is
independently pinned with its own inventory and compatibility evidence; none inherits the
MaaFramework revision. The C# binding is distributed via NuGet as `Maa.Framework`, its indexed
stable releases align with MaaFramework 5.x tags from `v5.1.0` on (prereleases start at
`v5.0.0-preview.1`), and each release declares its framework
version in `src/Directory.Packages.props` at the pinned commit. All three upstream bindings are
LGPL-3.0 (see `NOTICE`).

### Page meanings

| Page | Contents |
| --- | --- |
| `generated/maa-framework/index.md` | Release list with pinned revisions, the prerelease registry, and links to the three top-level indexes below. |
| `topics.md` | Curated topic routes rendered from `sources/maa-framework/source-map.yaml`: per topic, every variant's applicable release (`applies_to`), revision, pinned file links, symbols, and literal search terms. |
| `behaviour-changes.md` | Curated behaviour history rendered from `sources/maa-framework/semantic-changes.yaml`, grouped by the release that first carried the change, with pinned links. Optional interpretation layer. |
| `machine-changes.md` | Machine-extracted facts from upstream diffs: enum values, public functions, callback messages, JSON-schema properties/enums/defaults/required, interface protocol versions, and binding API names. Each structured record carries upstream evidence (verbatim added/removed lines for text changes, canonical JSON fragments for schema changes) and indexed paths. Records an explicit `unclassified` entry when a release pair changed indexed material without producing a structured record. |
| `machine-symbols.md` | The same records grouped by symbol: first release where the symbol appears and every later release that touched it, with links into the per-release pages. The quickest answer to "which release introduced X". |
Binding version pages follow the same pattern: compatibility evidence, registry links, a `Changed since <previous>` section computed from the per-release inventories, and a navigation block with the previous/next release, all versions and the prerelease registry.
Each per-version `index.md` ends with a Navigation block: previous and next release, all versions, and the top-level topic, machine and prerelease pages.
| `<version>/index.md` | Domain index for one release. It ends with `Changed since <previous indexed release>`: indexed material added, content-changed (by git blob id) and removed relative to the previous release, with counts, a per-class listing cap, and an `... and K more <label>` overflow line. The first indexed release says `Changed since the previous release` and notes there is no previous inventory. This is indexed **material** movement, not a behaviour change. |

The per-version index is the cheap, bundle-local summary; `maa-wiki-diff` (see below) prints the
complete, untruncated list. Behaviour changes live in `behaviour-changes.md` /
`semantic-changes.yaml`; appearance facts live in `machine-changes.md`. The rendered pages live at
`generated/maa-framework/topics.md`, `generated/maa-framework/behaviour-changes.md` and
`generated/maa-framework/machine-changes.md`. Both are rendered views:
`source-map.yaml` and `semantic-changes.yaml` are the curated sources of truth, while
`machine-changes.yaml` is generated by sync and must not be hand-edited.

### Repository layout

| Path | Purpose |
| --- | --- |
| `sources/repositories.yaml` | Registered upstream repositories and their active pinned revisions. |
| `sources/maa-framework/` | Release catalog, inventories (`inventory.yaml` plus historical `inventories/*.yaml`), curated `source-map.yaml` and `semantic-changes.yaml`, and generated `machine-changes.yaml`. |
| `sources/maa-framework-{go,rs,csharp}/` | Independent Go/Rust/C# binding release catalogs and inventories, each pinned separately. |
| `sources/compatibility/` | Evidence-backed binding compatibility metadata. |
| `generated/` | Generated navigation indexes for all sources; do not hand-edit. |
| `schemas/` | Generated metadata JSON schemas, including the bundle manifest schema. |
| `skills/maallmwiki/SKILL.md` | Installable agent skill for the routing procedure. |
| `src/maa_llm_wiki/` | Python synchronization, extraction, bundling and verification tooling. |
| `tests/` | Deterministic repository checks. |
| Root documents | `CATALOG-CONTRACT.md` (consumer contract), `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `LICENSE-DATA`, `NOTICE`. |

`sources/maa-framework/inventory.yaml` is the flat canonical artifact manifest used for coverage
checks; it is not the navigation interface. Every indexed artifact records its git blob id
(`blob`, a 40-character SHA), so the same file across releases is distinguishable by content hash and
`maa-wiki-report-semantic-gaps` can compare content offline from the committed inventories alone.

## Snapshot lifecycle

### Schedule and dispatch

- Scheduled runs: twice daily at 03:17 and 15:17 UTC (`cron: "17 3,15 * * *"`, about 11:17 and
  23:17 UTC+8). Scheduled runs are best-effort: GitHub may delay or skip them.
- Manual runs: `workflow_dispatch` accepts a boolean `force` input (default `false`). `force=true`
  publishes a packaging-only snapshot when catalog data is unchanged; it is rejected when the
  working tree changed, because that path must commit and validate the catalog update normally.
- `concurrency.group` is `publish-catalog` with `cancel-in-progress: false`; the job timeout is 30
  minutes.

### Classification branches

After checking out the catalog branch and the four upstream clones, each run re-indexes every stable
MaaFramework 5.x tag (`CATALOG_MAJOR`, currently `5`) plus every stable Go, Rust and C# binding tag,
regenerates schemas, runs the machine-catalog gate, and then classifies the catalog state:

1. **Working tree changed** (`git status --porcelain` non-empty): `changed=true`, `publish=true`.
   `force=true` is an error on this branch.
2. **Clean tree, no snapshot tag exists**: `publish=true`; this is the first snapshot.
3. **Clean tree, catalog paths moved since the latest snapshot tag**: `publish=true`; a new snapshot
   is due.
4. **Clean tree, HEAD is exactly the latest tag but its release/zip is missing**: `publish=true`;
   the run republishes that revision.
5. **Clean tree, `force=true`**: `publish=true`; packaging-only snapshot even though the catalog data
   did not change.
6. **Otherwise**: `publish=false`; the run only syncs and classifies (no checks, no commit, no
   release).

For publishing runs the required checks run before anything is committed:
`uv run maa-wiki-validate`, `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run pyright`, and `git diff --check`.

### Commit and version arithmetic

The commit step stages everything, then rejects any staged path outside `sources/`, `generated/`, and
`schemas/`, runs `git diff --cached --check`, commits with the fixed catalog-update message, rebases
on the remote default branch (`git pull --rebase --autostash`), and pushes.

Snapshot versions are derived from tags, not from upstream versions: if HEAD is exactly tagged, the
run reuses that tag (interrupted-publish recovery); otherwise it takes the latest `vX.Y.Z` tag,
increments the patch component, and skips any version that already exists. With no previous tag the
first snapshot is `v0.1.0`.

### Why one workflow

Detection, commit, tag and release stay in a single job because events produced with the default
`GITHUB_TOKEN` do not start another workflow. Splitting tag creation into a workflow triggered by a
push would silently leave a tag without its release.

## Release assembly

The order is fixed: build bundle → verify bundle → copy the `latest` alias → write checksums → run
the stand-alone verifier → render release notes → attest provenance → push the tag → publish the
release. The release body is rendered before attest/tag/release, so a failed render cannot leave a
tag without its intended body.

### Assets

| Asset | Meaning |
| --- | --- |
| `maa-llm-wiki-catalog-vX.Y.Z.zip` | Immutable versioned bundle for that tag; the only attested subject. |
| `maa-llm-wiki-catalog-latest.zip` | Byte-identical convenience copy of the newest bundle; overwritten by every release. |
| `SHA256SUMS` | Checksums covering both zip download names. |
| `verify_bundle.py` | Byte-for-byte copy of `src/maa_llm_wiki/verify_bundle.py`; the dependency-free verifier. |

The versioned zip contains `sources/`, `generated/`, `schemas/`, `catalog-manifest.json`, and the
consumer documents (`START-HERE.md`, READMEs, `CATALOG-CONTRACT.md`, `CONTRIBUTING.md`, `SECURITY.md`,
`docs/operations.md` and its Chinese mirror, `LICENSE`, `LICENSE-DATA`, `NOTICE`). The
manifest's `api_version` is `maa-llm-wiki-catalog/v1`; `wiki_revision` records the build commit;
`working_tree_clean` records whether the build came from a clean tree; `catalog_version` records the
bundle's tag (older bundles may omit it); `sources` pins the MaaFramework, Go, Rust and C# versions
and 40-character commits; `files` lists `path`, `size_bytes`, and `sha256` for every bundled file
other than the manifest. Field semantics, the v1 stability rules, and the integrity invariants are in
`CATALOG-CONTRACT.md`; the machine-readable schema ships in the bundle as
`schemas/catalog-bundle-manifest.schema.json`.

Builds refuse a dirty working tree. `--allow-dirty` exists only for local development and tests.
Release builds pass `--version vX.Y.Z` (the value is written to the manifest's `catalog_version`) and
verify the result with
`uv run maa-wiki-verify-bundle --bundle <zip> --expect-version vX.Y.Z --expect-revision <40-char SHA>`
before upload. A snapshot is built from the committed catalog revision, so its tag names exactly the
catalog it carries.

The `latest` alias is uploaded by the current workflow: historical releases may lack it, and it is
overwritten in place, so it is not reproducible. Discovery of the newest versioned asset is through
the Releases API (`https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest`).

A minimal consumer check, with the downloaded assets in the current directory:

```powershell
Invoke-WebRequest https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip -OutFile maa-llm-wiki-catalog-latest.zip
uv run maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-latest.zip
```

### Checksums and provenance

`SHA256SUMS` is generated inside `dist/` so `sha256sum -c SHA256SUMS` works in the directory where a
consumer downloaded the assets; the workflow also checks the file against both zips. It is a release
asset but is not attested, and it does not cover `verify_bundle.py`; compare its digest against the
asset digest returned by the Releases API when authenticating the checksum file. Releases that
predate this asset have no `SHA256SUMS`.

The versioned zip carries a keyless Sigstore build-provenance attestation recorded by the publish
workflow (short-lived OIDC token, `actions/attest-build-provenance`). Verify it with
`gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`; this needs
network access and a published attestation record. It proves which workflow and commit produced the
asset, not that the catalog content is correct. The `latest` alias, `SHA256SUMS` and
`verify_bundle.py` are not attested subjects, and releases published before provenance was introduced
have no attestation.

### Verification tools

- `uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z] [--expect-revision SHA]`
  reads only the zip, works offline, and prints the whole-bundle `sha256=…`. The workflow runs the
  same verification against the freshly built bundle.
- `verify_bundle.py` performs the same manifest/zip/checksum/expectation checks with only Python 3
  (3.10+, standard library), fully offline. It accepts `--bundle`, `--expect-version`,
  `--expect-revision`, and `--checksums`; its release asset is a copy of the in-repo script, and the
  copy in a release is the verifier current at publish time.
- When uv is available but a checkout is not,
  `uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle <zip>`
  builds the package from git (Python 3.13 selected via `requires-python`) and runs the same tool.

### Release body

The body is generated by `maa-wiki-release-notes` from the catalog itself, so it reflects exactly
what the snapshot contains. It contains:

- `Upstream snapshot` — per-source versions and pinned revisions.
- `New upstream releases since <previous tag>` — or a statement that there are none.
- `Machine-extracted changes` — extracted facts for the new releases, with counts by kind.
- `Curated behaviour changes` — only when new curated entries exist; may be absent.
- `Indexed material moved` — per-source added/removed/content-changed counts.
- `Catalog files changed` — added/removed/changed counts and examples under `generated/`, `sources/`
  and `schemas/`, so packaging-only snapshots are quantified too.
- `Verification` — checksum, attestation and stand-alone verifier commands.
- `Assets` — with `--bundle`, the zip's sha256, size and file count, plus the other assets.
- `Documentation` — contract, known gaps (§8), machine/behaviour pages, and the full changelog link.

The full changelog link remains at the end of the body.

### History and interrupted publishes

From `v0.1.3` onward, snapshot tags and the release that ships their bundle are produced by this
workflow. `v0.1.0` and `v0.1.1` predate the consolidation (the repository then used
`release-catalog.yml` / `sync-maafw.yml`) and also carry bundles. `v0.1.2` is an annotated tag from
2026-08-31 with no GitHub Release, so it carries no bundle asset; its number is not reused.

If a catalog revision has no snapshot tag, the next run creates a new tag and release. If the revision
is already tagged but the release or zip asset is missing, the run reuses the existing tag instead of
creating another. Either kind of interruption heals on the next run.

## Failure handling

### Guard failures

Most publish failures are deliberate guards asking for a decision rather than broken code:

| Guard / failing step | Meaning | Action |
| --- | --- | --- |
| `Sync Maa source indexes` | Upstream has a higher MaaFramework major than `CATALOG_MAJOR`, or the upstream tag list shrank. | Raise `CATALOG_MAJOR` in the workflow after review; confirm removed tags really disappeared, and only then use the explicit `--prune` flag by hand. The workflow never passes `--prune`. |
| `Check machine change catalog is current` | The committed `machine-changes.yaml` no longer matches a fresh extraction of the upstream diffs. | Re-run sync/extraction and commit the regenerated catalog; never hand-edit it. |
| `Guard hand-authored catalogs` | Synchronization wrote `source-map.yaml` or `semantic-changes.yaml`. | Treat as a defect in sync/extraction; curated files are committed explicitly by maintainers or agents. |
| `Validate generated source indexes` | One of the required checks failed. | The step log names the failing check; fix code or data and re-run. |
| `Classify catalog state` | `force=true` was requested while the working tree changed. | Re-run without `force` so the catalog update is committed and validated normally. |
| `Push snapshot tag` | The computed tag already exists at a different commit. | Nothing is moved automatically; resolve the tag/release mismatch manually. |

### `pipeline-failure` issue

When any step fails (`if: failure()`), the workflow opens or updates an issue labelled
`pipeline-failure`. The body names the failed steps, links the run and the commit, and repeats the
deliberate-guard guidance above. Duplicate reports are deduplicated by the body hash: the issue is
edited only when its content changes. The issue steps are `continue-on-error`, so they never mask the
original failure. The next successful run closes the issue (`if: success()`).

### Semantic-review issue

At the end of every run (`if: always()`) the workflow runs
`uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework` unless the MaaFramework clone is
unavailable. It compares titles and first-paragraph excerpts as well as the `blob` recorded in each
inventory for indexed releases newer than the newest `semantic-changes.yaml` entry. If the queue is
non-empty it opens or updates an issue labelled `semantic-review`; the issue body is updated only
when its hash changes, and the issue is closed when the queue becomes empty. Machine-extracted facts
are already published automatically, so a curated `semantic-changes.yaml` entry is optional
interpretation, not a required review step. The report lists suspected triggers, not verified
changes; paths outside the indexed set remain invisible (see `CATALOG-CONTRACT.md` §8).

### Tag/release reconciliation

A final `if: always()`, `continue-on-error` step lists snapshot tags and GitHub Releases and warns
(plus adds a job-summary entry) when a snapshot tag has no release or a release lacks its catalog
asset. It never modifies anything. `v0.1.2` is the documented legacy allowlist: it predates the
pipeline and intentionally has no release.

### Authentication

The job authenticates with the repository `GITHUB_TOKEN`. It declares `contents: write`,
`issues: write`, `id-token: write`, and `attestations: write` (the OIDC token is needed for the
provenance attestation). If the default branch requires pull requests, add a `CATALOG_PUSH_TOKEN`
secret — a fine-grained token with contents and issues write from an identity allowed to bypass that
rule — and the workflow prefers it automatically.

## Development commands

### Clone assumptions

Put the upstream clones under `tmp/` exactly as the publish workflow does:
`tmp/MaaFramework`, `tmp/maa-framework-go`, `tmp/maa-framework-rs`, and
`tmp/MaaFramework.Binding.CSharp`. Use the repository URLs from
`.github/workflows/publish-catalog.yml`. Python is pinned to 3.13 via `requires-python`.

### Commands

```powershell
uv sync --locked
uv run maa-wiki-sync-latest-maafw --repository tmp/MaaFramework
uv run maa-wiki-sync-maafw-history --repository tmp/MaaFramework --major 5
uv run maa-wiki-sync-bindings-history `
  --repository maa-framework-go=tmp/maa-framework-go `
  --repository maa-framework-rs=tmp/maa-framework-rs `
  --repository maa-framework-csharp=tmp/MaaFramework.Binding.CSharp
uv run maa-wiki-extract-changes --repository tmp/MaaFramework --check
uv run maa-wiki-build-bundle --output dist/maa-llm-wiki-catalog-vX.Y.Z.zip --version vX.Y.Z
uv run maa-wiki-verify-bundle --bundle dist/maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --expect-revision <40-char SHA>
uv run maa-wiki-diff --from 5.14.3 --to 5.15.0
uv run maa-wiki-release-notes --root . --version <tag> [--previous <previous tag>] --bundle <zip> --output <path>
uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework
```

`vX.Y.Z` and `<40-char SHA>` are placeholders.

- `maa-wiki-diff` compares the inventories of two indexed releases and lists added, removed and
  content-changed artifacts using the recorded `blob` ids, without an upstream clone. `--source`
  selects the source (default `maafw`); `--format json` is for tooling.
- `maa-wiki-release-notes` renders the release body described above. `--previous` is omitted for the
  first snapshot.
- The single-version command only regenerates the default inventory:
  `uv run maa-wiki-sync-maafw --version <version> --repository tmp/MaaFramework` rebuilds only
  `sources/maa-framework/inventory.yaml`, accepts only releases registered in
  `sources/maa-framework/releases.yaml`, and must point at the currently indexed latest release or
  `maa-wiki-validate` fails.
- History sync refuses to drop registered releases or prereleases by default. `--prune` is a
  dangerous, manual-only escape hatch for upstream tags that were really deleted; its help text says
  "do NOT pass from automation", and the publish workflow never passes it.

### Required checks

From `AGENTS.md`, exactly:

```powershell
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
git diff --check
```

### Repository state

The active revisions are recorded in `sources/repositories.yaml`; immutable release histories live
below each source directory. The current automation indexes all stable MaaFramework v5, Go, Rust and
C# binding releases, and `machine-changes.yaml` is rebuilt by sync on every run.
