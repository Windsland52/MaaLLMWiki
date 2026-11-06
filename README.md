# MaaLLMWiki

[English](README.en.md) | **中文**

MaaLLMWiki 为 Maa 生态知识提供机器可读、版本化的源目录。它帮助模型选择并定位原始文档、schema、公开 API 与源码；它不编写、也不替代这些源。由 publish workflow 发布的目录快照均提供可校验的 catalog bundle，消费者契约见 `CATALOG-CONTRACT.md`。

## 范围

收录：

- 完整的版本锁定 MaaFramework 文档、schema、原生 API 与树内绑定 API 索引；
- 独立版本化的 Go 与 Rust 绑定 API 索引，附明确的兼容性证据；
- 主题到源的导航与语义版本变更。

不收录：

- 项目专属文档与 Pipeline 配置；
- 原始用户产物与基准测试答案；
- MaaFramework 文档或源码树的全文拷贝（索引仅保留标题、自动摘取的首段摘要与 pinned 出处链接）；
- 人工撰写的教程、最佳实践与诊断方法论；
- 未经核实的模型生成结论。

绑定范围：只有 Go 与 Rust 绑定作为独立外部源登记（各自有锁定清单与 MaaFramework 兼容性元数据）；C# 与 Java 绑定不在本目录登记范围内——Java 被 MaaFramework 文档标注为过时，C# 没有注册的 pin 源。原生公开 API 为 C/C++ 头文件；树内 Python/NodeJS 绑定 API 随 MaaFramework 版本索引。

## 布局

```text
CATALOG-CONTRACT.md             catalog bundle 的消费者契约（manifest、发现、校验与已知局限）
sources/repositories.yaml       已注册的上游仓库
sources/maa-framework/          发布、清单、语义变更与源路由元数据
sources/maa-framework-{go,rs}/  独立绑定发布与源清单
sources/compatibility/          有证据支撑的绑定兼容性元数据
generated/maa-framework/        生成的发布、分域、主题与行为变更导航索引
generated/maa-framework-{go,rs}/ 生成的绑定发布导航索引
schemas/                        生成的元数据 JSON schema
skills/maallmwiki/              可安装的路由 agent skill
src/maa_llm_wiki/               Python 同步、打包与校验工具
tests/                          确定性仓库检查
LICENSE                         代码许可（MIT）
LICENSE-DATA                    目录数据许可（CC BY 4.0）
NOTICE                          上游文档摘录的许可与归属
SECURITY.md                     安全策略与私密报告渠道
CONTRIBUTING.md                 贡献流程、内容分类与必需检查
```

安全报告渠道见 [SECURITY.md](SECURITY.md)，贡献流程与内容分类见 [CONTRIBUTING.md](CONTRIBUTING.md)。

生成的索引逐条包含标题、首段摘要与 pinned commit 指向的原始出处；它不复制上游全文，查询时无需人工分块、embedding 或向量数据库。MaaFramework 源码保留在它自己的 Git 仓库中，按选定的不可变修订检索。

生成导航的分层结构：

```text
generated/maa-framework/index.md
  -> topics.md                     # 人工主题路由（由 source-map.yaml 渲染）
  -> behaviour-changes.md          # 人工行为变更（由 semantic-changes.yaml 渲染）
  -> <version>/index.md            # 末尾含 "Changed since <上一已索引版本>" 段落
       -> documentation/index.md -> {en-us,zh-cn,nodejs,tools}.md
       -> documentation/diagrams.md        # 自 5.10.3 起
       -> bindings/index.md -> {python,nodejs}.md
       -> native-api/index.md -> {framework,toolkit,agents}.md
       -> native-api/control-units.md      # 自 5.10.0 起
       -> schemas.md
```

`diagrams.md` 与 `control-units.md` 只存在于部分版本；其余版本目录中没有这两个文件。

每个 `<version>/index.md` 末尾都有 `Changed since` 段落：标题由 `Changed since` 与用反引号包裹的上一已索引版本组成，按清单中的 `blob` id 汇总相对上一版**新增、内容变化与删除的已索引材料**。有变化时页首先给出计数，随后按类列出条目，每类有列出上限，超出部分以 `... and K more <label>` 形式提示，完整列表用 `maa-wiki-diff`；无变化时只有一行说明。首个索引版本写的是 `Changed since the previous release`，并说明没有可比较的上一版。它回答“这一版有哪些被索引文件动了”，**不是行为变更**——行为变更看 `behaviour-changes.md` / `semantic-changes.yaml`。

`topics.md` 与 `behaviour-changes.md` 是人工维护元数据的渲染导航：前者按主题列出每个变体的适用版本（`applies_to`）、revision、pinned 文件链接、符号与字面搜索词；后者按首次发布版本分组记录跨版本行为变更并链到 pinned 出处。两者分别由 `sources/maa-framework/source-map.yaml` 与 `sources/maa-framework/semantic-changes.yaml` 渲染——YAML 仍是人工维护的权威源，页面只是让模型无需预先知道这两个路径；`index.md` 直接链接两者。

`sources/maa-framework/inventory.yaml` 仍是用于覆盖率检查的扁平权威产物清单，它不是导航接口。每个被索引 artifact 记录其内容的 git blob id（`blob`，40 位 SHA）：同一文件在不同 release 中的副本可按内容哈希区分，`maa-wiki-report-semantic-gaps` 也能只凭已提交的清单做内容级比较，无需克隆上游。

## 开发

```powershell
uv sync --locked
uv run maa-wiki-sync-latest-maafw --repository tmp/MaaFramework
uv run maa-wiki-sync-maafw-history --repository tmp/MaaFramework --major 5
uv run maa-wiki-sync-bindings-history --go-repository tmp/maa-framework-go --rust-repository tmp/maa-framework-rs
uv run maa-wiki-build-bundle --output dist/maa-llm-wiki-catalog-vX.Y.Z.zip --version vX.Y.Z
uv run maa-wiki-verify-bundle --bundle dist/maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --expect-revision <40 位 SHA>
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

`vX.Y.Z` 与 `<40 位 SHA>` 是占位符。同步命令需要先按 publish workflow 的仓库地址把上游检出到 `tmp/`（`tmp/MaaFramework`、`tmp/maa-framework-go`、`tmp/maa-framework-rs`）。

`maa-wiki-diff` 比较两个已索引 release 的清单，列出新增、删除与内容变化的 artifact。它用清单里的 `blob` 判断内容变化，不依赖上游克隆；`--source` 选择源（默认 `maafw`），`--format json` 供程序消费。版本索引里的 `Changed since` 是随包提供的摘要（每类有列出上限）；需要完整、无截断的列表时用 `maa-wiki-diff`。示例：`uv run maa-wiki-diff --from 5.14.3 --to 5.15.0`。

单版本命令只用于重新生成默认清单：`uv run maa-wiki-sync-maafw --version <版本> --repository tmp/MaaFramework` 只重建 `sources/maa-framework/inventory.yaml`，且只接受 `sources/maa-framework/releases.yaml` 中已注册的发布；它必须指向当前已索引的最新发布，否则 `maa-wiki-validate` 会失败。需要重建全部历史清单时运行 `maa-wiki-sync-maafw-history`。

历史同步（`maa-wiki-sync-maafw-history` 与 `maa-wiki-sync-bindings-history`）默认拒绝删除已注册的发布或预发布：如果本地克隆缺少已注册的 tag，命令会报错而不是静默收缩目录。`--prune` 只在上游确实删除 tag 时使用——它会删除目录数据，属于危险的逃生舱口；其 help 文本明确写着 "do NOT pass from automation"，publish workflow 也绝不传这个 flag。

当前生效修订记录在 `sources/repositories.yaml`；不可变发布历史存放在各源目录之下。现有自动化已索引 MaaFramework v5、Go 绑定与 Rust 绑定的全部稳定发布。

## 目录快照

打 tag 的发布提供带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip` 产物，内含 `sources/`、`generated/`、`schemas/` 与 `catalog-manifest.json`；发布时还会上传便利别名 `maa-llm-wiki-catalog-latest.zip`。manifest 的 `api_version` 为 `maa-llm-wiki-catalog/v1`，`wiki_revision` 记录构建提交，`working_tree_clean` 标记是否来自干净工作树，`catalog_version` 记录该 bundle 的 tag（旧 bundle 可能没有该字段），`sources` 固定 MaaFramework、Go、Rust 三源的版本与 40 位 commit，`files` 为除 manifest 自身外每个文件的 `path`、`size_bytes` 与 `sha256`。字段语义、v1 稳定性规则与完整性不变量见 `CATALOG-CONTRACT.md`，机器可读的 schema 随 bundle 提供于 `schemas/catalog-bundle-manifest.schema.json`。

快照由已提交的目录修订构建，因此其 tag 精确命名它所携带的目录；`maa-wiki-build-bundle` 拒绝脏工作树，`--allow-dirty` 仅供本地开发与测试使用。发布构建必须传 `--version vX.Y.Z`（该值写入 manifest 的 `catalog_version`），并在上传前用 `uv run maa-wiki-verify-bundle --bundle <zip> --expect-version vX.Y.Z --expect-revision <40 位 SHA>` 校验。

自 `v0.1.3` 起，快照 tag 及运送其 bundle 的 release 由下述 publish workflow 产生；更早的 `v0.1.0`、`v0.1.1` 是在 workflow 合并前发布的（当时仓库使用 `release-catalog.yml` / `sync-maafw.yml`），其 release 同样带有 bundle。若目录修订尚未有快照 tag，下一次运行会为它创建新 tag 并发布；若该修订已有 tag 但 release/zip 资产缺失，则复用既有 tag 补发、不另建 tag——两种中断都会在下一次运行时自愈。`v0.1.2` 是 2026-08-31 的 annotated tag，没有对应的 GitHub Release，因此没有 bundle 资产；其编号不再复用。

### 获取与校验

最新快照的稳定别名地址：

```text
https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip
```

该便利别名由当前 publish workflow 在发布时上传；此前的历史 release（例如 `v0.1.14`）没有该资产，历史版本请使用版本化的 `maa-llm-wiki-catalog-vX.Y.Z.zip`。

便利别名会随新版本原地覆盖，不用于复现；需要可复现时请从 Releases API 或 release 页面下载带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，并记录对应 tag。也可以从 `https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest` 发现最新带版本产物。

```powershell
Invoke-WebRequest https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip -OutFile maa-llm-wiki-catalog-latest.zip
uv run maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-latest.zip
```

`maa-wiki-verify-bundle` 只读取 zip，离线运行；传入 `--expect-version` / `--expect-revision` 可以把下载内容绑定到预期的 tag 与 commit。发现方式、校验规则与保证/非保证范围以 `CATALOG-CONTRACT.md` 为准。

完整性要求更高时，使用带版本的资产；由当前 workflow 发布的新快照还提供 `SHA256SUMS`。同时下载该 release 的 `SHA256SUMS` 与两个 zip 资产，然后在资产所在目录、用可运行 `sha256sum` 的 shell 校验：

```bash
sha256sum -c SHA256SUMS
```

`SHA256SUMS` 覆盖版本化 zip 与 `latest` 别名（两者内容相同）；它本身也是 release 资产，可对照 Releases API 返回的资产摘要核对它。更早的 release 没有 `SHA256SUMS` 资产。`maa-wiki-verify-bundle` 也会打印整包 `sha256=…`，可直接与该文件或 release 资产摘要对照。

版本化 zip 还带有 Sigstore build provenance，可用 GitHub CLI 校验（需要联网与已发布的证明记录）：

```bash
gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki
```

该证明只能说明资产由本仓库 publish workflow 在对应 commit 构建，不代表目录内容正确。只有版本化 zip 带该证明；`latest` 别名与 `SHA256SUMS` 不是被证明的资产，引入 provenance 之前的历史 release 也没有该证明。

如果本机只有 Python 3（不需要 uv、pip 或仓库检出）：由当前 workflow 发布的新快照还附带 `verify_bundle.py`。该资产是发布时从 `src/maa_llm_wiki/verify_bundle.py` 复制的逐字节副本（单一源：修改请改仓库中的脚本），只依赖 Python 3 标准库（3.10+），可离线运行。把版本化 zip、`SHA256SUMS` 与该脚本下载到同一目录后运行：

```bash
python verify_bundle.py --bundle maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --checksums SHA256SUMS
```

`--checksums` 用 `SHA256SUMS` 对照整包摘要，`--expect-version`（以及可选的 `--expect-revision`）绑定 tag 与 commit。脚本与 `SHA256SUMS` 都是便利资产，不在 attestation 覆盖范围内；`SHA256SUMS` 只覆盖两个 zip 下载名，不覆盖脚本。更早的 release 没有 `verify_bundle.py` 资产。

如果本机已有 uv 但不想检出仓库，可以用 `uvx` 直接运行校验工具（包名 `maa-llm-wiki`，从 git 构建；uvx 会按 `requires-python` 使用 Python 3.13，首次运行会构建并缓存）：

```bash
uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle maa-llm-wiki-catalog-vX.Y.Z.zip
```

怀疑完整性或供应链问题时，请按 `SECURITY.md` 私下报告，不要开公开 issue；贡献流程见 `CONTRIBUTING.md`。

## Agent skill

`skills/maallmwiki/SKILL.md` 把标准路由流程——选定目标 MaaFramework 版本、选择分域索引、沿 pinned commit 链接回溯原始出处——打包为可安装的 agent skill。MaaTutorial 的 `maafw-*` 开发 skill 把事实问题交给它处理。使用标准 skills CLI 安装：

```bash
npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global
```

## 自动更新

`.github/workflows/publish-catalog.yml` 掌管整个周期并每日运行。它重新索引 MaaFramework 5.x（workflow 环境变量 `CATALOG_MAJOR`，当前为 `5`）与 Go、Rust 绑定的全部稳定 `vMAJOR.MINOR.PATCH` tag，记录其不可变 commit，并重新生成目录与 schema；如果上游发布更高的主版本，同步会以明确错误失败（不再静默冻结在 5.x），只有在人工 review 后才应提升 `CATALOG_MAJOR`。在需要发布快照时（`publish=true`），它先运行全部检查（`uv run maa-wiki-validate`、`pytest`、`ruff check`、`ruff format --check`、`pyright`、`git diff --check`），再提交目录、计算快照版本、构建并校验 bundle，然后在同一 job 中打 tag 并发布 release（同时更新 `maa-llm-wiki-catalog-latest.zip`）。无变更的运行只同步与分类，不运行检查、不提交、不发布。检测、提交、打 tag 与发布保持在单个 workflow 内，因为默认 `GITHUB_TOKEN` 产生的事件不会触发另一个 workflow；拆开打 tag 会留下没有 release 的 tag。该 workflow 也支持 `workflow_dispatch` 手动触发。

两条规则把人工内容挡在自动化之外：

- 当同步触碰了 `sources/maa-framework/source-map.yaml` 或 `sources/maa-framework/semantic-changes.yaml` 时，运行拒绝发布；这两个文件只能经人工 review 变更。
- workflow 绝不推断语义变更。每次运行结束前（`if: always()`）会运行 `uv run maa-wiki-report-semantic-gaps --repository tmp/MaaFramework`，对晚于最新 `semantic-changes.yaml` 条目的已索引发布比较标题/首段摘要以及清单中记录的 `blob`（离线内容级比较；提供 `--repository` 时再以 git diff 交叉核验已索引路径），并在队列为空时关闭跟踪 issue。报告会列出待检查的发布与产物；每条都是疑似触发，不是已验证的变更。目录未索引的路径仍不可见——覆盖范围与盲区见 `CATALOG-CONTRACT.md` §8。

该 job 使用仓库 `GITHUB_TOKEN` 认证。若默认分支强制 pull request，请添加 `CATALOG_PUSH_TOKEN` secret——一个具 contents 与 issues 写权限、来自允许绕过该规则身份的 fine-grained token——workflow 会自动优先使用它。

## 已知局限

`CATALOG-CONTRACT.md` §8 公开记录目录的覆盖盲区与保证边界：语义变更覆盖不完整（且仍在扩充；当前数字以 §8.6 的重新核算命令为准）、source-map 只覆盖人工挑选的主题、绑定的 `declared` 兼容性只是文本证据而非运行时验证、`unknown` 条目不做猜测、GitHub Releases 是唯一分发渠道、且没有 SLA。§8.6 给出重新核算这些数字的命令；若数字与数据文件不一致，以数据文件为准。

## 许可证

- 代码（Python 源码、测试、workflow 与构建工具）以 MIT 发布：见 `LICENSE`。
- 目录数据（元数据、清单、生成的导航页面、schema 与发布 bundle）以 CC BY 4.0 发布：见 `LICENSE-DATA`。
- 目录中对 MaaXYZ 上游仓库文档的短摘录保留其上游许可证（LGPL-3.0）：归属、链接与说明见 `NOTICE`。

再分发目录数据或摘录时请保留上述归属声明；本仓库的许可不改变上游材料的许可。
