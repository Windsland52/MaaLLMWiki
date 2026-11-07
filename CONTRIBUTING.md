# Contributing to MaaLLMWiki

**中文摘要：** MaaLLMWiki 是 MaaFramework 的版本锁定源目录，由自动生成索引、机器抽取层（声明变更与上游提交索引）和一份策展的主题路由 `source-map.yaml` 组成。不要手改 `generated/`、`schemas/` 或机器抽取层；不要让同步/自动化修改 `source-map.yaml`。变更事实不手写：缺了就扩展抽取器并用上游真实写法加测试。改目录请按 [operations 的开发命令](docs/operations.md#development-commands) 运行同步并执行 `AGENTS.md` 的完整必需检查；新增主题必须引用已注册 release 与 40 位 pinned SHA。数据错误请用 "Catalog data error" issue 模板；安全问题请按 `SECURITY.md` 私下报告。

## Content classes

- **Generated (do not hand-edit):** `generated/**`, `schemas/*.schema.json`,
  `sources/maa-framework/releases.yaml`, `sources/maa-framework/inventory.yaml`,
  `sources/maa-framework/inventories/*.yaml`, `sources/maa-framework/machine-changes.yaml`,
  `sources/maa-framework/upstream-commits.yaml`, the `releases.yaml`/inventory files under
  `sources/maa-framework-{go,rs,csharp}/`, and `sources/compatibility/bindings.yaml` (all written by
  sync).
- **Curated (maintainer/agent-authored; never written by sync):**
  `sources/maa-framework/source-map.yaml`. Never let synchronization or automation modify it; the
  publish workflow fails if synchronization touches it. Maintainers or agents commit changes
  explicitly, and `uv run maa-wiki-validate` checks its structure.
- **Everything else:** `src/`, `tests/`, `.github/`, and root documentation follow normal review.

## Changing the catalog

Set up the upstream clones under `tmp/` and run the sync commands exactly as documented in
[docs/operations.md — Development commands](docs/operations.md#development-commands). Never hand-edit
the outputs. `--prune` is a dangerous manual-only escape hatch for upstream tags that were really
deleted; automation must never pass it.

Then run the required checks from [AGENTS.md](AGENTS.md), exactly:

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

## Change facts are generated

Change facts between releases are never hand-written. `machine-changes.yaml` (declared API elements
added, removed, modified or deprecated) and `upstream-commits.yaml` (the upstream commits between
releases) come from the sync and are checked by `uv run maa-wiki-extract-changes --check`. When a
fact is missing or wrong, change the parser (`src/maa_llm_wiki/c_declarations.py`,
`binding_declarations.py` or `declarations.py`) and add a test on the upstream shape it missed,
then re-run the sync.

## Adding a source-map topic

`sources/maa-framework/source-map.yaml` is the only curated catalog input; `topics.md` is generated
from it. Use the documented `id` shape; each variant's `applies_to` must be a registered release and
its `revision` must equal that release's commit. Confirm listed paths, symbols, and literal terms exist
at that commit; the validator checks release/revision consistency, not symbol existence. Never edit
the rendered pages; run `uv run maa-wiki-validate` and let sync/render regenerate them.

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
- Hand-edited `generated/` files, hand-edited JSON schemas, hand-edited
  `sources/maa-framework/machine-changes.yaml` or `upstream-commits.yaml`, hand-written change
  descriptions, or automation changes to the curated source map.
- References to a branch or tag instead of a full 40-character commit SHA.

## Licence

Code contributions are accepted under the MIT License ([LICENSE](LICENSE)); catalog data
contributions are accepted under CC BY 4.0 ([LICENSE-DATA](LICENSE-DATA)). Upstream excerpts remain
under their own licence ([NOTICE](NOTICE)). By contributing you agree to these terms.
