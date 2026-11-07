---
name: maallmwiki
description: 把 MaaFramework 事实问题路由到版本锁定的原始出处——字段语义与默认值、参数版本支持、API 签名、JSON schema、协议行为与版本变更。任何 MaaFW 事实核查（"这个字段什么意思/默认值多少/哪个版本引入"）或其他 MaaFW skill 指示"路由 MaaLLMWiki"时使用；回答必须引用 pinned 出处，禁止凭记忆作答。Use for any MaaFramework factual question — field semantics and defaults, version support, API signatures, schemas, protocol behavior and version changes — and whenever another MaaFW skill says to route through MaaLLMWiki. Answers must cite the version-pinned upstream source, never model memory.
---

# MaaLLMWiki 知识路由

MaaLLMWiki 是面向模型的**源目录与版本路由层**：索引上游官方文档、schema 与源码，并把每条引用锁定到不可变 commit（40 位 SHA）。它不复制全文、不替代原始内容——索引只保留标题、自动摘取的首段摘要与 pinned 出处链接；回答事实问题必须**回源**到它指向的原始出处。目录内容托管在 https://github.com/Windsland52/MaaLLMWiki ，本文所有相对路径均相对该仓库根。消费者契约、保证边界与已知局限见 `CATALOG-CONTRACT.md`；目录数据以 CC BY 4.0 发布，上游文档摘录保留 LGPL-3.0（归属见 `NOTICE`）。

本 skill 是标准路由流程；MaaTutorial 的 maafw-* 开发 skill 中"路由 MaaLLMWiki"指的就是执行本流程。
**skill 版本**：2026-11-07d。安装到本地的是本文件的快照；结构与流程升级后需要重装（见下方"版本纪律"）。

## 版本纪律（每次使用先做，防止拿旧目录作答）

1. **解析最新发布版本**：`curl -s https://api.github.com/repos/Windsland52/MaaLLMWiki/releases/latest`，取 `tag_name`（或 `gh release view --json tagName -q .tagName`）。GitHub 不通时跳过这一步，用第 3 步的本地版本并声明“未与最新发布核对”。
2. **引用钉到不可变版本**：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>` 或 jsDelivr `@<tag>`；**不要用 `main`**（分支会移动，答案无法复现）。
3. **本地检出先对版本**：`git fetch --tags` 后用 `git describe --tags --dirty` 看当前位置（不要加 `--abbrev=0`，它会把“标签之后的新提交”藏起来）。离线或只读使用时跳过 fetch，只和本地已有的 tag 比较，并声明“未与最新发布核对”：
    - 结果就是最新 tag → `catalog_version` 写这个 tag。
    - 落后于第 1 步的 tag → 切到该 tag（`git checkout <tag>`）或下载该版本 release bundle，再作答。
    - 形如 `v0.1.35-4-g948f4dd`（比最新 tag 多出未发布的提交）→ 直接用这个检出，**不要退回旧 tag**；`catalog_version` 写完整的 describe 结果（带 `-dirty` 时说明有本地改动），目录引用钉到 40 位提交（`git rev-parse HEAD`）。未推送的提交没有 raw 链接，用“仓库内路径 + 提交 SHA”引用。
4. **陈旧特征自检**：目录里没有 `generated/maa-framework/upstream-commits.md`、或还有 `behaviour-changes.md`，说明快照太旧（机器层还没有 C API 函数、结构体字段和常量）。最新发布也不满足时，用仓库默认分支的当前提交并钉到 40 位 SHA；还不满足就声明“目录未更新”，只用已有页面作答。
5. **安装副本更新**：安装副本的“skill 版本”行早于仓库里 `skills/maallmwiki/SKILL.md` 时，重装：`npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global`（不必每次都装）。本仓库 CI 会校验本文引用的目录路径存在，路径失效会直接让发布失败，因此流程与目录结构保持同步。


## 路由步骤

1. **定版本**：以被开发项目实际使用的 MaaFramework（下称 MaaFW）版本为准（运行时/依赖声明/用户陈述）。版本未知 → 用最新稳定版并**明确声明该假设**。可用版本清单见 `generated/maa-framework/index.md`（目录没有 `latest`，必须先选版本）。
    - **预发布版本**（如 `5.16.0-beta.2`）：从 `generated/maa-framework/prereleases.md` 取它的 commit，事实一律在该 commit 上回源；目录页面用它之前最近的已索引稳定版（`git -C <上游 clone> describe --tags --abbrev=0 --exclude '*-*' <tag>`），再用 `git log <稳定版>..<tag>` 看之后又改了什么。Included in 列为 `no` 表示尚未进入任何稳定版。
    - **兼容一个版本范围**（如“用 5.15.0，最低兼容 5.4.0”）：在下限版本上确认文档、schema 和实现都支持，并用第 5 步找到它的引入版本；引入版本高于下限就是不兼容。
    - **升级问题**（“升到 5.15.0 还能用吗”）：有起点和终点两个版本；起点未知就不假设，给出变化发生在哪个版本，并把它与终点之间的相关修改一起列出（`machine-changes.md` 加 `upstream-commits.md`）。
2. **进目录**：`generated/maa-framework/<版本>/`（版本页末尾的 Navigation 段有上一版/下一版与顶层页链接）。`Changed since <上一版本>` 只列这一版哪些**已索引文件**变了（文档、头文件、绑定、schema；不含 `source/` 下的实现源码），答“哪个版本”一类问题不要从这里逐版翻，直接用第 5 步。
3. **按域选索引**：
    | 要查什么 | 索引位置 |
    | --- | --- |
    | 协议/文档（3.1 Pipeline 协议、3.3 Project Interface V2、2.x 集成、4.x 构建） | `documentation/zh-cn.md` / `en-us.md`——按上游文档编号列条目，每条链到 pinned commit 的原文（长文档没有字段锚点，用字段名 grep） |
    | Python / NodeJS 绑定 API（随框架版本） | 文件清单在 `bindings/`（只列文件，不列符号）；查具体方法/字段用 `machine-symbols.md`（第 5 步） |
    | Go / Rust / C# 绑定 API（独立 pin） | `generated/maa-framework-go/`、`generated/maa-framework-rs/`、`generated/maa-framework-csharp/` 的 `<版本>/api.md` |
    | 原生 API | `native-api/` |
    | JSON Schema | `schemas.md` |
    | 主题级 / 跨版本 | `generated/maa-framework/topics.md`（策展的少量主题，没有对应主题就跳过）；`machine-symbols.md` / `machine-changes.md` / `upstream-commits.md`（见第 5 步） |

    注册了哪些信息源见 `sources/repositories.yaml`。
4. **回源作答**：打开条目给出的 pinned commit 读**原文**再回答；引用时注明上游文件 + MaaFW 版本 + commit。禁止把目录索引本身当作字段语义的出处，禁止把链接换成移动分支（main / master）。
    - **读上游原文**：能联网就打开 pinned 链接；有上游本地 clone 时用 `git -c core.quotepath=false -C <clone> show <40 位 SHA>:<路径>`、`git grep <词> <SHA> -- <路径>`，提交 diff 用 `git show <SHA>`（中文路径要加 `core.quotepath=false`）。实现源码（`source/`）目录不索引，但可以并且应该在同一 commit 上直接读；git 子模块（如 MaaUtils）不在范围内，读不到就标注“未验证”。
    - **来源冲突时**：实现源码 > JSON schema / 头文件 > 协议文档正文。不一致就在回答里写明冲突并按代码作答。绑定可能跟不上框架：字段或参数改名后，要分别核对 Python 与 NodeJS 绑定，它们可能还停在旧名。没有框架内实现的协议（如 interface.json 的 Project Interface，5.15.0 源码里已没有 MaaPiCli）以协议文档和 schema 为准，实际行为取决于读取它的客户端。
    - **修复类问题**：确认修复提交包含在目标版本里（`git merge-base --is-ancestor <提交> <tag>`；第一个包含它的 tag，含预发布，用 `git tag --contains <提交>`），并在目标版本的源码里确认改动仍在。Agent 模式下主进程（AgentClient）和子进程（AgentServer）各用一份 MaaFW，修复在哪一侧就核对哪一侧的版本。
    - **“弃用了还能不能用”**：声明里的 deprecated 标记只说明意图；还要在同一 commit 上读实现（`git grep <函数名> <SHA> -- source/`），确认它仍被实现、是否变成兼容层或会回退到别的行为。源码里的提交用 `git log <旧 tag>..<新 tag> -- <路径>` 找。
5. **主题级定位与跨版本比较**：
    - **某符号/字段/枚举/常量/函数哪个版本引入、哪个版本弃用**：先 grep `generated/maa-framework/machine-symbols.md`。Introduced 列是“上一已索引版本没有、这一版有”的版本；`≤ 5.0.0` 表示首个已索引版本就已存在；从未变过的元素不在表里（去目标版本的 pinned 文件里确认它存在即可）。符号写法：C 用裸名（`MaaLinuxControllerCreate`、`MaaCustomControllerCallbacks.shell`、`Win32ControlUnitAPI::set_background_managed_keys_option`），Python 用 `maa.controller:Controller.post_shell`，NodeJS 用 `maa.Controller.post_click`，schema 用点分路径（`$defs.Shell.cmd`、`definitions.pretaskConfig`；数组元素写 `[]`，如 `preset[].pretask[].name`）。路径写法不确定时，用字段名的最后一段 grep。
    - **某版本具体变了什么**：`generated/maa-framework/machine-changes.md`，按版本、文件列出声明元素的 added / removed / modified（附旧文本）/ deprecated；页面很长，按 `## [版本]` 标题或符号名 grep，不要整页读。页面引文超过 200 字会被截断并以 `…` 结尾，`sources/maa-framework/machine-changes.yaml` 保留前 300 字；仍不完整时回源读文件。结构体新增字段只记 added，不记位置；C 结构体中间插入字段会改变后面字段的偏移，是否破坏二进制兼容要看头文件 diff。
    - **行为变更（声明没变、行为变了）**：`generated/maa-framework/upstream-commits.md`，按版本列出两版之间的上游提交（标题、PR、至多 5 个改动路径；完整路径在 `sources/maa-framework/upstream-commits.yaml`，或用 `git show --stat <SHA>`）。标题常常只写原因、不写症状，按标题关键词未必找得到。有上游 clone 时，最准的办法是按相关模块的路径列提交：`git log --oneline <旧 tag>..<新 tag> -- <路径>`（如 `source/MaaAgentServer/`、`source/MaaLinuxControlUnit/`）；没有 clone 时在本页按路径、再按关键词找。找到后读该提交的 diff。提交标题只是作者意图，不是已验证的行为。
    - **主题定位**：`generated/maa-framework/topics.md`——策展的少量主题（主题 → 按版本适用的变体 → pinned 原始路径 + 符号 + 字面搜索词，由 `sources/maa-framework/source-map.yaml` 渲染）。没有对应主题就直接用上面三页。
    - **协议版本号 ≠ MaaFW 版本号**：3.1 / 3.3 文档的版本表里，`v5.11`、`v2.10.3` 这类是协议版本标签，可能和引入该功能的 MaaFW 版本相差好几个版本；3.1 的版本表在 MaaFW 5.8.0 才加入，所以机器层把那时已有的全部行都记为 5.8.0 added。答“MaaFW 哪个版本开始支持”时以声明元素或提交的引入版本为准，不要用协议版本标签。
    - **机器层的边界**：只比较声明（头文件、树内 Python/NodeJS 绑定、JSON schema、3.1/3.3 协议版本表），不含运行时语义；文档正文没有解析器（变化只在版本页 `Changed since` 里）；`unclassified` 表示头文件/绑定/schema 变了但声明没变（注释、格式或解析器不读的写法），或文件无法解析。结论仍要回源到 pinned 文件。
6. **消费通道**（按连通性择优）：
    - 本地 Git 检出：一次克隆长期可用，弱网环境最稳（版本对齐见「版本纪律」第 3 步）；
    - raw 直链：`https://raw.githubusercontent.com/Windsland52/MaaLLMWiki/<tag>/<相对路径>`，如 `generated/maa-framework/<版本>/documentation/zh-cn.md`；GitHub 不通畅时换 jsDelivr 镜像 `https://cdn.jsdelivr.net/gh/Windsland52/MaaLLMWiki@<tag>/<相对路径>`（`@<tag>`/`@<commit>` 不可变；`@main` 会移动，只作应急）；
    - release bundle：GitHub Releases 的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，解压即可离线读；下载、校验（`SHA256SUMS`、build provenance、`verify_bundle.py`）和 `-latest` 别名的区别见 README 与 `CATALOG-CONTRACT.md`。

    不引入 chunking / embedding / vector / MCP——目录就是分层 markdown，直接读。

## 跨版本材料差异（maa-wiki-diff）

`Changed since` 只是页面摘要（有截断）。要完整、可复现的差异列表，在本地检出后运行下面的命令（`uv run` 会在检出目录里创建 `.venv`。只读使用时直接比较两个 MaaFW 版本的清单文件：`git diff --no-index sources/maa-framework/inventories/<旧版本>.yaml sources/maa-framework/inventories/<新版本>.yaml`，`blob:` 行变化的是内容变化的文件，`- path:` 行增减的是新增或删除的文件；不要比较两个目录 tag，那比较的是目录快照，不是 MaaFW 版本）：

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

预发布只登记 tag 与 commit（`generated/maa-framework/prereleases.md`，绑定源在各自目录的 `prereleases.md`），**不生成 inventory、没有版本目录**，也不能作为 `maa-wiki-diff` 的 `--from`/`--to`。事实在该表的 pinned commit 上回源；目录页面和前后对比的方法见路由步骤第 1 步。

## 硬规则

- **两个版本维度**：MaaFW 目标版本 ≠ Wiki 自身 Git revision，引用时说清对象；引用一律 pin 到 tag/commit，不用 `main`。
- **旧快照即未验证**：安装副本或本地检出落后时不静默沿用，按「版本纪律」对齐并声明所用 `catalog_version`；比最新发布更新的检出不算落后。
- **不可达即未验证**：目录或上游拿不到 → 回答显式标注"未验证"，不用记忆补；宁可少答。
- **内容边界**：本仓库只做路由，不收项目实践/教程/日志/诊断——开发实践在 MaaTutorial，项目事实在各项目仓库。
- **机器层没有记录 ≠ 行为没变**：它只看声明；行为问题要查 `upstream-commits.md` 并读提交 diff（边界见路由步骤第 5 步）。
- **派生页不是权威源**：`topics.md` / `machine-changes.md` / `machine-symbols.md` / `upstream-commits.md` 都是渲染或抽取导航；引用仍要回源到 pinned commit，数据改动分别走 `source-map.yaml` 或 sync。
- **引用与许可**：上游文档摘录保留 LGPL-3.0（见 `NOTICE`），目录数据为 CC BY 4.0（见 `LICENSE-DATA`）；引用时保留上游仓库、版本与 commit，再分发时保留归属声明。
