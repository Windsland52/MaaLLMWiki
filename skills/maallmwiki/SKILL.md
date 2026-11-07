---
name: maallmwiki
description: 把 MaaFramework 事实问题路由到版本锁定的原始出处——字段语义与默认值、参数版本支持、API 签名、JSON schema、协议行为与版本变更。任何 MaaFW 事实核查（"这个字段什么意思/默认值多少/哪个版本引入"）或其他 MaaFW skill 指示"路由 MaaLLMWiki"时使用；回答必须引用 pinned 出处，禁止凭记忆作答。Use for any MaaFramework factual question — field semantics and defaults, version support, API signatures, schemas, protocol behavior and version changes — and whenever another MaaFW skill says to route through MaaLLMWiki. Answers must cite the version-pinned upstream source, never model memory.
---

# MaaLLMWiki 知识路由

MaaLLMWiki 是面向模型的**源目录与版本路由层**：索引上游官方文档、schema 与源码，并把每条引用锁定到不可变 commit（40 位 SHA）。它不复制全文、不替代原始内容——索引只保留标题、自动摘取的首段摘要与 pinned 出处链接；回答事实问题必须**回源**到它指向的原始出处。目录内容托管在 https://github.com/Windsland52/MaaLLMWiki ，本文所有相对路径均相对该仓库根。消费者契约、保证边界与已知局限见 `CATALOG-CONTRACT.md`；目录数据以 CC BY 4.0 发布，上游文档摘录保留 LGPL-3.0（归属见 `NOTICE`）。

本 skill 是标准路由流程；MaaTutorial 的 maafw-* 开发 skill 中"路由 MaaLLMWiki"指的就是执行本流程。
**skill 版本**：2026-11-07b（要求目录结构 ≥ v0.1.36）。安装到本地的是本文件的快照；结构与流程升级后需要重装（见下方"版本纪律"）。

## 版本纪律（每次使用先做，防止拿旧目录作答）

1. **解析当前目录版本**：`curl -s https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest | jq -r .tag_name`（或 `gh release view --json tagName -q .tagName`）；GitHub 不通时用本地 `git describe --tags --abbrev=0` 并声明"版本可能落后"。
2. **引用一律钉到 tag**：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>` 或 jsDelivr `@<tag>`；**不要用 `main`**（分支会移动，第 1 步解析出的版本无法复现）。
3. **本地检出先刷新**：`git fetch --tags` 后比较本地最新 tag 与第 1 步的结果；落后就 `git checkout <tag>`，或直接下载该版本 release bundle。回答里写出所用 `catalog_version`。
4. **陈旧特征自检**：目录里没有 `generated/maa-framework/upstream-commits.md`、或还有 `behaviour-changes.md`，说明快照早于 v0.1.36（机器层还没有 C API 函数、结构体字段和常量）—— 先刷新，再作答。
5. **安装副本更新**：`npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global`。本仓库 CI 会校验本文引用的目录路径存在，路径失效会直接让发布失败，因此流程与目录结构保持同步。


## 路由步骤

1. **定版本**：先按「版本纪律」解析当前目录版本（`catalog_version`）；再以被开发项目实际使用的 MaaFramework（下称 MaaFW）版本为准（运行时/依赖声明/用户陈述）。版本未知 → 用最新稳定版并**明确声明该假设**；已知版本不在目录中 → 取相邻已有版本并标注差距。可用版本清单见 `generated/maa-framework/index.md`（预发布见 `prereleases.md`；目录没有 `latest`，必须先选版本）。
2. **进目录**：`generated/maa-framework/<版本>/`（版本页末尾的 Navigation 段有上一版/下一版与顶层页链接）。跨版本问题可以先看该版本 `index.md` 末尾的 `Changed since <上一版本>`：它按 `blob` 列出这一版相对上一版**已索引文件**的新增、内容变化与删除（摘要有上限；完整列表用 `maa-wiki-diff`）。具体哪些声明变了看 `machine-changes.md`，行为变更看 `upstream-commits.md`（见第 5 步）。
3. **按域选索引**：
    | 要查什么 | 索引位置 |
    | --- | --- |
    | 协议/文档（3.1 Pipeline 协议、3.3 Project Interface V2、2.x 集成、4.x 构建） | `documentation/zh-cn.md` / `en-us.md`——按上游文档编号列条目，每条链到 pinned commit 的原文 |
    | Python / NodeJS 绑定 API（随框架版本） | `bindings/` |
    | Go / Rust 绑定 API（独立 pin） | `generated/maa-framework-go/`、`generated/maa-framework-rs/` 的 `<版本>/api.md` |
    | 原生 API | `native-api/` |
    | JSON Schema | `schemas.md` |
    | 主题级 / 跨版本 | `generated/maa-framework/topics.md`（每主题每变体的 `applies_to`、pinned 文件、符号、搜索词）；`machine-symbols.md` / `machine-changes.md` / `upstream-commits.md`（见第 5 步） |

    注册了哪些信息源见 `sources/repositories.yaml`。
4. **回源作答**：打开条目给出的 pinned commit 链接读**原文**再回答；引用时注明上游文档 + MaaFW 版本 + commit。禁止把目录索引本身当作字段语义的出处，禁止把链接换成移动分支（main / master）。
5. **主题级定位与跨版本比较**：
    - **主题定位**：`generated/maa-framework/topics.md`——主题 → 按版本适用的变体 → pinned 原始路径 + 符号 + 字面搜索词，可直接跳到源码级出处（由 `sources/maa-framework/source-map.yaml` 渲染，改数据改 YAML）。
    - **某符号/字段/枚举/常量/函数哪个版本引入**：先查 `generated/maa-framework/machine-symbols.md`。Introduced 列是“上一已索引版本没有、这一版有”的版本；`≤ 5.0.0` 表示首个已索引版本就已存在；从未变过的元素不在表里（去目标版本的 pinned 文件里确认它存在即可）。符号写法：C 用裸名（`MaaLinuxControllerCreate`、`MaaCustomControllerCallbacks.shell`、`ControlUnitAPI::connect`），Python 用 `maa.controller:Controller.post_shell`，NodeJS 用 `maa.Controller.post_click`，schema 用点分路径（`$defs.Shell.cmd`）。
    - **某版本具体变了什么**：`generated/maa-framework/machine-changes.md`，按版本、文件列出声明元素的 added / removed / modified（附旧文本）/ deprecated，每条带上游原文；源文件 `sources/maa-framework/machine-changes.yaml` 由 sync 生成。
    - **行为变更（声明没变、行为变了）**：`generated/maa-framework/upstream-commits.md`，按版本列出两版之间的上游提交（标题、PR、改动路径）；按路径或关键词找到提交后，打开该提交的 diff 读原文。提交标题只是作者意图，不是已验证的行为。
    - **机器层的边界**：只比较声明（头文件、树内 Python/NodeJS 绑定、JSON schema、3.1/3.3 协议版本表），不含运行时语义；文档正文没有解析器（变化只在版本页 `Changed since` 里）；`unclassified` 表示头文件/绑定/schema 变了但声明没变（注释、格式或解析器不读的写法），或文件无法解析。结论仍要回源到 pinned 文件。
6. **消费通道**（按连通性择优）：
    - 本地 Git 检出：一次克隆长期可用，弱网环境最稳；
    - raw 直链：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>`（`<tag>` 取第 1 步解析出的版本，**不要用 `main`**），如 `generated/maa-framework/<版本>/documentation/zh-cn.md`；
    - GitHub 不通畅时：jsDelivr CDN 镜像同一相对路径——`https://cdn.jsdelivr.net/gh/Windsland52/MaaLLMWiki@<tag>/<相对路径>`（`@<tag>`/`@<commit>` 为不可变缓存；`@main` 会移动且最长缓存 12h，只作应急）；
    - 其他 GitHub 加速代理同理可用；
    - 正式产物：GitHub Releases 的 catalog zip（经 Releases API 发现最新版本，一次下载本地解压；manifest 记录每个文件的 SHA-256）。release 正文由 `maa-wiki-release-notes` 从目录自身生成，含上游快照表、新上游 release、机器抽取事实、per-source 已索引材料移动计数与校验命令；先读正文可快速判断该快照包含什么、是否值得下载。最新快照另有稳定便利别名 `https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip`（由当前 publish workflow 发布时上传，历史 release 可能没有；会被覆盖，不可复现）；需要复现时用带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，下载后可运行 `uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z --expect-revision <40 位 SHA>]` 离线校验。字段语义与保证范围见 `CATALOG-CONTRACT.md`。
    - 完整性敏感时：优先带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，并按 README / `CATALOG-CONTRACT.md` 用该 release 的 `SHA256SUMS`（`sha256sum -c SHA256SUMS`）与 build provenance（`gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`）校验；只有版本化 zip 带 attestation，`latest` 别名不是被证明的资产。若本机没有工具链，release 还附带 `verify_bundle.py`（发布时从仓库脚本复制），用裸 Python 3 即可离线运行。

    不引入 chunking / embedding / vector / MCP——目录就是分层 markdown，直接读。

## 跨版本材料差异（maa-wiki-diff）

`Changed since` 只是页面摘要（有截断）。要完整、可复现的差异列表，在本地检出后运行：

```bash
# MaaFramework 本体：5.14.2 与 5.15.0 之间哪些被索引文件新增/改内容/删除
uv run maa-wiki-diff --from 5.14.2 --to 5.15.0

# 绑定源同理（--source 取 repositories.yaml 里的 id；只能比较已登记版本，预发布没有 inventory）
uv run maa-wiki-diff --from 3.5.1 --to 4.0.0 --source maa-framework-go

# 程序消费
uv run maa-wiki-diff --from 5.14.2 --to 5.15.0 --format json
```

它比较的是**已索引文件**（按 git blob），不是声明或行为；声明变化看 `machine-changes.md`，行为变更看 `upstream-commits.md`。没有本地检出时退回 `Changed since` 摘要，并说明列表可能被截断。

## 预发布

预发布只登记 tag 与 commit（`<源>/prereleases.md`），**不生成 inventory、没有版本目录**，也不能作为 `maa-wiki-diff` 的 `--from`/`--to`；需要预发布版本的事实，用该表里的 pinned commit 直接回源。

## 硬规则

- **两个版本维度**：MaaFW 目标版本 ≠ Wiki 自身 Git revision，引用时说清对象；引用一律 pin 到 tag/commit，不用 `main`。
- **旧快照即未验证**：安装副本或本地检出落后时不静默沿用，按「版本纪律」刷新并声明所用 `catalog_version`。
- **不可达即未验证**：目录或上游拿不到 → 回答显式标注"未验证"，不用记忆补；宁可少答。
- **内容边界**：本仓库只做路由，不收项目实践/教程/日志/诊断——开发实践在 MaaTutorial，项目事实在各项目仓库。
- **机器层没有记录 ≠ 行为没变**：它只看声明；行为问题要查 `upstream-commits.md` 并读提交 diff（边界见路由步骤第 5 步）。
- **派生页不是权威源**：`topics.md` / `machine-changes.md` / `machine-symbols.md` / `upstream-commits.md` 都是渲染或抽取导航；引用仍要回源到 pinned commit，数据改动分别走 `source-map.yaml` 或 sync。
- **引用与许可**：上游文档摘录保留 LGPL-3.0（见 `NOTICE`），目录数据为 CC BY 4.0（见 `LICENSE-DATA`）；引用时保留上游仓库、版本与 commit，再分发时保留归属声明。
