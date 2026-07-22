# MaaLLMWiki

MaaLLMWiki provides machine-readable, versioned source catalogs for Maa ecosystem knowledge. It
helps a model select and find original documentation, schemas, public APIs, and source code; it
does not author or replace those sources.

## Scope

Included:

- complete version-pinned MaaFramework documentation, schema, native API, and in-tree binding API
  indexes;
- independently versioned Go and Rust binding API indexes with explicit compatibility evidence;
- topic-to-source navigation and semantic version changes;
- a disabled MaaTutorial registration until its authored guidance is ready.

Excluded:

- project-specific documentation and Pipeline configuration;
- raw user artifacts and benchmark answers;
- copied MaaFramework documentation or source trees;
- manually authored tutorials, best practices, and diagnostic methodology;
- unverified model-generated conclusions.

Authored Pipeline guidance and diagnostic methodology belong in MaaTutorial. Maa project details
must be discovered from the supplied project repository, respecting its own `AGENTS.md`.
MaaTutorial is registered as a disabled placeholder until a stable revision is selected.

## Layout

```text
sources/repositories.yaml       Registered upstream repositories
sources/maa-framework/          Release, inventory, semantic-change, and source-route metadata
sources/maa-framework-{go,rs}/  Independent binding releases and source inventories
sources/compatibility/          Evidence-backed binding compatibility metadata
generated/maa-framework/        Generated release and domain navigation indexes
generated/maa-framework-{go,rs}/ Generated binding release navigation indexes
schemas/                        Generated metadata JSON schemas
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
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The active revisions are recorded in `sources/repositories.yaml`; immutable release histories are
stored below each source directory. The current automation indexes all stable MaaFramework v5,
Go binding, and Rust binding releases. MaaTutorial is intentionally not ingested yet.

## Catalog snapshots

MDE can read this Git checkout directly during development. Tagged releases publish both a
tag-named catalog ZIP and the stable `maa-llm-wiki-catalog.zip` asset used by GitHub's
`releases/latest/download` URL. Each contains `sources/`, `generated/`, `schemas/`, and a
`catalog-manifest.json`. The manifest pins the Wiki commit and current upstream revisions and
records every bundled file's size and SHA-256 digest. Release bundles must be built from a clean
working tree; `--allow-dirty` exists only for local development and tests.

The inventory treats C/C++ headers as the native public API. Python modules under
`source/binding/Python/maa` and NodeJS declarations under `source/binding/NodeJS/src/apis/*.d.ts`
are in-tree binding APIs. C#, Go, and Rust bindings live in independent repositories and require
their own pinned inventories and MaaFramework compatibility metadata; they must not inherit the
MaaFramework repository revision. The Java binding is documented by MaaFramework as outdated and
is not a default API source.

## Automated updates

The weekly GitHub Actions workflow discovers the latest stable `vMAJOR.MINOR.PATCH` tag, records
its immutable commit, regenerates the catalogs, runs all checks, and opens a pull request. It does
not infer semantic changes: maintainers review API and behavior changes and update
`semantic-changes.yaml` when needed.
