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
- Added `odracir search` for inspectable lexical retrieval with paper, page, and chunk citations.
- Exposed the same retrieval capability to the LLM as `search_research_chunks`.
- Updated the Odracir system prompt from an agent-building example toward an evidence-aware research companion.
- Added a DeepSeek provider adapter for OpenAI-compatible chat and JSON completions.
- Added `odracir summarize` for evidence-aware map-reduce summaries over traceable chunks.
- Added summary metadata, usage recording, source-chunk citation allowlisting, idempotent skipping, and downstream invalidation.
- Added an optional Docling PDF parser adapter that preserves the normalized page-level artifact contract.
- Added `odracir capabilities` to report optional parser and preprocessor availability.
- Added explicit `odracir ocr` preprocessing through OCRmyPDF derivatives without modifying source PDFs.
- Added extraction provenance and cache invalidation for parser changes and OCR-derived inputs.
- Added `odracir translate` for explicit, selective translation of traceable chunks through DeepSeek.
- Added default abstract, methods, and conclusion selection with a controlled chunk limit.
- Added precise `--section`, `--chunk`, and explicit `--all-chunks` translation modes.
- Added `odracir translate --dry-run` to preview selected citations without loading API configuration or calling DeepSeek.
- Added translation artifacts with source citations, selection hashes, provider/model/prompt metadata, token usage, and idempotent skipping.
- Decoupled summary and translation invalidation while keeping both downstream of chunk changes.
- Added retrieval-first `odracir ask` for folder-level questions over ranked local evidence.
- Added `odracir ask --dry-run` to inspect selected evidence without loading API configuration or calling DeepSeek.
- Added answer artifacts, lazy provider creation, context limits, cache revalidation, and citation allowlisting for claims and inline answer text.
- Expanded the external parser benchmark strategy with PyMuPDF4LLM, Marker, and Unstructured while keeping heavier integrations behind adapters or service clients.
- Added an optional `pymupdf4llm` layout-aware Markdown parser adapter with explicit OCR disabled.
- Added `odracir benchmark-parsers` for read-only parser comparisons over indexed PDFs.
- Added parser benchmark summaries for success counts, timing, extracted characters, baseline deltas, and isolated backend failures.
- Normalized PyMuPDF provenance to record its release version instead of the library's version tuple.
- Added `odracir recommend-parsers` for cached advisory routing recommendations without changing extraction artifacts.
- Added conservative review thresholds, explicit OCR routing, cache invalidation by PDF hash/parser version/policy version, and isolated candidate-parser failures.
- Added a versioned research-skill registry with `generic@0.1` and `biomedical-paper@0.1`.
- Added `odracir skills [name]` and the read-only `list_research_skills` agent tool.
- Added `odracir summarize --skill biomedical-paper --dry-run` for no-cost summary-scope review.
- Added biomedical summary schema extensions with citation-or-inference validation, artifact provenance, and cache invalidation when the selected skill changes.
- Added deterministic `odracir evaluate-summaries` with cached local reports, stale-evidence detection, citation revalidation, domain completeness metrics, and review warnings.
- Added the read-only `evaluate_research_summaries` agent tool for summary-readiness and quality checks.

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
- 添加 `odracir search`，用于返回论文、页码和 chunk 引用的可检查关键词检索。
- 将同一检索能力作为 `search_research_chunks` 暴露给 LLM。
- 将 Odracir 系统 prompt 从 agent 构建示例更新为注重证据的科研 companion。
- 添加用于 OpenAI-compatible chat 和 JSON completion 的 DeepSeek provider adapter。
- 添加 `odracir summarize`，用于基于可追溯 chunk 生成注重证据的 map-reduce 摘要。
- 添加摘要元数据、用量记录、源 chunk 引用白名单校验、幂等跳过和下游失效传播。
- 添加可选 Docling PDF parser adapter，并保持标准化按页 artifact 契约。
- 添加 `odracir capabilities`，用于报告可选 parser 和预处理器是否可用。
- 添加显式 `odracir ocr`，通过 OCRmyPDF derivative 预处理而不修改原始 PDF。
- 添加提取 provenance，以及 parser 切换和 OCR derivative 输入变化后的缓存失效。
- 添加 `odracir translate`，通过 DeepSeek 显式、选择性地翻译可追溯 chunk。
- 添加默认摘要、方法和结论选择，并设置受控 chunk 上限。
- 添加精确 `--section`、`--chunk` 和显式 `--all-chunks` 翻译模式。
- 添加 `odracir translate --dry-run`，无需读取 API 配置或调用 DeepSeek 即可预览选定引用。
- 添加包含来源引用、选择 hash、provider/模型/prompt 元数据、token 用量和幂等跳过的翻译 artifact。
- 将摘要与翻译的失效传播解耦，同时保持二者都在 chunk 变化后失效。
- 添加检索优先的 `odracir ask`，用于基于排序后的本地证据回答文件夹级问题。
- 添加 `odracir ask --dry-run`，无需读取 API 配置或调用 DeepSeek 即可检查选定证据。
- 添加问答 artifact、provider 懒加载、上下文上限、缓存重新校验，以及对 claims 和答案内联引用的白名单校验。
- 使用 PyMuPDF4LLM、Marker 和 Unstructured 扩展外部解析器基准策略，同时让较重集成保持在 adapter 或服务客户端之后。
- 添加可选 `pymupdf4llm` 版式感知 Markdown parser adapter，并禁用其隐式 OCR。
- 添加 `odracir benchmark-parsers`，用于对已索引 PDF 执行只读 parser 比较。
- 添加 parser benchmark 汇总，包括成功数、耗时、提取字符数、相对默认后端差异和隔离后的后端失败。
- 将 PyMuPDF provenance 规范化为发行版本号，而不是记录整个库版本 tuple。
- 添加 `odracir recommend-parsers`，用于缓存建议式 parser 路由，而不修改 extraction artifact。
- 添加保守审阅阈值、显式 OCR 分流、基于 PDF hash/parser 版本/策略版本的缓存失效，以及候选 parser 失败隔离。
- 添加版本化科研 skill registry，包含 `generic@0.1` 和 `biomedical-paper@0.1`。
- 添加 `odracir skills [name]` 和只读 `list_research_skills` agent tool。
- 添加 `odracir summarize --skill biomedical-paper --dry-run`，用于无费用地审阅摘要范围。
- 添加带 citation-or-inference 校验、artifact provenance 和 skill 切换缓存失效的生物医学摘要 schema 扩展。
- 添加确定性 `odracir evaluate-summaries`，包括带缓存本地报告、过期证据检测、引用重新校验、领域完整性指标和审阅 warning。
- 添加只读 `evaluate_research_summaries` agent tool，用于检查摘要就绪状态和质量。

### Planned / 计划

- Evolve the first `odracir_index.json` schema after real paper processing.
- Benchmark paper translation and structured summaries on reviewed examples.
- Benchmark and refine richer retrieval and cited answers over reviewed folder-level questions.
- Add a research-companion agent that reuses the audited retrieval and answer paths.
- Review cached parser-routing recommendations and representative PyMuPDF4LLM output quality before accepting per-paper overrides.
- Review biomedical summary dry runs, then benchmark selected DeepSeek summaries before folder-wide execution.

- 在真实论文处理后继续演进第一版 `odracir_index.json` schema。
- 在人工审阅样例上评估论文翻译和结构化摘要。
- 在人工审阅的文件夹级问题上评估和优化更丰富的检索与带引用问答。
- 添加复用已审计检索和问答路径的科研 companion agent。
- 审阅缓存的 parser 路由建议和代表性 PyMuPDF4LLM 输出质量，再接受逐篇 parser override。
- 审阅生物医学摘要 dry-run，再对选定论文执行 DeepSeek 摘要 benchmark，然后考虑整目录运行。

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
