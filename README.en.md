# MaaLLMWiki

**English** | [中文](README.md)

MaaLLMWiki provides machine-readable, versioned source catalogs for Maa ecosystem knowledge. It
helps a model select and find original documentation, schemas, public APIs, and source code; it
does not author or replace those sources.

## Scope

Included:

- complete version-pinned MaaFramework documentation, schema, native API, and in-tree binding API
  indexes;
- independently versioned Go and Rust binding API indexes with explicit compatibility evidence;
- topic-to-source navigation and semantic version changes.

Excluded:

- project-specific documentation and Pipeline configuration;
- raw user artifacts and benchmark answers;
- copied MaaFramework documentation or source trees;
- manually authored tutorials, best practices, and diagnostic methodology;
- unverified model-generated conclusions.

Authored Pipeline guidance and diagnostic methodology belong in MaaTutorial. Maa project details
must be discovered from the supplied project repository, respecting its own `AGENTS.md`.

## Layout

```text
sources/repositories.yaml       Registered upstream repositories
sources/maa-framework/          Release, inventory, semantic-change, and source-route metadata
sources/maa-framework-{go,rs}/  Independent binding releases and source inventories
sources/compatibility/          Evidence-backed binding compatibility metadata
generated/maa-framework/        Generated release and domain navigation indexes
generated/maa-framework-{go,rs}/ Generated binding release navigation indexes
schemas/                        Generated metadata JSON schemas
skills/maallmwiki/              Installable agent skill for the routing procedure
src/maa_llm_wiki/               Python synchronization and validation tooling
tests/                          Deterministic repository checks
```

The generated index contains no copied upstream content and requires no manual chunking, embedding,
or vector database. MaaFramework source remains in its own Git repository and is searched at the
revision selected by the catalog.

Generated navigation is layered as follows:

```text
generated/maa-framework/index.md
  -> <version>/index.md
       -> documentation/{en-us,zh-cn,nodejs,tools}.md
       -> bindings/{python,nodejs}.md
       -> native-api/{framework,control-units,toolkit,agents}.md
       -> schemas.md
       -> documentation/diagrams.md
```

`sources/maa-framework/inventory.yaml` remains the flat canonical artifact manifest used for
coverage checks. It is not the navigation interface.

## Development

```powershell
uv sync
uv run maa-wiki-sync-maafw --repository ../MaaFramework --version 5.11.2
uv run maa-wiki-sync-latest-maafw --repository ../MaaFramework
uv run maa-wiki-sync-maafw-history --repository ../MaaFramework --major 5
uv run maa-wiki-sync-bindings-history --go-repository tmp/maa-framework-go --rust-repository ../maa-framework-rs
uv run maa-wiki-build-bundle --output dist/maa-llm-wiki-catalog.zip
uv run maa-wiki-report-semantic-gaps
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The active revisions are recorded in `sources/repositories.yaml`; immutable release histories are
stored below each source directory. The current automation indexes all stable MaaFramework v5,
Go binding, and Rust binding releases.

## Catalog snapshots

MaaEvidenceKit (MEK) can read this Git checkout directly during development. Tagged releases publish a versioned
`maa-llm-wiki-catalog-vX.Y.Z.zip` asset containing `sources/`, `generated/`, `schemas/`, and
a `catalog-manifest.json`. Consumers discover the latest versioned asset through the GitHub
Releases API. The manifest pins the Wiki commit and current upstream revisions and records every
bundled file's size and SHA-256 digest. A snapshot is built from the committed catalog revision, so
its tag names exactly the catalog it carries; `maa-wiki-build-bundle` refuses a dirty working tree,
and `--allow-dirty` exists only for local development and tests.

Snapshot tags, and the release that ships their bundle, are produced by the publish workflow
described below. A run that finds catalog data on the default branch without a snapshot tag
publishes that revision instead of creating a second tag, so an interrupted publish heals on the
next run. `v0.1.2` was tagged before the workflow was consolidated and carries no bundle asset; its
number is not reused.

The inventory treats C/C++ headers as the native public API. Python modules under
`source/binding/Python/maa` and NodeJS declarations under `source/binding/NodeJS/src/apis/*.d.ts`
are in-tree binding APIs. C#, Go, and Rust bindings live in independent repositories and require
their own pinned inventories and MaaFramework compatibility metadata; they must not inherit the
MaaFramework repository revision. The Java binding is documented by MaaFramework as outdated and
is not a default API source.

## Agent skill

`skills/maallmwiki/SKILL.md` packages the standard routing procedure — select the target
MaaFramework version, pick the domain index, and follow the pinned-commit link back to the original
source — as an installable agent skill. MaaTutorial's `maafw-*` development skills defer factual
questions to it. Install with the standard skills CLI:

```bash
npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global
```

## Automated updates

`.github/workflows/publish-catalog.yml` owns the whole cycle and runs daily. It discovers the latest
stable `vMAJOR.MINOR.PATCH` tags of MaaFramework, the Go binding, and the Rust binding, records their
immutable commits, regenerates the catalogs, runs every check, commits the result to the default
branch, and publishes the snapshot release from the same job. Detection, commit, tag, and release
stay in one workflow because events produced with the default `GITHUB_TOKEN` do not start another
workflow; tagging in a separate workflow would leave a tag without its release. The workflow can also
be started by hand through `workflow_dispatch`.

Two rules keep human-authored content out of the automation:

- The run refuses to publish when synchronization touched
  `sources/maa-framework/source-map.yaml` or `sources/maa-framework/semantic-changes.yaml`; those
  files change only through review.
- The workflow never infers semantic changes. When a snapshot lands with releases whose recorded
  official material moved after the newest `semantic-changes.yaml` entry, it opens or updates a
  semantic-review issue naming the releases and artifacts to inspect
  (`uv run maa-wiki-report-semantic-gaps`). Each item is a suspected trigger, not a verified change.

The job authenticates with the repository `GITHUB_TOKEN`. If the default branch requires pull
requests, add a `CATALOG_PUSH_TOKEN` secret — a fine-grained token with contents and issues write
from an identity allowed to bypass that rule — and the workflow prefers it automatically.
