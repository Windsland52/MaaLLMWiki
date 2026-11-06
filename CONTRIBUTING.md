# Contributing to MaaLLMWiki

**中文摘要：** MaaLLMWiki 是 MaaFramework 的版本锁定源目录，由自动生成索引和两份人工维护元数据组成。不要手改 `generated/` 与 `schemas/`；不要让同步/自动化修改 `source-map.yaml` 或 `semantic-changes.yaml`。改目录请运行同步命令并执行 `AGENTS.md` 的完整必需检查；改代码时 PR CI 会跑同一套检查。新增语义变更或主题必须引用已注册 release 与 40 位 pinned SHA。数据错误请用 "Catalog data error" issue 模板；安全问题请按 `SECURITY.md` 私下报告。

## Who this repository is for

MaaLLMWiki is a machine-readable, versioned catalog of MaaFramework material: it stores metadata
(release facts, pinned paths, short first-paragraph excerpts, schemas) and routes a reader to the
original source at an immutable commit. It is not a tutorial, a copy of MaaFramework documentation,
or runtime evidence. Contributions are welcome in two areas: catalog data and the tooling/workflows
that produce and verify it. Read [AGENTS.md](AGENTS.md); this file explains the contributor workflow.

## Two content classes

- **Generated (do not hand-edit):** `generated/**`, `schemas/*.schema.json`,
  `sources/maa-framework/releases.yaml`, `sources/maa-framework/inventory.yaml`,
  `sources/maa-framework/inventories/*.yaml`, the `releases.yaml`/inventory files under
  `sources/maa-framework-{go,rs}/`, and `sources/compatibility/bindings.yaml` (all written by the
  sync commands below).
- **Hand-authored (reviewed by humans):** `sources/maa-framework/source-map.yaml` and
  `sources/maa-framework/semantic-changes.yaml`. Never let synchronization or automation modify
  these two; the publish workflow fails if synchronization touches them.
- **Everything else:** `src/`, `tests/`, `.github/`, and root documentation follow normal review.

## Changing the catalog

Put the upstream clones under `tmp/` as the publish workflow does (`tmp/MaaFramework`,
`tmp/maa-framework-go`, `tmp/maa-framework-rs`), then run from the repository root:

```powershell
uv sync --locked
uv run maa-wiki-sync-latest-maafw --repository tmp/MaaFramework
uv run maa-wiki-sync-maafw-history --repository tmp/MaaFramework --major 5
uv run maa-wiki-sync-bindings-history --go-repository tmp/maa-framework-go --rust-repository tmp/maa-framework-rs
```

Never hand-edit the outputs. `--prune` is a dangerous escape hatch for tags upstream really deleted;
automation must never pass it. Then run the required checks from [AGENTS.md](AGENTS.md), exactly:

```powershell
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
git diff --check
```

Commit only `sources/`, `generated/`, and `schemas/` changes produced by synchronization; the
publish workflow also fails if its own commit stages anything outside those paths.

## Changing code

- Python 3.13 (`requires-python = "==3.13.*"`), installed with `uv sync --locked`.
- CI (`.github/workflows/ci.yml`) runs the same required checks on pull requests and pushes to
  `main`, plus a schema no-diff gate and `git diff --check` on the change set.
- If you change a Pydantic model, run `uv run maa-wiki-generate-schemas` and commit the updated
  `schemas/*.schema.json`; never edit those manually.
- The verifier also ships to consumers as the release asset `verify_bundle.py`: the publish workflow
  copies `src/maa_llm_wiki/verify_bundle.py` into the release, so source and shipped copy must stay
  in sync, and the script must stay standard-library-only (no new dependencies).
- Add or update tests for behaviour changes and fill in the pull-request checklist.

## Adding a semantic-change entry or source-map topic

These are the only hand-authored catalog inputs; `topics.md` and `behaviour-changes.md` are
generated from them.

- **Semantic change** (`semantic-changes.yaml`): `topic_id` must exist in `source-map.yaml`;
  `first_version` must be registered in `sources/maa-framework/releases.yaml`; `revision` must equal
  that release's commit; every `.md`/`.json`/`.h`/`.hpp` path must already appear in
  `sources/maa-framework/inventories/*.yaml`. Describe one observable behaviour change, not a diff,
  and cite upstream evidence at the pinned SHA.
- **Source-map topic** (`source-map.yaml`): use the documented `id` shape; each variant's
  `applies_to` must be a registered release and its `revision` must equal that release's commit.
  Confirm listed paths, symbols, and literal terms exist at that commit; the validator checks
  release/revision consistency, not symbol existence.
- Never edit the rendered pages; run `uv run maa-wiki-validate` and let sync/render regenerate them.

## Reporting a data error

Use the **[Catalog data error issue form](.github/ISSUE_TEMPLATE/bug-report.yml)** and include the
affected `source_id`, catalog version or release, artifact path, pinned 40-character commit SHA,
what the upstream actually says, and a permalink at that SHA. Do not paste raw logs, dumps, or whole
documents.

For suspected integrity, supply-chain, or tampering issues, follow [SECURITY.md](SECURITY.md) and
report privately through GitHub Security Advisories. Do not open a public issue for a vulnerability;
guarantees and coverage are documented in [CATALOG-CONTRACT.md](CATALOG-CONTRACT.md).

## What will be rejected

- Unverified claims, model-generated conclusions, or references without a pinned upstream source.
- Copied upstream documentation beyond short identifying excerpts, raw logs, dumps, or screenshots.
- Project-specific documentation, Pipeline configuration, tutorials, or diagnostic methodology
  (those belong in the individual project repositories or MaaTutorial).
- Hand-edited `generated/` files, hand-edited JSON schemas, or automation changes to the two
  hand-authored catalogs.
- References to a branch or tag instead of a full 40-character commit SHA.

## Licence

Code contributions are accepted under the MIT License ([LICENSE](LICENSE)); catalog data
contributions are accepted under CC BY 4.0 ([LICENSE-DATA](LICENSE-DATA)). Upstream excerpts remain
under their own licence ([NOTICE](NOTICE)). By contributing you agree to these terms.
