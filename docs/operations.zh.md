# MaaLLMWiki 运维

本文面向需要了解目录如何导航、生成、发布与恢复的运维者和贡献者。消费者保证与校验规则见
[`CATALOG-CONTRACT.md`](../CATALOG-CONTRACT.md)；贡献规则与必需检查见
[`CONTRIBUTING.md`](../CONTRIBUTING.md)。

## 布局与导航

### 生成的导航树

catalog bundle 与本仓库在 `generated/` 下包含相同的生成导航：

```text
generated/maa-framework/index.md
  -> topics.md                     # curated topic routes (rendered from source-map.yaml)
  -> behaviour-changes.md          # curated behaviour changes (rendered from semantic-changes.yaml)
  -> machine-changes.md            # machine-extracted change facts (generated from upstream diffs)
-> machine-symbols.md            # 同样的记录按符号索引
  -> <version>/index.md            # ends with a "Changed since <previous indexed release>" section
       -> documentation/index.md -> {en-us,zh-cn,tools}.md
       -> documentation/diagrams.md        # since 5.10.3
       -> bindings/index.md -> {python,nodejs,readmes}.md
       -> native-api/index.md -> {framework,toolkit,agents}.md
       -> native-api/control-units.md      # since 5.10.0
       -> schemas.md
```

`documentation/diagrams.md` 与 `native-api/control-units.md` 只存在于首次包含它们的版本；其他版本目录没有这些文件。
`generated/maa-framework-{go,rs,csharp}/` 保存 Go、Rust 与 C# 绑定的同级版本/分域索引。

每条生成条目包含标题、首段摘要与指向 pinned commit 原始出处的链接；目录不复制上游全文，也不需要人工分块、
embedding 或向量数据库。MaaFramework 源码仍保留在其自己的 Git 仓库中，按选定的不可变修订检索。

MaaFramework 之外还登记了三个外部绑定源：Go、Rust 与 C#。每个源都独立 pin 自己的清单与兼容性证据，均不继承
MaaFramework 仓库修订。C# 绑定通过 NuGet 以 `Maa.Framework` 分发；其被索引的稳定 release 自 `v5.1.0` 起对齐（预发布最早从 `v5.0.0-preview.1` 起）
MaaFramework 5.x tag，且每个 release 在 pinned commit 的 `src/Directory.Packages.props` 中声明其框架版本。
三个上游绑定均为 LGPL-3.0（见 `NOTICE`）。

### 页面含义

| 页面 | 内容 |
| --- | --- |
| `generated/maa-framework/index.md` | 带 pinned revision 的 release 列表、预发布登记，以及指向下方三个顶层索引的链接。 |
| `topics.md` | 由 `sources/maa-framework/source-map.yaml` 渲染的策展主题路由：每个主题的每个变体给出适用版本（`applies_to`）、revision、pinned 文件链接、符号与字面搜索词。 |
| `behaviour-changes.md` | 由 `sources/maa-framework/semantic-changes.yaml` 渲染的策展行为历史，按首次承载该变更的 release 分组并带 pinned 链接。可选的解读层。 |
| `machine-changes.md` | 从上游 diff 机器抽取的事实：枚举值、公开函数、回调消息、JSON-schema properties/enums/defaults/required、interface 协议版本与绑定 API 名称。每条结构化记录带上游证据（文本改动为逐字 added/removed 行，schema 改动为规范化 JSON 片段）与已索引路径。某对 release 的已索引材料发生变化但未产生结构化记录时，会显式记录一条 `unclassified` 条目。 |
| `machine-symbols.md` | 同样的记录按符号重新索引：该符号首次出现的 release 与之后每次触及它的 release，并链接到对应版本页。回答“哪个版本引入 X”最快的一页。 |
绑定版本页同样有兼容性证据、注册表链接、由逐版本清单算出的 `Changed since <上一版>` 段，以及带上一版/下一版、全部版本与预发布登记的 Navigation 段。
每个版本页末尾有 Navigation 段：上一版、下一版、全部版本，以及主题/机器变更/预发布等顶层页。
| `<version>/index.md` | 单个 release 的分域索引。末尾的 `Changed since <previous indexed release>` 列出相对上一版的已索引材料新增、内容变化（按 git blob id）与删除，并给出计数、每类列出上限与 `... and K more <label>` 溢出提示。首个索引版本写 `Changed since the previous release` 并说明没有上一份清单。这是已索引**材料**移动，不是行为变更。 |

每版本索引是随包提供的廉价摘要；`maa-wiki-diff`（见下）打印完整、无截断的列表。行为变更在
`behaviour-changes.md` / `semantic-changes.yaml`；出现事实在 `machine-changes.md`。渲染页位于
`generated/maa-framework/topics.md`、`generated/maa-framework/behaviour-changes.md` 与
`generated/maa-framework/machine-changes.md`。它们都是渲染视图：`source-map.yaml` 与
`semantic-changes.yaml` 是策展权威源，而 `machine-changes.yaml` 由 sync 生成，不得手改。

### 仓库布局

| 路径 | 用途 |
| --- | --- |
| `sources/repositories.yaml` | 已注册的上游仓库及其当前 pinned revision。 |
| `sources/maa-framework/` | Release 目录、清单（`inventory.yaml` 与历史 `inventories/*.yaml`）、策展的 `source-map.yaml` 与 `semantic-changes.yaml`，以及生成的 `machine-changes.yaml`。 |
| `sources/maa-framework-{go,rs,csharp}/` | Go/Rust/C# 绑定的独立 release 目录与清单，各自独立 pin。 |
| `sources/compatibility/` | 有证据支撑的绑定兼容性元数据。 |
| `generated/` | 所有源的生成导航索引；不要手改。 |
| `schemas/` | 生成的元数据 JSON schema，包括 bundle manifest schema。 |
| `skills/maallmwiki/SKILL.md` | 可安装的路由 agent skill。 |
| `src/maa_llm_wiki/` | Python 同步、抽取、打包与校验工具。 |
| `tests/` | 确定性仓库检查。 |
| 根文档 | `CATALOG-CONTRACT.md`（消费者契约）、`CONTRIBUTING.md`、`SECURITY.md`、`LICENSE`、`LICENSE-DATA`、`NOTICE`。 |

`sources/maa-framework/inventory.yaml` 是用于覆盖率检查的扁平权威产物清单；它不是导航接口。每个被索引
artifact 记录其 git blob id（`blob`，40 位 SHA），因此同一文件跨 release 可按内容哈希区分，
`maa-wiki-report-semantic-gaps` 也能只凭已提交的清单离线比较内容。

## 快照生命周期

### 计划与手动触发

- 计划运行：每天两次，03:17 与 15:17 UTC（`cron: "17 3,15 * * *"`，约 11:17 与 23:17 UTC+8）。
  计划运行是 best-effort：GitHub 可能延迟或跳过。
- 手动运行：`workflow_dispatch` 接受布尔 `force` 输入（默认 `false`）。`force=true` 在目录数据未变时
  发布一次仅打包型快照；如果工作树已变化则会被拒绝，因为该路径必须正常提交并校验目录更新。
- `concurrency.group` 为 `publish-catalog`，`cancel-in-progress: false`；job 超时为 30 分钟。

### 状态分类分支

检出目录分支与四个上游克隆后，每次运行都会重新索引 MaaFramework 5.x 的全部稳定 tag（`CATALOG_MAJOR`，当前
为 `5`）以及 Go、Rust 与 C# 绑定的全部稳定 tag，重新生成 schema，运行机器目录门禁，然后分类目录状态：

1. **工作树有变化**（`git status --porcelain` 非空）：`changed=true`、`publish=true`。该分支下
   `force=true` 是错误。
2. **干净树，尚无快照 tag**：`publish=true`；这是首个快照。
3. **干净树，目录路径自最新快照 tag 以来移动**：`publish=true`；需要新快照。
4. **干净树，HEAD 正好是最新 tag 但其 release/zip 缺失**：`publish=true`；运行会重发该修订。
5. **干净树，`force=true`**：`publish=true`；即使目录数据未变也发布仅打包型快照。
6. **其他情况**：`publish=false`；运行只同步与分类（不检查、不提交、不发布）。

对于发布运行，必需检查在提交任何内容之前执行：
`uv run maa-wiki-validate`、`uv run pytest`、`uv run ruff check .`、
`uv run ruff format --check .`、`uv run pyright` 与 `git diff --check`。

### 提交与版本计算

提交步骤先 stage 全部内容，然后拒绝任何落在 `sources/`、`generated/`、`schemas/` 之外的 staged 路径，
运行 `git diff --cached --check`，用固定的目录更新消息提交，rebase 到远端默认分支
（`git pull --rebase --autostash`），然后 push。

快照版本从 tag 推导，而不是从上游版本推导：如果 HEAD 正好有 tag，运行会复用该 tag（中断发布恢复）；
否则取最新的 `vX.Y.Z` tag，递增 patch 组件，并跳过已存在的版本。没有上一 tag 时首个快照为 `v0.1.0`。

### 为什么用一个 workflow

检测、提交、打 tag 与发布保持在一个 job 内，因为默认 `GITHUB_TOKEN` 产生的事件不会启动另一个 workflow。
把打 tag 拆成由 push 触发的 workflow 会静默留下没有 release 的 tag。

## 发布装配

顺序固定：构建 bundle → 校验 bundle → 复制 `latest` 别名 → 写 checksums → 运行独立校验器 → 渲染 release
notes → attest provenance → push tag → 发布 release。release 正文在 attest/tag/release 之前渲染，因此渲染
失败不会留下没有预期正文的 tag。

### 资产

| 资产 | 含义 |
| --- | --- |
| `maa-llm-wiki-catalog-vX.Y.Z.zip` | 该 tag 的不可变版本化 bundle；唯一被 attest 的主体。 |
| `maa-llm-wiki-catalog-latest.zip` | 最新 bundle 的逐字节便利副本；每个 release 覆盖。 |
| `SHA256SUMS` | 覆盖两个 zip 下载名的校验和。 |
| `verify_bundle.py` | `src/maa_llm_wiki/verify_bundle.py` 的逐字节副本；零依赖校验器。 |

版本化 zip 包含目录数据（`sources/`、`generated/`、`schemas/`）、manifest（`catalog-manifest.json`）以及说明与授权它的随包文档（README、契约、贡献/安全说明、运维指南、`LICENSE`、`LICENSE-DATA`、`NOTICE`）。manifest 的
`api_version` 为 `maa-llm-wiki-catalog/v1`；`wiki_revision` 记录构建提交；`working_tree_clean` 记录
构建是否来自干净树；`catalog_version` 记录 bundle 的 tag（旧 bundle 可能没有该字段）；`sources` 固定
MaaFramework、Go、Rust 与 C# 的版本与 40 位 commit；`files` 为除 manifest 自身外每个文件的 `path`、
`size_bytes` 与 `sha256`。字段语义、v1 稳定性规则与完整性不变量见 `CATALOG-CONTRACT.md`；机器可读的
schema 随 bundle 提供于 `schemas/catalog-bundle-manifest.schema.json`。

构建拒绝脏工作树。`--allow-dirty` 仅用于本地开发与测试。发布构建传 `--version vX.Y.Z`（该值写入
manifest 的 `catalog_version`），并在上传前用
`uv run maa-wiki-verify-bundle --bundle <zip> --expect-version vX.Y.Z --expect-revision <40-char SHA>`
校验结果。快照由已提交的目录修订构建，因此其 tag 精确命名它所携带的目录。

`latest` 别名由当前 workflow 上传：历史 release 可能没有它，且它会被原地覆盖，因此不可复现。最新版本化
资产的发现通过 Releases API（`https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest`）。

在当前目录已有下载资产时，最小消费者校验如下：

```powershell
Invoke-WebRequest https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip -OutFile maa-llm-wiki-catalog-latest.zip
uv run maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-latest.zip
```

### 校验和与来源证明

`SHA256SUMS` 在 `dist/` 内生成，因此在消费者下载资产所在目录可直接运行 `sha256sum -c SHA256SUMS`；
workflow 也会用两个 zip 核对这个文件。它是 release 资产但不被 attest，也不覆盖 `verify_bundle.py`；
需要认证校验和文件时，可将其摘要与 Releases API 返回的资产摘要对照。早于该资产的 release 没有
`SHA256SUMS`。

版本化 zip 带有一个由 publish workflow 记录的 keyless Sigstore build-provenance attestation（短时 OIDC
token、`actions/attest-build-provenance`）。用
`gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki` 校验；需要联网与
已发布的 attestation 记录。它证明哪个 workflow 与 commit 产出了该资产，不证明目录内容正确。`latest` 别名、
`SHA256SUMS` 与 `verify_bundle.py` 不在 attestation 范围内，引入 provenance 之前的 release 也没有
attestation。

### 校验工具

- `uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z] [--expect-revision SHA]`
  只读取 zip，离线运行，并打印整包 `sha256=…`。workflow 会对刚构建的 bundle 运行同一校验。
- `verify_bundle.py` 仅用 Python 3（3.10+，标准库）执行相同的 manifest/zip/checksum/expectation 检查，
  完全离线。它接受 `--bundle`、`--expect-version`、`--expect-revision` 与 `--checksums`；其 release
  资产是仓库内脚本的副本，release 中的副本是发布时的校验器。
- 有 uv 但没有检出时，可用
  `uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle <zip>`
  从 git 构建包（按 `requires-python` 选择 Python 3.13）并运行同一工具。

### 发布正文

正文由 `maa-wiki-release-notes` 从目录自身生成，因此精确反映快照内容。它包含：

- `Upstream snapshot` — 各源版本与 pinned revision。
- `New upstream releases since <previous tag>` — 或说明没有新上游 release。
- `Machine-extracted changes` — 新 release 的抽取事实，按 kind 计数。
- `Curated behaviour changes` — 仅当存在新的策展条目时出现，可省略。
- `Indexed material moved` — 各源 added/removed/content changed 计数。
- `Catalog files changed` — `generated/`、`sources/` 与 `schemas/` 下 added/removed/changed 计数与示例，
  因此仅打包型快照也能被量化。
- `Verification` — checksum、attestation 与独立校验器命令。
- `Assets` — 传入 `--bundle` 时给出 zip 的 sha256、大小与文件数，以及其余资产。
- `Documentation` — contract、§8 已知局限、机器/行为页面与完整 changelog 链接。

完整 changelog 链接保留在正文末尾。

### 历史与被中断的发布

自 `v0.1.3` 起，快照 tag 及运送其 bundle 的 release 由本 workflow 产生。`v0.1.0` 与 `v0.1.1` 在合并前
发布（当时仓库使用 `release-catalog.yml` / `sync-maafw.yml`），同样带有 bundle。`v0.1.2` 是 2026-08-31
的 annotated tag，没有 GitHub Release，因此没有 bundle 资产；其编号不再复用。

如果目录修订没有快照 tag，下一次运行会创建新 tag 与 release。如果修订已有 tag 但 release 或 zip 资产缺失，
运行会复用既有 tag 而不再创建另一个。两种中断都会在下一次运行时自愈。

## 失败处理

### 护栏失败

大多数发布失败是要求做决策的故意护栏，而不是代码故障：

| 护栏 / 失败步骤 | 含义 | 处置 |
| --- | --- | --- |
| `Sync Maa source indexes` | 上游出现高于 `CATALOG_MAJOR` 的 MaaFramework 主版本，或上游 tag 列表缩水。 | review 后在 workflow 中提升 `CATALOG_MAJOR`；确认被删除的 tag 确实消失，然后才手动使用显式 `--prune`。workflow 绝不传 `--prune`。 |
| `Check machine change catalog is current` | 已提交的 `machine-changes.yaml` 不再匹配对上游 diff 的新抽取。 | 重新运行同步/抽取并提交再生成的目录；不要手改。 |
| `Guard hand-authored catalogs` | 同步写入了 `source-map.yaml` 或 `semantic-changes.yaml`。 | 视为同步/抽取缺陷；策展文件由维护者或 agent 显式提交。 |
| `Validate generated source indexes` | 某项必需检查失败。 | 步骤日志会点名失败的检查；修代码或数据后重跑。 |
| `Classify catalog state` | 工作树已变化时请求了 `force=true`。 | 去掉 `force` 重跑，让目录更新正常提交与校验。 |
| `Push snapshot tag` | 计算出的 tag 已存在于另一个 commit。 | 不会自动移动任何东西；人工解决 tag/release 不匹配。 |

### `pipeline-failure` issue

任何步骤失败时（`if: failure()`），workflow 会打开或更新一个带 `pipeline-failure` label 的 issue。
正文点名失败步骤、链接运行与 commit，并重复上面的护栏处置说明。重复报告按正文 hash 去重：只有内容变化时
才编辑 issue。issue 步骤是 `continue-on-error`，不会掩盖原始失败。下一次成功运行会关闭该 issue
（`if: success()`）。

### Semantic-review issue

每次运行结束时（`if: always()`），除非 MaaFramework 克隆不可用，workflow 会运行
`uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework`。它对晚于最新 `semantic-changes.yaml`
条目的已索引 release，比较标题、首段摘要以及每份清单中记录的 `blob`。若队列非空，会打开或更新一个带
`semantic-review` label 的 issue；只有 hash 变化时才更新正文，队列为空时关闭 issue。机器抽取事实已经自动
发布，因此策展的 `semantic-changes.yaml` 条目是可选的解读，不是必经的 review 步骤。报告列出疑似触发，
不是已验证的变更；已索引集合之外的路径仍然不可见（见 `CATALOG-CONTRACT.md` §8）。

### Tag/release 对账

最后一个 `if: always()`、`continue-on-error` 步骤列出快照 tag 与 GitHub Releases；当某个快照 tag 没有
release，或某个 release 缺少其 catalog 资产时发出警告（并写入 job summary）。它从不修改任何东西。
`v0.1.2` 是已记录的 legacy 例外：它早于该 pipeline，故意没有 release。

### 认证

job 使用仓库 `GITHUB_TOKEN` 认证。它声明 `contents: write`、`issues: write`、`id-token: write` 与
`attestations: write`（provenance attestation 需要 OIDC token）。若默认分支要求 pull request，请添加
`CATALOG_PUSH_TOKEN` secret——一个具 contents 与 issues 写权限、来自允许绕过该规则身份的 fine-grained
token——workflow 会自动优先使用它。

## 开发命令

### 克隆假设

按 publish workflow 的方式把上游克隆放在 `tmp/` 下：
`tmp/MaaFramework`、`tmp/maa-framework-go`、`tmp/maa-framework-rs` 与
`tmp/MaaFramework.Binding.CSharp`。使用 `.github/workflows/publish-catalog.yml` 中的仓库 URL。
Python 通过 `requires-python` 固定为 3.13。

### 命令

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

`vX.Y.Z` 与 `<40-char SHA>` 是占位符。

- `maa-wiki-diff` 比较两个已索引 release 的清单，用记录的 `blob` id 列出新增、删除与内容变化的 artifact，
  不需要上游克隆。`--source` 选择源（默认 `maafw`）；`--format json` 供工具消费。
- `maa-wiki-release-notes` 渲染上文描述的 release 正文。首个快照省略 `--previous`。
- 单版本命令只重新生成默认清单：
  `uv run maa-wiki-sync-maafw --version <version> --repository tmp/MaaFramework` 只重建
  `sources/maa-framework/inventory.yaml`，只接受已在 `sources/maa-framework/releases.yaml` 注册的发布，
  且必须指向当前已索引的最新发布，否则 `maa-wiki-validate` 会失败。
- 历史同步默认拒绝删除已注册的发布或预发布。`--prune` 是危险的、仅限手动的逃生舱口，用于上游确实删除 tag
  的情况；其 help 文本写着 "do NOT pass from automation"，publish workflow 绝不传它。

### 必需检查

来自 `AGENTS.md`，完全一致：

```powershell
uv run maa-wiki-validate
uv run maa-wiki-generate-schemas
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
git diff --check
```

### 仓库状态

当前生效修订记录在 `sources/repositories.yaml`；不可变发布历史存放在各源目录之下。现有自动化已索引
MaaFramework v5、Go、Rust 与 C# 绑定的全部稳定发布，且 `machine-changes.yaml` 随每次 sync 重建。
