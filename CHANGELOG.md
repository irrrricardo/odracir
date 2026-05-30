# Changelog / 版本记录

This file records meaningful changes to Odracir.

本文件用于记录 Odracir 的重要版本变化、设计演进和阶段性计划。

The format loosely follows Keep a Changelog, but stays practical for a personal research agentic system.

本文件大致参考 Keep a Changelog 的风格，但会优先服务于个人科研 agentic system 的实际迭代。

## [Unreleased] / 未发布

### Added / 新增

- Added a research-folder harness that creates `papers/`, `notes/`, and `code/`, scans paper files, and maintains `odracir_index.json`.
- Added an `odracir scan <research-folder>` command.
- Added generated README project-status blocks.
- Added an `odracir sync-docs` command.
- Added a `.githooks/pre-commit` hook template for automatic docs sync before commits.
- Added `odracir install-hooks` to configure the local repository to use project hooks.
- Added `--papers-dir` to scan existing custom paper storage folders.
- Added `odracir extract` for page-level PDF text extraction into `.odracir/texts/`.
- Added `WORKFLOW.md` to document the operating workflow and the distinction between tools, agent tools, and future skills.
- Added `ARCHITECTURE.md` with module boundaries, data lifecycle, scientific data model, pipeline states, phased roadmap, and acceptance criteria.
- Added typed schemas and index validation for project, paper, extraction, text, and chunk artifacts.
- Added `odracir status` for processing-state, OCR-need, and failure reporting.
- Added deterministic page-traceable chunking and the `odracir chunk` command.
- Added source-change invalidation for generated downstream artifacts.
- Added a replaceable parser registry with `pymupdf` as the initial backend.
- Documented the external parser strategy for Docling, OCRmyPDF, GROBID, and MinerU.
- Added failure-mode tests for invalid PDFs, likely scanned PDFs, schema errors, source changes, and stable chunk IDs.

- 添加研究文件夹 harness，用于创建 `papers/`、`notes/` 和 `code/`，扫描论文文件，并维护 `odracir_index.json`。
- 添加 `odracir scan <research-folder>` 命令。
- 添加 README 自动生成项目状态区块。
- 添加 `odracir sync-docs` 命令。
- 添加 `.githooks/pre-commit` hook 模板，用于在提交前自动同步文档。
- 添加 `odracir install-hooks`，用于配置本地仓库使用项目 hook。
- 添加 `--papers-dir`，用于扫描已有的自定义论文存储文件夹。
- 添加 `odracir extract`，用于将 PDF 正文按页提取到 `.odracir/texts/`。
- 添加 `WORKFLOW.md`，用于记录工作流程，以及 tool、agent tool 和未来 skill 的区别。
- 添加 `ARCHITECTURE.md`，用于记录模块边界、数据生命周期、科学化数据模型、流水线状态、分阶段路线图和验收标准。
- 添加项目、论文、提取、正文和 chunk artifact 的类型化 schema 与索引校验。
- 添加 `odracir status`，用于报告处理状态、OCR 需求和失败项。
- 添加确定性的按页可追溯 chunking 和 `odracir chunk` 命令。
- 添加源文件变化后对下游生成 artifact 的失效传播。
- 添加可替换解析器注册表，并将 `pymupdf` 作为首个后端。
- 记录 Docling、OCRmyPDF、GROBID 和 MinerU 的外部解析器接入策略。
- 添加损坏 PDF、疑似扫描件、schema 错误、源文件变化和稳定 chunk ID 的失败模式测试。

### Planned / 计划

- Evolve the first `odracir_index.json` schema after real paper processing.
- Add paper translation and structured summary tools.
- Add retrieval over paper records and extracted text.
- Add a research conversation agent that can use folder-level evidence.

- 在真实论文处理后继续演进第一版 `odracir_index.json` schema。
- 添加论文翻译和结构化摘要工具。
- 添加基于论文记录和提取文本的检索能力。
- 添加能够使用文件夹级证据的科研交流 agent。

## [0.1.0] - 2026-05-30 / 初始版本

### Added / 新增

- Created the initial Odracir project structure.
- Added DeepSeek API configuration through an OpenAI-compatible client.
- Added a minimal agent loop with tool calling.
- Added a small tool registry with example project-planning tools.
- Added a command-line entry point.
- Added initial unit tests for tool execution.
- Added English and Chinese README files describing Odracir as a personal research agentic system.
- Added this changelog file for future version tracking.

- 创建 Odracir 初始项目结构。
- 通过 OpenAI-compatible 客户端添加 DeepSeek API 配置。
- 添加支持工具调用的最小 agent loop。
- 添加小型工具注册表和示例项目规划工具。
- 添加命令行入口。
- 添加工具执行相关的初始单元测试。
- 添加英文和中文 README，将 Odracir 定位为个人科研 agentic system。
- 添加本版本记录文件，用于后续版本追踪。

### Notes / 记录

- The project is intentionally still a single-agent prototype.
- The first real milestone is not multi-agent orchestration, but a reliable loop for paper intake, structured summary, and folder-level memory.
- GitHub publishing still requires a GitHub remote and authentication on the local machine.

- 当前项目仍然刻意保持为单 agent 原型。
- 第一个真实里程碑不是多 agent 编排，而是跑通论文收纳、结构化摘要和文件夹级记忆的可靠闭环。
- 推送到 GitHub 仍需要本地配置 GitHub 远程仓库和认证。
