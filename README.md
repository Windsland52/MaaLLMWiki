# MaaLLMWiki

[English](README.en.md) | **中文**

MaaLLMWiki 为 Maa 生态知识提供机器可读、版本化的源目录。它帮助模型选择并定位原始文档、schema、公开 API 与源码；它不编写、也不替代这些源。

## 范围

收录：

- 完整的版本锁定 MaaFramework 文档、schema、原生 API 与树内绑定 API 索引；
- 独立版本化的 Go 与 Rust 绑定 API 索引，附明确的兼容性证据；
- 主题到源的导航与语义版本变更；
- 一个尚未启用的 MaaTutorial 注册项（等待其成稿指南就绪）。

不收录：

- 项目专属文档与 Pipeline 配置；
- 原始用户产物与基准测试答案；
- MaaFramework 文档或源码树的拷贝；
- 人工撰写的教程、最佳实践与诊断方法论；
- 未经核实的模型生成结论。

成稿的 Pipeline 指南与诊断方法论归属 MaaTutorial。Maa 项目细节必须从对应项目仓库获取，并尊重其自身的 `AGENTS.md`。MaaTutorial 在选定稳定修订前保持禁用占位注册。

## 布局

```text
sources/repositories.yaml       已注册的上游仓库
sources/maa-framework/          发布、清单、语义变更与源路由元数据
sources/maa-framework-{go,rs}/  独立绑定发布与源清单
sources/compatibility/          有证据支撑的绑定兼容性元数据
generated/maa-framework/        生成的发布与分域导航索引
generated/maa-framework-{go,rs}/ 生成的绑定发布导航索引
schemas/                        生成的元数据 JSON schema
skills/maallmwiki/              可安装的路由 agent skill
src/maa_llm_wiki/               Python 同步与校验工具
tests/                          确定性仓库检查
```

生成的索引不包含任何上游内容拷贝，无需人工分块、embedding 或向量数据库。MaaFramework 源码保留在它自己的 Git 仓库中，按目录选定的修订进行检索。

生成导航的分层结构：

```text
generated/maa-framework/index.md
  -> <version>/index.md
       -> documentation/{en-us,zh-cn,nodejs,tools}.md
       -> bindings/{python,nodejs}.md
       -> native-api/{framework,control-units,toolkit,agents}.md
       -> schemas.md
       -> documentation/diagrams.md
```

`sources/maa-framework/inventory.yaml` 仍是用于覆盖率检查的扁平权威产物清单，它不是导航接口。

## 开发

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

当前生效修订记录在 `sources/repositories.yaml`；不可变发布历史存放在各源目录之下。现有自动化已索引 MaaFramework v5、Go 绑定与 Rust 绑定的全部稳定发布。MaaTutorial 刻意尚未纳入。

## 目录快照

模型（LLM/Agent）可在开发期直接读取本 Git 检出。打 tag 的发布提供带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip` 产物，内含 `sources/`、`generated/`、`schemas/` 与 `catalog-manifest.json`。消费者通过 GitHub Releases API 发现最新的带版本产物。manifest 锁定 Wiki commit 与当前上游修订，并记录每个打包文件的体积与 SHA-256 摘要。快照由已提交的目录修订构建，因此其 tag 精确命名它所携带的目录；`maa-wiki-build-bundle` 拒绝脏工作树，`--allow-dirty` 仅供本地开发与测试使用。

快照 tag 及运送其 bundle 的 release 由下述 publish workflow 产生。若某次运行在默认分支上发现未打快照 tag 的目录数据，会改为发布该修订而不创建第二个 tag——被中断的发布会在下一次运行时自愈。`v0.1.2` 是在 workflow 合并前打的 tag，不带 bundle 产物；其编号不再复用。

清单将 C/C++ 头文件视为原生公开 API。`source/binding/Python/maa` 下的 Python 模块与 `source/binding/NodeJS/src/apis/*.d.ts` 下的 NodeJS 声明属于树内绑定 API。C#、Go、Rust 绑定位于独立仓库，需要各自的锁定清单与 MaaFramework 兼容性元数据；它们不得继承 MaaFramework 仓库修订。Java 绑定被 MaaFramework 文档标注为过时，不是默认 API 源。

## Agent skill

`skills/maallmwiki/SKILL.md` 把标准路由流程——选定目标 MaaFramework 版本、选择分域索引、沿 pinned commit 链接回溯原始出处——打包为可安装的 agent skill。MaaTutorial 的 `maafw-*` 开发 skill 把事实问题交给它处理。使用标准 skills CLI 安装：

```bash
npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global
```

## 自动更新

`.github/workflows/publish-catalog.yml` 掌管整个周期并每日运行。它发现 MaaFramework、Go 绑定与 Rust 绑定的最新稳定 `vMAJOR.MINOR.PATCH` tag，记录其不可变 commit，重新生成目录，运行全部检查，把结果提交到默认分支，并在同一 job 中发布快照 release。检测、提交、打 tag 与发布保持在单个 workflow 内，因为默认 `GITHUB_TOKEN` 产生的事件不会触发另一个 workflow；拆开打 tag 会留下没有 release 的 tag。该 workflow 也支持 `workflow_dispatch` 手动触发。

两条规则把人工内容挡在自动化之外：

- 当同步触碰了 `sources/maa-framework/source-map.yaml` 或 `sources/maa-framework/semantic-changes.yaml` 时，运行拒绝发布；这两个文件只能经人工 review 变更。
- workflow 绝不推断语义变更。当快照落地的发布中，已记录的官方材料晚于最新 `semantic-changes.yaml` 条目发生移动时，它会打开或更新一个 semantic-review issue，点名待检查的发布与产物（`uv run maa-wiki-report-semantic-gaps`）。每一条都是疑似触发，不是已验证的变更。

该 job 使用仓库 `GITHUB_TOKEN` 认证。若默认分支强制 pull request，请添加 `CATALOG_PUSH_TOKEN` secret——一个具 contents 与 issues 写权限、来自允许绕过该规则身份的 fine-grained token——workflow 会自动优先使用它。
