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
  -> prereleases.md                # prerelease registry
  -> topics.md                     # curated topic routes (rendered from source-map.yaml)
  -> machine-changes.md            # declared API element changes by release (machine-changes.yaml)
  -> machine-symbols.md            # the same records indexed by element
  -> upstream-commits.md           # upstream commits by release (upstream-commits.yaml)
  -> <version>/index.md            # ends with "Changed since <previous release>" and Navigation
       -> documentation/index.md -> {en-us,zh-cn,tools}.md
       -> documentation/diagrams.md        # since 5.10.3
       -> bindings/index.md -> {python,nodejs,readmes}.md
       -> native-api/index.md -> {framework,toolkit,agent-client-server}.md
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
| `generated/maa-framework/index.md` | Current snapshot (latest indexed release, release and prerelease counts), the release list with pinned revisions, and links to the top-level pages below. |
| `prereleases.md` | Prerelease registry: every registered prerelease tag with its date, its commit, and the first stable release that contains it (`not merged` when none does). Prereleases get no inventory. |
| `topics.md` | Curated topic routes rendered from `sources/maa-framework/source-map.yaml`: per topic, every variant's applicable release (`applies_to`), revision, pinned file links, symbols, and literal search terms. |
| `machine-changes.md` | Declared API elements that changed between consecutive registered releases, rendered from `sources/maa-framework/machine-changes.yaml` and grouped by release and file. Each record is `added`, `removed`, `modified` (with `previous_quote`, the earlier upstream text) or `deprecated`, with upstream text and the file path; tables at the top count records by kind and by release. Coverage and `unclassified` records are described under *Machine layer and commit index* below. |
| `machine-symbols.md` | The same records indexed by element: every element that changed at least once, with its kind, its file, the release that introduced it (`≤ <first release>` when the first indexed release already declared it) and its later changes. It answers "which release introduced X" for every listed element; an element that never changed is not listed, so read the pinned file of the release you target. |
| `upstream-commits.md` | Every upstream non-merge commit between consecutive registered releases, rendered from `sources/maa-framework/upstream-commits.yaml` and filed under the first release that contains it. Each release section has a compare link; each commit shows its subject and up to five of its changed paths. Use it for behaviour changes that no declaration shows, then read the commit's diff at the pinned SHA. |
| `<version>/index.md` | Domain index for one release. Its `Changed since <previous indexed release>` section lists indexed material added, content-changed (by git blob id) and removed relative to the previous release, with counts, a per-class listing cap, and an `... and K more <label>` overflow line. The first indexed release says `Changed since the previous release` and notes there is no previous inventory. This is indexed **material** movement, not a behaviour change. |

Each per-version `index.md` ends with a Navigation block: all versions, the previous and next
release, and the top-level topic, machine-change, machine-symbol, upstream-commit and prerelease
pages. Binding version pages follow the same pattern: compatibility evidence, registry links, a
`Changed since <previous>` section computed from the per-release inventories, and a Navigation block
with all versions, the previous and next release, and the prerelease registry.

The per-version index is the cheap, bundle-local summary; `maa-wiki-diff` (see below) prints the
complete, untruncated list. Every top-level page is a rendered view and must not be hand-edited:
`source-map.yaml` is the only hand-authored catalog, while `machine-changes.yaml` and
`upstream-commits.yaml` are generated by sync.

### Machine layer and commit index

`sources/maa-framework/machine-changes.yaml` is the machine layer. Each registered release pins every
indexed file to a git blob; the extractor parses the files that declare API elements at every release
and compares the declarations of consecutive releases:

- C/C++ headers under `include/`: functions including class methods, struct fields, enum values,
  `#define Maa*` constants, typedefs, and callback messages (`MaaMsg_*`);
- the in-tree Python and NodeJS bindings: Python `module:qualname` symbols and NodeJS declarations;
- the JSON schemas under `tools/`: definitions, `allOf`/`anyOf`/`oneOf` branches (a branch that only
  references a definition included), properties, enum and const values, required names and defaults;
- documents 3.1 and 3.3: the rows of their protocol version tables.

Record kinds are `enum-value`, `public-function`, `callback-message`, `constant`, `struct-field`,
`type-definition`, `schema-definition`, `schema-branch`, `schema-property`, `schema-enum`, `schema-default`,
`schema-required`, `documentation-version`, `binding-api` and `unclassified`. Each record is
`added`, `removed`, `modified` (with `previous_quote`) or `deprecated`, with upstream text and paths.

C declarations, Python modules and NodeJS declarations are compared across all files of their
language, so a declaration that only moves to another file is not reported; schema and documentation
elements are compared within their file. Signatures leave out comments and formatting, so
reformatting is not a change. An `unclassified` record marks one changed header, binding or schema
file whose declarations did not change (its comments or formatting changed, or a construct the
parser does not read), or any parsed file that could not be parsed. Documentation prose has no
parser, including the prose of documents 3.1 and 3.3: its changes appear in the version pages'
`Changed since` lists and in the commit index. The layer states what changed in the declarations,
never runtime semantics, intent, or whether a change matters.

`sources/maa-framework/upstream-commits.yaml` is the commit index: every upstream non-merge commit
between consecutive registered releases, filed under the first release that contains it, with its
subject, the pull-request number from a trailing `(#N)` in the subject, its `path_count`, and up to
20 of its changed paths. Commits whose subject ends with `[skip changelog]` (automated formatting
and submodule updates) are left out, and commits up to the first registered release are not listed.
A change of runtime behaviour behind an unchanged declaration produces no machine record; find its
commit here, then read the diff at the pinned SHA. A commit subject states the author's intent, not
verified behaviour.

Both files are generated by `maa-wiki-sync-maafw-history`, which also renders their pages, and by
`maa-wiki-extract-changes`, which writes only the two files. `maa-wiki-extract-changes --check`
compares both with a fresh extraction; the publish step `Check machine change catalog is current`
runs it. `CATALOG-CONTRACT.md` §8.1 states the coverage limits.

### Repository layout

| Path | Purpose |
| --- | --- |
| `sources/repositories.yaml` | Registered upstream repositories and their active pinned revisions. |
| `sources/maa-framework/` | Release catalog, inventories (`inventory.yaml` plus historical `inventories/*.yaml`), the hand-authored `source-map.yaml`, and the generated `machine-changes.yaml` and `upstream-commits.yaml`. |
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
(`blob`, a 40-character SHA), so the same file across releases is distinguishable by content hash:
`maa-wiki-diff` and the `Changed since` sections compare these ids offline from the committed
inventories alone, and the machine-layer extractor reads the pinned blobs from the upstream clone.

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
- `Indexed material moved` — per-source added/removed/content-changed counts.
- `Catalog files changed` — added/removed/changed counts and examples under `generated/`, `sources/`
  and `schemas/`, so packaging-only snapshots are quantified too.
- `Verification` — checksum, attestation and stand-alone verifier commands.
- `Assets` — with `--bundle`, the zip's sha256, size and file count, plus the other assets.
- `Documentation` — start pages (`index.md`, `machine-symbols.md`), the contract, the bundled
  documents, known gaps (§8), `machine-changes.md`, `upstream-commits.md`, and the full changelog
  link.

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
| `Check machine change catalog is current` | The committed `machine-changes.yaml` or `upstream-commits.yaml` does not match a fresh extraction from the upstream clone. | Re-run `maa-wiki-sync-maafw-history` and commit the regenerated files; never hand-edit them. |
| `Guard hand-authored catalogs` | Synchronization wrote `sources/maa-framework/source-map.yaml`, the only hand-authored catalog. | Treat as a defect in sync/extraction; the source map is committed explicitly by maintainers or agents. |
| `Validate generated source indexes` | One of the required checks failed. | The step log names the failing check; fix code or data and re-run. |
| `Classify catalog state` | `force=true` was requested while the working tree changed. | Re-run without `force` so the catalog update is committed and validated normally. |
| `Push snapshot tag` | The computed tag already exists at a different commit. | Nothing is moved automatically; resolve the tag/release mismatch manually. |

### `pipeline-failure` issue

When any step fails (`if: failure()`), the workflow opens or updates an issue labelled
`pipeline-failure`. The body names the failed steps, links the run and the commit, and repeats the
deliberate-guard guidance above. Duplicate reports are deduplicated by the body hash: the issue is
edited only when its content changes. The issue steps are `continue-on-error`, so they never mask the
original failure. The next successful run closes the issue (`if: success()`).

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
```

`vX.Y.Z` and `<40-char SHA>` are placeholders.

- `maa-wiki-sync-maafw-history` is the only MaaFramework sync. It re-indexes every stable release of
  the given major, rewrites the release and prerelease registry (`releases.yaml`) and the pinned
  revision in `sources/repositories.yaml`, writes every per-release inventory, `inventory.yaml`
  (the latest release), `machine-changes.yaml` and `upstream-commits.yaml`, and renders every page
  under `generated/maa-framework/`. It reads `source-map.yaml` to render `topics.md` and never
  writes it.
- `maa-wiki-extract-changes` extracts `machine-changes.yaml` and `upstream-commits.yaml` from the
  clone and writes both files; it does not render pages, which the history sync does. With
  `--check` it writes nothing, compares both files with a fresh extraction, and exits non-zero on
  any difference; the publish step `Check machine change catalog is current` runs this form.
- `maa-wiki-diff` compares the inventories of two indexed releases and lists added, removed and
  content-changed artifacts using the recorded `blob` ids, without an upstream clone. `--source`
  selects the source (default `maafw`); `--format json` is for tooling.
- `maa-wiki-release-notes` renders the release body described above. `--previous` is omitted for the
  first snapshot.
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
C# binding releases, and `machine-changes.yaml` and `upstream-commits.yaml` are rebuilt by sync on
every run.
