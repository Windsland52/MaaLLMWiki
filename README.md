# MaaLLMWiki

[English](README.en.md) | **中文**

MaaLLMWiki 为 Maa 生态知识提供机器可读、版本化的源目录：它帮助模型选择并定位原始文档、schema、公开 API 与源码，不编写、也不替代这些源。目录快照以可校验的 catalog bundle 发布，消费者契约见 `CATALOG-CONTRACT.md`。

## 范围

收录：

- 完整的版本锁定 MaaFramework 文档、schema、原生 API 与树内绑定 API 索引；
- 独立版本化的 Go、Rust 与 C# 绑定 API 索引，附明确的兼容性证据；
- 主题到源的导航；从上游机器抽取的版本间 API 声明变更与上游提交索引。

不收录：

- 项目专属文档与 Pipeline 配置；
- 原始用户产物、日志与基准测试答案；
- MaaFramework 文档或源码树的全文拷贝（索引只保留标题、自动摘取的首段摘要与 pinned 出处链接）；
- 人工撰写的教程、最佳实践与诊断方法论；
- 未经核实的模型生成结论。

Go、Rust 与 C# 绑定作为独立外部源登记，各自有锁定清单与兼容性证据；C# 通过 NuGet `Maa.Framework` 分发，其稳定 release 自 `v5.1.0` 起对齐 MaaFramework 5.x tag（预发布最早从 `v5.0.0-preview.1` 起）。Java 被上游文档标注为过时，不是默认 API 源；原生公开 API 为 C/C++ 头文件，树内 Python/NodeJS 绑定 API 随 MaaFramework 版本索引。

## 30 秒选版本

1. **用哪个 MaaFramework 版本** → `generated/maa-framework/index.md` 顶部的 Current snapshot（最新版本与总数），或列表里挑一个；
2. **这一版里有什么** → 该版本 `index.md`：各域文件数、页尾 Navigation（上一版/下一版/顶层页）；
3. **某字段/API/枚举是哪个版本引入的** → `generated/maa-framework/machine-symbols.md`（元素 → 引入版本与之后的改动）；某版具体变了什么看 `machine-changes.md`，声明没变的行为变更看 `upstream-commits.md`；
4. **两版之间哪些被索引材料变了** → 版本页的 `Changed since` 摘要，或 `uv run maa-wiki-diff --from <旧> --to <新>`；
5. **需要事实出处** → 页面链接钉到 40 位 commit，回源引用。

## 使用

1. 从 Releases API 或 release 页面下载带版本的 `maa-llm-wiki-catalog-vX.Y.Z.zip`，并同时下载该 release 的 `SHA256SUMS` 与 `verify_bundle.py`。zip 根目录有 `START-HERE.md`，并自带 README、契约、运维指南与许可文件，解压即可离线阅读。
2. 按顺序校验：
   - `sha256sum -c SHA256SUMS`
   - `gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`
   - `python verify_bundle.py --bundle maa-llm-wiki-catalog-vX.Y.Z.zip --expect-version vX.Y.Z --checksums SHA256SUMS`
3. 便利别名 `https://github.com/Windsland52/MaaLLMWiki/releases/latest/download/maa-llm-wiki-catalog-latest.zip` 会被每个新版本原地覆盖，不用于复现；历史 release 可能没有该别名。只有版本化 zip 带 attestation，别名、`SHA256SUMS` 与脚本不在证明范围内。
4. 比较两个已索引 release 的已索引材料变化：`uv run maa-wiki-diff --from <旧版本> --to <新版本>`；完整、无截断的列表以它为准。
5. 安装 `skills/maallmwiki/SKILL.md` 中的 agent skill（MaaTutorial 的 `maafw-*` 开发 skill 把事实问题交给它）：`npx skills add https://github.com/Windsland52/MaaLLMWiki --skill maallmwiki --global`

没有 Python 3 或想用 uv 时，可用 `uv run maa-wiki-verify-bundle --bundle <zip> [--expect-version vX.Y.Z]` 或 `uvx --from "maa-llm-wiki @ git+https://github.com/Windsland52/MaaLLMWiki" maa-wiki-verify-bundle --bundle <zip>`；细节见 `docs/operations.md`。

已发布的 release 正文由目录自身生成，汇总上游快照、新上游 release、机器事实与校验命令；细节见 `docs/operations.md`。

## 内容

```text
generated/maa-framework/index.md
  -> topics.md · machine-changes.md · machine-symbols.md · upstream-commits.md
  -> <version>/index.md            # 含 "Changed since <上一已索引版本>"
       -> documentation/ · bindings/ · native-api/ · schemas.md
```

每个版本目录提供分域导航；`topics.md` 是策展主题路由，`machine-changes.md` / `machine-symbols.md` 是从上游文件机器抽取的声明变更（按版本 / 按元素），`upstream-commits.md` 按版本列出上游提交。`generated/maa-framework-{go,rs,csharp}/` 提供 Go/Rust/C# 绑定的同级索引。页面含义、清单语义与完整目录结构见 `docs/operations.zh.md`。

版本索引末尾的 `Changed since` 只列已索引文件的移动；声明变化看 `machine-changes.md`，行为变更从 `upstream-commits.md` 找到提交再读 diff。

## 更多

| 想要 | 去处 |
| --- | --- |
| 保证、校验规则、已知局限（§8） | [`CATALOG-CONTRACT.md`](CATALOG-CONTRACT.md) |
| 如何修改目录/代码、内容边界与必需检查 | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| 流水线、快照生命周期、失败处理、开发命令 | [`docs/operations.zh.md`](docs/operations.zh.md)（中文；[English](docs/operations.md)） |
| 安全与私密报告 | [`SECURITY.md`](SECURITY.md) |
| 许可与归属 | [`LICENSE`](LICENSE)、[`LICENSE-DATA`](LICENSE-DATA)、[`NOTICE`](NOTICE) |

快照每天生成两次（best-effort）；pipeline 失败会打开去重的 `pipeline-failure` issue，并在下一次成功运行时关闭。

## 许可证

- 代码（Python 源码、测试、workflow 与构建工具）以 MIT 发布：见 `LICENSE`。
- 目录数据（元数据、清单、生成的导航页面、schema 与发布 bundle）以 CC BY 4.0 发布：见 `LICENSE-DATA`。
- 目录中对 MaaXYZ 上游仓库文档的短摘录保留其上游许可证（LGPL-3.0）：见 `NOTICE`。

再分发目录数据或摘录时请保留上述归属声明；本仓库的许可不改变上游材料的许可。
