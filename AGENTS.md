# Repository Guidelines

MaaLLMWiki is a machine-readable source catalog and version-routing layer for language models. It
is not a tutorial, a copy of MaaFramework documentation, a project-specific knowledge base, or
runtime evidence.

## Content boundaries

- Keep project-specific documentation in each Maa project repository. Do not add M9A, MaaEnd,
  MaaNTE, GUI, or custom-agent layouts here.
- Human-authored guidance, best practices, and diagnostic methodology belong in MaaTutorial.
- Keep MaaFramework documentation, schemas, APIs, and source in MaaFramework; catalog immutable
  references here instead of copying their content.
- Separate symptoms, directly observed mechanisms, and suspected triggers.
- Do not add raw logs, issue archives, screenshots, dumps, benchmark answers, or model-generated
  claims without original-source verification.
- Diagnostic conclusions must return to original documents or source before citing a fact.

## Version policy

- The Wiki Git revision and the target MaaFramework version are separate dimensions.
- Generate a complete official-material inventory for each registered baseline release.
- Add semantic-change entries only when relevant behavior changes; a new release alone is not
  enough.
- Pin every source reference to a full 40-character commit SHA; never cite a moving branch.

## Implementation

- Python 3.13 owns metadata contracts and validation.
- YAML catalogs and generated Markdown indexes are the content formats. Do not introduce manual
  chunks, embeddings, vector databases, model calls, or MCP.
- `sources/repositories.yaml` registers information sources. `sources/maa-framework/source-map.yaml`
  maps Wiki topics to original paths, symbols, and literal search terms.
- `sources/maa-framework/inventory.yaml` and `generated/maa-framework/*.md` are generated from a
  pinned MaaFramework Git tree; do not edit them manually.
- Historical per-version manifests live under `sources/maa-framework/inventories/`; the default
  `inventory.yaml` is the latest indexed release.
- Keep the inventory flat for deterministic coverage, but generate navigation as
  release -> domain -> language or API-module indexes. Do not expose one long artifact list as the
  primary index.
- In-tree Python and NodeJS binding APIs follow the MaaFramework revision. External C#, Go, Rust,
  and Java bindings require independently pinned source entries and compatibility metadata.
- `sources/maa-framework/semantic-changes.yaml` records behavior changes relevant to source
  selection; each entry must match a registered release commit.
- MaaTutorial is currently a disabled placeholder. Do not ingest its working tree until a stable
  revision and authored Pipeline guidance are supplied.
- `.github/workflows/publish-catalog.yml` owns detection, commit, tag, and release in one job. Do not
  split tagging or releasing into a workflow that another workflow's push is expected to trigger:
  events produced with the default `GITHUB_TOKEN` do not start a workflow, which leaves a tag
  without its release.
- Synchronization must never write `sources/maa-framework/source-map.yaml` or
  `sources/maa-framework/semantic-changes.yaml`; the publish workflow fails when it does.

## Required checks

```powershell
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
git diff --check
```

Generated files under `schemas/*.schema.json` come from the Pydantic models. Do not edit them
manually.
