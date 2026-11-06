# MaaLLMWiki

**English** | [中文](README.md)

MaaLLMWiki provides machine-readable, versioned source catalogs for Maa ecosystem knowledge. It
helps a model select and find original documentation, schemas, public APIs, and source code; it
does not author or replace those sources. Catalog snapshots published by the publish workflow are
available as verifiable catalog bundles; the consumer contract is `CATALOG-CONTRACT.md`.

## Scope

Included:

- complete version-pinned MaaFramework documentation, schema, native API, and in-tree binding API
  indexes;
- independently versioned Go and Rust binding API indexes with explicit compatibility evidence;
- topic-to-source navigation and semantic version changes.

Excluded:

- project-specific documentation and Pipeline configuration;
- raw user artifacts and benchmark answers;
- full copies of MaaFramework documentation or source trees (the index keeps titles, auto-extracted
  first-paragraph excerpts, and pinned source links only);
- manually authored tutorials, best practices, and diagnostic methodology;
- unverified model-generated conclusions.

Binding scope: only the Go and Rust bindings are registered as independent external sources, each
with its own pinned inventory and MaaFramework compatibility metadata. The C# and Java bindings are
not registered — Java is marked obsolete by the MaaFramework documentation, and C# has no registered
pinned source. The native public API is the C/C++ headers; in-tree Python/NodeJS binding APIs are
indexed with the MaaFramework version.

## Layout

```text
CATALOG-CONTRACT.md             Consumer contract for catalog bundles (manifest, discovery, verification, limitations)
sources/repositories.yaml       Registered upstream repositories
sources/maa-framework/          Release, inventory, semantic-change, and source-route metadata
sources/maa-framework-{go,rs}/  Independent binding releases and source inventories
sources/compatibility/          Evidence-backed binding compatibility metadata
generated/maa-framework/        Generated release, domain, topic, behaviour-change, and machine-change navigation indexes
generated/maa-framework-{go,rs}/ Generated binding release navigation indexes
schemas/                        Generated metadata JSON schemas
skills/maallmwiki/              Installable agent skill for the routing procedure
src/maa_llm_wiki/               Python synchronization, bundling, and verification tooling
tests/                          Deterministic repository checks
LICENSE                         Code licence (MIT)
LICENSE-DATA                    Catalog data licence (CC BY 4.0)
NOTICE                          Licence and attribution for upstream documentation excerpts
SECURITY.md                     Security policy and private reporting channel
CONTRIBUTING.md                 Contribution workflow, content classes, and required checks
```

Security reporting is described in [SECURITY.md](SECURITY.md); the contribution workflow and content
classes are in [CONTRIBUTING.md](CONTRIBUTING.md).

Each generated entry carries a title, a first-paragraph excerpt, and a link to the original source
at a pinned commit; the index does not copy upstream full text, and querying it needs no manual
chunking, embedding, or vector database. MaaFramework source remains in its own Git repository and
is searched at the selected immutable revision.

Generated navigation is layered as follows:

```text
generated/maa-framework/index.md
  -> topics.md                     # curated topic routes (rendered from source-map.yaml)
  -> behaviour-changes.md          # curated behaviour changes (rendered from semantic-changes.yaml; optional interpretation layer)
  -> machine-changes.md            # machine-extracted change facts (generated from upstream diffs)
  -> <version>/index.md            # ends with a "Changed since <previous indexed release>" section
       -> documentation/index.md -> {en-us,zh-cn,nodejs,tools}.md
       -> documentation/diagrams.md        # since 5.10.3
       -> bindings/index.md -> {python,nodejs}.md
       -> native-api/index.md -> {framework,toolkit,agents}.md
       -> native-api/control-units.md      # since 5.10.0
       -> schemas.md
```

`diagrams.md` and `control-units.md` exist only in some versions; other version directories do not
contain them.

Each `<version>/index.md` ends with a `Changed since` section: the heading is `Changed since`
followed by the previous indexed release in backticks, and it summarises the **indexed material**
added, content-changed, and removed relative to the previous release using the `blob` ids recorded
in the inventories. When something changed it starts with counts and then lists entries per class,
with a per-class listing cap; overflow is shown as `... and K more <label>`, and `maa-wiki-diff`
has the full list. When nothing changed there is a single line saying so. The first indexed release
says `Changed since the previous release` and notes there is no previous inventory to compare. It
answers "which indexed files moved in this release" — **it is not a behaviour change**; behaviour
changes live in `behaviour-changes.md` / `semantic-changes.yaml`.

`topics.md` and `behaviour-changes.md` are rendered navigation for curated metadata: the former
lists, per topic, every variant's applicable release (`applies_to`), revision, pinned file links,
symbols, and literal search terms; the latter groups recorded cross-version behaviour changes by the
release that first carried them and links each entry to its pinned source. Both are rendered from
`sources/maa-framework/source-map.yaml` and `sources/maa-framework/semantic-changes.yaml` — the YAML
files remain the curated source of truth, and the pages simply let a model walk the navigation
without knowing those two paths in advance; `index.md` links them.

`machine-changes.md` is the machine-extracted layer: sync mechanically extracts enum values, public
functions, callback messages, JSON-schema properties/enums/defaults/required, interface protocol
versions, and binding API names from the upstream diff between consecutive releases. Each structured
record carries upstream evidence (verbatim added/removed lines for text changes, canonical JSON
fragments for schema changes) and the indexed paths it came from, answering "which release introduced
this enum value / field / function". It is extraction evidence, not interpretation, and it cannot
state runtime semantics or whether a change matters. When a release pair changed indexed paths but
produced no structured record, that is listed explicitly as `unclassified` (one line plus the
changed files), so extractor gaps stay visible. `behaviour-changes.md` is the optional curated
interpretation layer: it adds significance and routing guidance but no detection. The machine layer
is rebuilt by sync on every run — no agent or manual step is required.

`sources/maa-framework/inventory.yaml` remains the flat canonical artifact manifest used for
coverage checks. It is not the navigation interface. Every indexed artifact records the git blob id
of its content (`blob`, a 40-character SHA): copies of the same file across releases are therefore
distinguishable by content hash, and `maa-wiki-report-semantic-gaps` can make content-level
comparisons from the committed inventories alone, without cloning the upstream repository.

## Development

```powershell
uv sync --locked
uv run maa-wiki-sync-latest-maafw --repository tmp/MaaFramework
uv run maa-wiki-sync-maafw-history --repository tmp/MaaFramework --major 5
uv run maa-wiki-sync-bindings-history --go-repository tmp/maa-framework-go --rust-repository tmp/maa-framework-rs
uv run maa-wiki-build-bundle --output dist/maa-llm-wiki-catalog-vX.Y.Z.zip --version vX.Y.Z
uv run maa-wiki-verify-bundle --bundle dist/maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --expect-revision <40-char SHA>
uv run maa-wiki-diff --from 5.14.3 --to 5.15.0
uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
git diff --check
```

`vX.Y.Z` and `<40-char SHA>` are placeholders. The sync commands require the upstream clones to be
checked out under `tmp/` first, using the repository URLs from the publish workflow
(`tmp/MaaFramework`, `tmp/maa-framework-go`, `tmp/maa-framework-rs`).

`maa-wiki-diff` compares the inventories of two indexed releases and lists added, removed, and
content-changed artifacts. It uses the `blob` recorded in each inventory to decide whether content
changed and needs no upstream clone; `--source` selects the source (default `maafw`), and
`--format json` is available for machine consumption. The per-version `Changed since` section is the
cheap, bundle-local summary (with per-class caps); use `maa-wiki-diff` when you need the full,
untruncated list. Example: `uv run maa-wiki-diff --from 5.14.3 --to 5.15.0`.

The single-version command only regenerates the default inventory:
`uv run maa-wiki-sync-maafw --version <version> --repository tmp/MaaFramework` only rebuilds
`sources/maa-framework/inventory.yaml`, and only accepts releases registered in
`sources/maa-framework/releases.yaml`; it must match the currently indexed latest release or
`maa-wiki-validate` fails. Use `maa-wiki-sync-maafw-history` to rebuild the full history.

History sync (`maa-wiki-sync-maafw-history` and `maa-wiki-sync-bindings-history`) refuses to drop
registered releases or prereleases by default: if the local clone is missing a registered tag, the
command errors instead of silently shrinking the catalog. `--prune` exists only for the case where
upstream really deleted tags — it deletes catalog data and is a dangerous escape hatch; its help
text says "do NOT pass from automation", and the publish workflow never passes it.

The active revisions are recorded in `sources/repositories.yaml`; immutable release histories are
stored below each source directory. The current automation indexes all stable MaaFramework v5, Go
binding, and Rust binding releases.

## Catalog snapshots

Tagged releases publish a versioned `maa-llm-wiki-catalog-vX.Y.Z.zip` asset containing `sources/`,
`generated/`, `schemas/`, and a `catalog-manifest.json`; publishing also uploads the convenience
alias `maa-llm-wiki-catalog-latest.zip`. The manifest's `api_version` is
`maa-llm-wiki-catalog/v1`; `wiki_revision` records the build commit, `working_tree_clean` records
whether the build came from a clean tree, `catalog_version` records the bundle's tag (older bundles
may omit it), `sources` pins the versions and 40-character commits of MaaFramework, Go, and Rust,
and `files` lists `path`, `size_bytes`, and `sha256` for every bundled file other than the manifest
itself. Field semantics, the v1 stability rules, and the integrity invariants are defined in
`CATALOG-CONTRACT.md`; the machine-readable schema ships in the bundle as
`schemas/catalog-bundle-manifest.schema.json`.

A snapshot is built from the committed catalog revision, so its tag names exactly the catalog it
carries; `maa-wiki-build-bundle` refuses a dirty working tree, and `--allow-dirty` exists only for
local development and tests. Release builds must pass `--version vX.Y.Z` (the value is written to
the manifest's `catalog_version`), and must be verified before upload with
`uv run maa-wiki-verify-bundle --bundle <zip> --expect-version vX.Y.Z --expect-revision <40-char SHA>`.

From `v0.1.3` onward, snapshot tags and the release that ships their bundle are produced by the
publish workflow described below; the earlier `v0.1.0` and `v0.1.1` releases predate the
consolidation (the repository then used `release-catalog.yml` / `sync-maafw.yml`) and also carry
bundles. A catalog revision without a snapshot tag gets a new tag and release on the next run; a
revision that is already tagged but whose release or zip asset is missing reuses the existing tag
instead of creating another. Either kind of interruption heals on the next run. `v0.1.2` is an
annotated tag from 2026-08-31 with no GitHub Release, so it carries no bundle asset; its number is
not reused.

### Download and verification

Stable alias for the newest snapshot:

```text
https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip
```

This convenience alias is uploaded by the current publish workflow at release time; historical
releases (for example `v0.1.14`) do not have it — use the versioned
`maa-llm-wiki-catalog-vX.Y.Z.zip` for those.

The convenience alias is overwritten in place by every release and is not reproducible; for
anything reproducible, download the versioned `maa-llm-wiki-catalog-vX.Y.Z.zip` from the Releases
API or the release page and record its tag. You can discover the newest versioned asset via
`https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest`.

```powershell
Invoke-WebRequest https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip -OutFile maa-llm-wiki-catalog-latest.zip
uv run maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-latest.zip
```

`maa-wiki-verify-bundle` reads only the zip and works offline; `--expect-version` /
`--expect-revision` tie the downloaded bytes to the intended tag and commit. Discovery, verification
rules, and the guarantees/non-guarantees are defined by `CATALOG-CONTRACT.md`.

For stronger integrity, use the versioned asset; snapshots published by the current workflow also
provide a `SHA256SUMS` asset. Download that release's `SHA256SUMS` together with both zip assets,
then check them in the directory that contains the assets, in a shell where `sha256sum` is
available:

```bash
sha256sum -c SHA256SUMS
```

`SHA256SUMS` covers both the versioned zip and the `latest` alias (identical content); it is itself
a release asset — compare its digest against the asset digest returned by the Releases API when you
need to authenticate the checksum file. Releases published before this asset existed have no
`SHA256SUMS`. `maa-wiki-verify-bundle` also prints the whole-bundle `sha256=…`, which you can compare
with that file or the release asset digest.

The versioned zip also carries Sigstore build provenance, verifiable with the GitHub CLI (network
access and a published attestation record required):

```bash
gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki
```

The attestation only shows that the asset was produced by this repository's publish workflow at the
attested commit; it does not make the catalog content correct. Only the versioned zip carries an
attestation; the `latest` alias and `SHA256SUMS` are not attested subjects, and releases published
before provenance was introduced have no attestation.

If the machine has only Python 3 (no uv, no pip, no repository checkout): snapshots published by the
current workflow also ship `verify_bundle.py`. That asset is a byte-for-byte copy of
`src/maa_llm_wiki/verify_bundle.py` as of the release (single source of truth: change the in-repo
script), depends only on the Python 3 standard library (3.10+), and runs offline. Download the
versioned zip, `SHA256SUMS`, and the script into one directory, then run:

```bash
python verify_bundle.py --bundle maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --checksums SHA256SUMS
```

`--checksums` compares the whole-bundle digest against `SHA256SUMS`; `--expect-version` (and the
optional `--expect-revision`) binds the tag and commit. The script and `SHA256SUMS` are convenience
artifacts, not attested subjects; `SHA256SUMS` covers the two zip download names only, not the
script. Releases published before this asset existed have no `verify_bundle.py`.

If uv is available but you do not want a checkout, run the verifier directly with `uvx` (package
name `maa-llm-wiki`, built from git; uvx selects Python 3.13 from `requires-python`, and the first
run builds and caches the package):

```bash
uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-vX.Y.Z.zip
```

For suspected integrity or supply-chain problems, report privately through `SECURITY.md` — do not
open a public issue. Contribution workflow: `CONTRIBUTING.md`.

## Agent skill

`skills/maallmwiki/SKILL.md` packages the standard routing procedure — select the target
MaaFramework version, pick the domain index, and follow the pinned-commit link back to the original
source — as an installable agent skill. MaaTutorial's `maafw-*` development skills defer factual
questions to it. Install with the standard skills CLI:

```bash
npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global
```

## Automated updates

`.github/workflows/publish-catalog.yml` owns the whole cycle and runs daily. It re-indexes every
stable `vMAJOR.MINOR.PATCH` tag of MaaFramework 5.x (workflow environment variable `CATALOG_MAJOR`,
currently `5`) plus the Go and Rust bindings, records their immutable commits, and regenerates the
catalogs and schemas; it also runs
`uv run maa-wiki-extract-changes --repository tmp/MaaFramework --check` so the machine-extracted
layer matches the committed YAML. If upstream publishes a higher major, the sync fails loudly (no
more silent freeze on 5.x), and `CATALOG_MAJOR` should only be raised after human review. When a
snapshot must be published (`publish=true`), it first runs every check (`uv run maa-wiki-validate`,
`pytest`, `ruff check`, `ruff format --check`, `pyright`, `git diff --check`), then commits the
catalog, computes the snapshot version, builds and verifies the bundle, and then tags and publishes
the release in the same job (also updating `maa-llm-wiki-catalog-latest.zip`). Runs with no changes only
sync and classify: they run no checks, commit nothing, and publish nothing. Detection, commit, tag,
and release stay in one workflow because events produced with the default `GITHUB_TOKEN` do not start
another workflow; tagging in a separate workflow would leave a tag without its release. The workflow
can also be started by hand through `workflow_dispatch`.

Automation and curatorial boundary:

- The run refuses to publish when synchronization touched
  `sources/maa-framework/source-map.yaml` or `sources/maa-framework/semantic-changes.yaml`:
  synchronization never rewrites those files; maintainers or agents commit them explicitly, and
  `uv run maa-wiki-validate` checks their structure.
- Every run rebuilds the machine-extracted layer
  (`sources/maa-framework/machine-changes.yaml` and
  `generated/maa-framework/machine-changes.md`): API/schema/protocol-level changes between releases
  are extracted by sync from the upstream diff and published with the snapshot, so a version update
  needs no agent or manual step. A curated `semantic-changes.yaml` entry is optional: it adds
  interpretation ("why it matters for routing"), not detection, and is no longer a mandatory
  pre-release review queue.
- At the end of every run (`if: always()`) it still runs
  `uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework`, which compares titles and
  first-paragraph excerpts as well as the `blob` recorded in each inventory (an offline
  content-level comparison; `--repository` additionally cross-checks indexed paths with `git diff`)
  for indexed releases newer than the newest `semantic-changes.yaml` entry, and closes the tracking
  issue when the queue is empty. The report names suspected triggers, but the machine facts are
  already published automatically; each item is still not a verified change. Paths the inventory
  does not index remain invisible — see §8 of `CATALOG-CONTRACT.md` for coverage and blind spots.

The job authenticates with the repository `GITHUB_TOKEN`. If the default branch requires pull
requests, add a `CATALOG_PUSH_TOKEN` secret — a fine-grained token with contents and issues write
from an identity allowed to bypass that rule — and the workflow prefers it automatically.

## Known gaps

§8 of `CATALOG-CONTRACT.md` is the public, honest statement of coverage gaps and guarantee
boundaries: semantic-change coverage is incomplete and still being expanded (the current numbers are
whatever §8.6's re-derivation commands report), the source map covers only curated topics, binding
`declared` compatibility is textual evidence rather than runtime verification, `unknown` entries are
not guessed, GitHub Releases is the only distribution channel, and there is no SLA. §8.6 gives the
commands that re-derive its numbers; if a number disagrees with the data files, the data files win.

## Licence

- Code (Python sources, tests, workflows, and build tooling) is MIT-licensed: see `LICENSE`.
- Catalog data (metadata, inventories, generated navigation pages, schemas, and release bundles) is
  licensed under CC BY 4.0: see `LICENSE-DATA`.
- Short excerpts of MaaXYZ upstream documentation remain under their upstream licence (LGPL-3.0):
  attribution and details are in `NOTICE`.

Keep those attribution notices when redistributing catalog data or excerpts; this repository's
licences do not relicense upstream material.
