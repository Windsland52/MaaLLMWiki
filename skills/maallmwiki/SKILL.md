---
name: maallmwiki
description: 把 MaaFramework 事实问题路由到版本锁定的原始出处——字段语义与默认值、参数版本支持、API 签名、JSON schema、协议行为与版本变更。任何 MaaFW 事实核查（"这个字段什么意思/默认值多少/哪个版本引入"）或其他 MaaFW skill 指示"路由 MaaLLMWiki"时使用；回答必须引用 pinned 出处，禁止凭记忆作答。Use for any MaaFramework factual question — field semantics and defaults, version support, API signatures, schemas, protocol behavior and version changes — and whenever another MaaFW skill says to route through MaaLLMWiki. Answers must cite the version-pinned upstream source, never model memory.
---

# MaaLLMWiki 知识路由

MaaLLMWiki 是面向模型的**源目录与版本路由层**：索引上游官方文档、schema 与源码，并把每条引用锁定到不可变 commit（40 位 SHA）。它不复制全文、不替代原始内容——索引只保留标题、自动摘取的首段摘要与 pinned 出处链接；回答事实问题必须**回源**到它指向的原始出处。目录内容托管在 https://github.com/Windsland52/MaaLLMWiki ，本文所有相对路径均相对该仓库根。消费者契约、保证边界与已知局限见 `CATALOG-CONTRACT.md`；目录数据以 CC BY 4.0 发布，上游文档摘录保留 LGPL-3.0（归属见 `NOTICE`）。

本 skill 是标准路由流程；MaaTutorial 的 maafw-* 开发 skill 中"路由 MaaLLMWiki"指的就是执行本流程。
**skill 版本**：2026-11-06（要求目录结构 ≥ v0.1.21）。安装到本地的是本文件的快照；结构与流程升级后需要重装（见下方"版本纪律"）。

## 版本纪律（每次使用先做，防止拿旧目录作答）

1. **解析当前目录版本**：`curl -s https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest | jq -r .tag_name`（或 `gh release view --json tagName -q .tagName`）；GitHub 不通时用本地 `git describe --tags --abbrev=0` 并声明"版本可能落后"。
2. **引用一律钉到 tag**：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>` 或 jsDelivr `@<tag>`；**不要用 `main`**（分支会移动，第 1 步解析出的版本无法复现）。
3. **本地检出先刷新**：`git fetch --tags` 后比较本地最新 tag 与第 1 步的结果；落后就 `git checkout <tag>`，或直接下载该版本 release bundle。回答里写出所用 `catalog_version`。
4. **陈旧特征自检**：目录里没有 `generated/maa-framework/machine-changes.md`、或版本 `index.md` 末尾没有 `Changed since`、或没有 `topics.md`，说明快照早于 v0.1.21 —— 先刷新，再作答。
5. **安装副本更新**：`npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global`。本仓库 CI 会校验本文引用的目录路径存在，路径失效会直接让发布失败，因此流程与目录结构保持同步。


## 路由步骤

1. **定版本**：先按「版本纪律」解析当前目录版本（`catalog_version`）；再以被开发项目实际使用的 MaaFramework（下称 MaaFW）版本为准（运行时/依赖声明/用户陈述）。版本未知 → 用最新稳定版并**明确声明该假设**；已知版本不在目录中 → 取相邻已有版本并标注差距。可用版本清单见 `generated/maa-framework/index.md`（预发布见 `prereleases.md`；目录没有 `latest`，必须先选版本）。
2. **进目录**：`generated/maa-framework/<版本>/`（顶层 `index.md` 还链接 `topics.md`、`behaviour-changes.md` 与 `machine-changes.md`）。跨版本问题可以先看该版本 `index.md` 末尾的 `Changed since <上一版本>`：它按 `blob` 列出这一版相对上一版**已索引材料**的新增、内容变化与删除（摘要有上限；完整列表用 `maa-wiki-diff`），但它是材料移动，不是行为变更——行为变更看 `behaviour-changes.md` / `semantic-changes.yaml`。
3. **按域选索引**：
    | 要查什么 | 索引位置 |
    | --- | --- |
    | 协议/文档（3.1 Pipeline 协议、3.3 Project Interface V2、2.x 集成、4.x 构建） | `documentation/zh-cn.md` / `en-us.md`——按上游文档编号列条目，每条链到 pinned commit 的原文 |
    | Python / NodeJS 绑定 API（随框架版本） | `bindings/` |
    | Go / Rust 绑定 API（独立 pin） | `generated/maa-framework-go/`、`generated/maa-framework-rs/` 的 `<版本>/api.md` |
    | 原生 API | `native-api/` |
    | JSON Schema | `schemas.md` |
    | 主题级 / 跨版本 | `generated/maa-framework/topics.md`（每主题每变体的 `applies_to`、pinned 文件、符号、搜索词）；`generated/maa-framework/behaviour-changes.md`（按首次发布分组的行为变更） |

    注册了哪些信息源见 `sources/repositories.yaml`。
4. **回源作答**：打开条目给出的 pinned commit 链接读**原文**再回答；引用时注明上游文档 + MaaFW 版本 + commit。禁止把目录索引本身当作字段语义的出处，禁止把链接换成移动分支（main / master）。
5. **主题级定位与跨版本比较**：优先查渲染页 `generated/maa-framework/topics.md`——主题 → 按版本适用的变体 → pinned 原始路径 + 符号 + 字面搜索词，可直接跳到源码级出处；跨版本**行为变更**查 `generated/maa-framework/behaviour-changes.md`（按首次发布分组，每条链到 pinned 出处）。想知道某符号/枚举值/字段/函数是哪个版本出现的，先查 `generated/maa-framework/machine-changes.md`：它由 sync 从上游 diff 机器抽取，每条带上游证据（文本行为逐字引用，schema 值为规范化 JSON）；证据只证明该事实在版本中出现，不证明运行时语义或“变化是否重要”。`topics.md` 与 `behaviour-changes.md` 分别由 `sources/maa-framework/source-map.yaml` 与 `sources/maa-framework/semantic-changes.yaml` 渲染：YAML 是策展的权威源（改数据改 YAML，不改页面）；`machine-changes.md` 由 sync 从上游 diff 生成（源文件 `sources/maa-framework/machine-changes.yaml`），随每次 sync 自动更新；`behaviour-changes.md` 只是可选的解读层。想知道两个已索引版本之间哪些被索引产物变了，用 `uv run maa-wiki-diff --from <旧版本> --to <新版本>`（`--source` 选源，默认 `maafw`；`--format json` 供程序消费）。
6. **消费通道**（按连通性择优）：
    - 本地 Git 检出：一次克隆长期可用，弱网环境最稳；
    - raw 直链：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>`（`<tag>` 取第 1 步解析出的版本，**不要用 `main`**），如 `generated/maa-framework/<版本>/documentation/zh-cn.md`；
    - GitHub 不通畅时：jsDelivr CDN 镜像同一相对路径——`https://cdn.jsdelivr.net/gh/Windsland52/MaaLLMWiki@<tag>/<相对路径>`（`@<tag>`/`@<commit>` 为不可变缓存；`@main` 会移动且最长缓存 12h，只作应急）；
    - 其他 GitHub 加速代理同理可用；
    - 正式产物：GitHub Releases 的 catalog zip（经 Releases API 发现最新版本，一次下载本地解压；manifest 记录每个文件的 SHA-256）。release 正文由 `maa-wiki-release-notes` 从目录自身生成，含上游快照表、新上游 release、机器抽取事实、per-source 已索引材料移动计数与校验命令；先读正文可快速判断该快照包含什么、是否值得下载。最新快照另有稳定便利别名 `https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip`（由当前 publish workflow 发布时上传，历史 release 可能没有；会被覆盖，不可复现）；需要复现时用带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，下载后可运行 `uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z --expect-revision <40 位 SHA>]` 离线校验。字段语义与保证范围见 `CATALOG-CONTRACT.md`。
    - 完整性敏感时：优先带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，并按 README / `CATALOG-CONTRACT.md` 用该 release 的 `SHA256SUMS`（`sha256sum -c SHA256SUMS`）与 build provenance（`gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`）校验；只有版本化 zip 带 attestation，`latest` 别名不是被证明的资产。若本机没有工具链，release 还附带 `verify_bundle.py`（发布时从仓库脚本复制），用裸 Python 3 即可离线运行。

    不引入 chunking / embedding / vector / MCP——目录就是分层 markdown，直接读。

## 硬规则

- **两个版本维度**：MaaFW 目标版本 ≠ Wiki 自身 Git revision，引用时说清对象；引用一律 pin 到 tag/commit，不用 `main`。
- **旧快照即未验证**：安装副本或本地检出落后时不静默沿用，按「版本纪律」刷新并声明所用 `catalog_version`。
- **不可达即未验证**：目录或上游拿不到 → 回答显式标注"未验证"，不用记忆补；宁可少答。
- **内容边界**：本仓库只做路由，不收项目实践/教程/日志/诊断——开发实践在 MaaTutorial，项目事实在各项目仓库。
- **派生页不是权威源**：`topics.md` / `behaviour-changes.md` / `machine-changes.md` 都是渲染或抽取导航；引用仍要回源到 pinned commit，数据改动分别走策展 YAML 或 sync。
- **引用与许可**：上游文档摘录保留 LGPL-3.0（见 `NOTICE`），目录数据为 CC BY 4.0（见 `LICENSE-DATA`）；引用时保留上游仓库、版本与 commit，再分发时保留归属声明。
