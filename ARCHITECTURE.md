# Odracir Architecture Roadmap / 架构路线图

This document describes how Odracir should evolve from a local PDF extraction prototype into a modular, evidence-aware, multi-disciplinary research agentic system.

本文档描述 Odracir 如何从本地 PDF 提取原型，逐步演进为模块化、注重证据、支持多学科的科研 agentic system。

## 1. Product Boundary / 产品边界

Odracir is not only a chatbot and should not become one giant prompt. It is a local-first research workspace with optional LLM assistance.

Odracir 不只是聊天机器人，也不应该演变成一个巨大的 prompt。它是一个本地优先、可选择使用 LLM 辅助的科研工作空间。

Its stable core responsibilities are:

它的稳定核心职责是：

1. Ingest research files without modifying the originals.
2. Convert heterogeneous files into traceable local artifacts.
3. Maintain a structured folder-level research memory.
4. Use LLM providers for translation, extraction, synthesis, and planning.
5. Preserve evidence links so claims can be traced back to source pages or sections.
6. Add discipline-specific skills without coupling the core system to one field.

1. 在不修改原始文件的前提下收纳科研资料。
2. 将不同类型文件转化为可追溯的本地 artifact。
3. 维护结构化的文件夹级科研记忆。
4. 使用 LLM provider 完成翻译、信息提取、综合分析和规划。
5. 保留证据链接，使结论可以追溯到原文页码或章节。
6. 在不把核心系统绑定到单一学科的前提下添加领域 skill。

## 2. Architecture Principles / 架构原则

### Local-First / 本地优先

Original papers and generated artifacts stay understandable on disk. A remote database can be added later, but it must not become the only source of truth.

原始论文和生成 artifact 应该在本地磁盘上保持可理解。未来可以添加远程数据库，但不能让它成为唯一事实来源。

### Evidence-Aware / 注重证据

Every structured claim should eventually support citations such as `paper_id`, `page_number`, `section`, and `chunk_id`.

每一条结构化结论最终都应该支持 `paper_id`、`page_number`、`section` 和 `chunk_id` 等引用信息。

### Incremental And Resumable / 增量执行与可恢复

Each pipeline step should read prior artifacts, skip unchanged work, record failures, and resume safely.

每一个流水线步骤都应该读取已有 artifact，跳过未变化内容，记录失败，并能够安全恢复。

### Provider-Agnostic / Provider 解耦

DeepSeek is the first LLM provider, not a permanent hard dependency. LLM calls should be wrapped behind a provider adapter.

DeepSeek 是首个 LLM provider，而不是永久硬依赖。LLM 调用应该封装在 provider adapter 后面。

### Skills Above Tools / Skill 位于 Tool 之上

Parsers and file operations are deterministic tools. Skills combine prompts, schemas, tools, and evaluation rules for a domain. Agents choose and orchestrate them.

解析器和文件操作是确定性 tool。Skill 将 prompt、schema、tool 和评测规则组合为领域能力。Agent 负责选择和编排它们。

## 3. Target Module Layout / 目标模块布局

```text
src/odracir/
  cli.py
  config.py
  harness/
    pipeline.py
    jobs.py
    state.py
  ingestion/
    registry.py
    models.py
    pdf_parser.py
    text_parser.py
    ocr.py
  artifacts/
    store.py
    paths.py
  chunking/
    chunker.py
    sectioning.py
  schemas/
    paper.py
    chunk.py
    summary.py
    project.py
  providers/
    base.py
    deepseek.py
  processing/
    summarize.py
    translation.py
    extract_fields.py
  retrieval/
    lexical.py
    embeddings.py
    citations.py
  skills/
    registry.py
    biomedical/
    computer_science/
    review/
  agents/
    research_companion.py
    orchestrator.py
  evaluation/
    fixtures.py
    metrics.py
```

This is a target layout, not an instruction to create empty folders immediately. Modules should be extracted only when real behavior enters them.

这是目标布局，不代表现在要立刻创建空文件夹。只有当真实行为出现时，才应该拆出对应模块。

## 4. Data Lifecycle / 数据生命周期

```text
source file
-> scan manifest
-> normalized extraction artifact
-> traceable chunks
   -> structured summary artifact
   -> translation artifact
-> retrieval index
-> evidence-backed answer artifacts
-> conversation and planning
```

```text
原始文件
-> 扫描清单
-> 标准化提取 artifact
-> 可追溯 chunk
   -> 结构化总结 artifact
   -> 翻译 artifact
-> 检索索引
-> 带证据的问答 artifact
-> 交流与规划
```

Recommended artifact layout:

推荐 artifact 布局：

```text
research-folder/
  odracir_index.json
  .odracir/
    project.json
    jobs/
    texts/
    chunks/
    summaries/
    translations/
    answers/
    retrieval/
    logs/
```

`odracir_index.json` should remain compact. Large text, chunk, translation, and summary payloads belong in `.odracir/`.

`odracir_index.json` 应保持精简。大段正文、chunk、翻译和总结应该放在 `.odracir/` 下。

## 5. Scientific Data Model / 科学化数据模型

Every paper should have a generic core record before any discipline-specific extension is applied.

每篇论文应该先拥有通用核心记录，再应用学科专用扩展。

Generic core fields:

通用核心字段：

```text
identity:
  id, title, authors, year, source_file, sha256
processing:
  extraction_status, chunking_status, summary_status, translation_status
research:
  research_question, background, hypothesis, methods, evidence, findings
  limitations, uncertainty, key_terms, implementation_or_validation_notes
traceability:
  artifact_paths, citations, parser_version, prompt_version, provider, model
```

Domain-specific fields should live under a namespaced extension:

领域专用字段应该放在带命名空间的扩展字段中：

```json
{
  "domain_extensions": {
    "biomedical": {
      "population": [],
      "intervention_or_exposure": [],
      "comparator": [],
      "outcomes": [],
      "biological_mechanisms": [],
      "assays_or_measurements": [],
      "clinical_relevance": "",
      "safety_or_ethics": []
    }
  }
}
```

## 6. Pipeline State Machine / 流水线状态机

Each paper should advance through explicit states:

每篇论文都应该经过显式状态：

```text
discovered
-> indexed
-> extracted | needs_ocr | extraction_failed
-> chunked | chunking_failed
-> summarized | summary_failed
-> translated | translation_skipped | translation_failed
-> retrievable
```

Each step should record:

每一步都应该记录：

```text
status
input_sha256
artifact_path
started_at
completed_at
tool_or_parser_version
provider_and_model_if_any
error_if_any
```

## 7. Tool, Agent Tool, Skill, Agent, Harness / 概念分层

```text
tool
  Deterministic capability such as PDF parsing, JSON writing, or file hashing.
  确定性能力，例如 PDF 解析、JSON 写入、文件 hash。

agent tool
  A tool exposed to an LLM through a schema.
  通过 schema 暴露给 LLM 的 tool。

skill
  A reusable domain capability package containing instructions, schemas,
  tool bindings, examples, and evaluation rules.
  可复用的领域能力包，包含说明、schema、工具绑定、示例和评测规则。

agent
  A role with goals, instructions, allowed tools, and state boundaries.
  具有目标、指令、可用工具和状态边界的角色。

harness
  The runtime that schedules work, records state, handles retries,
  controls permissions, writes artifacts, and evaluates outcomes.
  负责调度任务、记录状态、处理重试、控制权限、写入 artifact 和评估结果的运行框架。
```

The PDF parser is currently a normal tool used directly by the CLI harness. Later it can also be exposed as an agent tool. That does not require rewriting the parser.

当前 PDF parser 是由 CLI harness 直接调用的普通 tool。未来也可以把它暴露为 agent tool，不需要重写 parser。

## 8. Multi-Agent Boundary / 多 Agent 边界

Do not add multiple agents only because multiple API calls exist. Split agents only when responsibilities, permissions, context windows, or evaluation criteria differ meaningfully.

不要因为存在多次 API 调用就添加多个 agent。只有当职责、权限、上下文窗口或评测标准显著不同时，才拆分 agent。

Likely future roles:

未来可能的角色：

```text
research_companion
  Talks with the user and answers evidence-backed questions.

paper_processing_agent
  Runs structured extraction, summary, and translation skills.

planning_agent
  Converts research understanding into reading, reproduction, and experiment plans.

coding_agent
  Uses code tools inside an explicitly permitted workspace.

review_agent
  Checks claims, citations, uncertainty, and missing evidence.
```

An orchestrator or deterministic harness should decide the default workflow. The LLM should not be responsible for every operational decision.

默认工作流应该由 orchestrator 或确定性 harness 决定。不能把所有运行决策都交给 LLM。

## 9. Roadmap / 路线图

### Phase 0: Reliability Baseline / 可靠性基线

Goal: make current scan and extract behavior dependable.

目标：让现有 scan 和 extract 可靠。

Work:

- Add schema validation for `odracir_index.json`.
- Move common timestamp and path helpers into shared utilities.
- Record extraction failures with stable error fields.
- Add CLI `status` command.
- Add tests for modified PDFs, missing PDFs, empty PDFs, invalid PDFs, and duplicate names.
- Decide whether generated research artifacts should remain local-only or optionally be tracked in separate repositories.

Acceptance:

- Re-running scan and extract is idempotent.
- A failed PDF does not stop batch processing.
- Every paper has a visible processing state.
- Tests cover the most common failure modes.

验收：

- 重复运行 scan 和 extract 不会破坏已有结果。
- 单篇 PDF 失败不会中断批处理。
- 每篇论文都有明确处理状态。
- 测试覆盖常见失败模式。

### Phase 1: Normalization And Chunking / 标准化与切块

Goal: convert extracted text into traceable chunks suitable for LLM processing and retrieval.

目标：把已提取正文转化为适合 LLM 处理和检索的可追溯 chunk。

Work:

- Add parser registry instead of hard-coding PDF behavior.
- Add normalized document schema.
- Add section-aware chunking with page ranges and stable chunk IDs.
- Record token estimates and content hashes.
- Detect likely scanned PDFs and route them to `needs_ocr`.

Acceptance:

- Every chunk points back to source pages.
- Re-chunking unchanged text produces the same chunk IDs.
- Large papers can be processed incrementally.

验收：

- 每个 chunk 都可以追溯到原文页码。
- 未变化正文重复切块时产生相同 chunk ID。
- 长论文可以增量处理。

### Phase 2: Structured Summary And Selective Translation / 结构化总结与选择性翻译

Goal: use DeepSeek through a provider adapter to create evidence-aware paper records.

目标：通过 provider adapter 调用 DeepSeek，生成注重证据的论文记录。

Work:

- Add `providers/base.py` and `providers/deepseek.py`.
- Define generic summary schema plus domain extension hooks.
- Add map-reduce summarization over chunks.
- Require citations for extracted claims.
- Add selective translation for abstract, methods, conclusion, and chosen passages.
- Record prompt version, model, provider, cost-related usage if available, and input hashes.

Acceptance:

- A summary is reproducible from artifacts and prompt version.
- Claims include citations or are marked as inference.
- A changed source file invalidates downstream summaries.

验收：

- 可以从 artifact 和 prompt 版本复现总结。
- 结论带引用，或明确标记为推断。
- 原文变化会使下游总结失效。

### Phase 3: Retrieval And Evidence-Backed Conversation / 检索与带证据交流

Goal: answer questions across papers without loading all text into one prompt.

目标：无需把全部正文塞入单一 prompt，也能跨论文回答问题。

Work:

- Start with lexical retrieval over chunk text.
- Add optional embeddings behind a retrieval interface.
- Add citation rendering.
- Add a retrieval-first `odracir ask` harness with inspectable dry runs.
- Add project-level comparison and synthesis commands.
- Add a `research_companion` agent using retrieval as an agent tool.

Acceptance:

- Answers cite paper and page/chunk evidence.
- Retrieval can be inspected independently from the final answer.
- Missing evidence is reported honestly.

验收：

- 回答引用论文和页码/chunk 证据。
- 检索结果可以独立检查。
- 缺少证据时明确说明。

### Phase 4: Skills And Evaluation / Skill 与评测

Goal: support multiple disciplines without polluting the generic core.

目标：在不污染通用核心的前提下支持多学科。

Work:

- Add skill manifests with name, version, instructions, schema extensions, tool bindings, and evaluation rules.
- Implement `biomedical-paper-skill` first.
- Add summary quality fixtures from a small manually reviewed paper set.
- Evaluate evidence coverage, unsupported claims, missing limitations, and field completeness.

Acceptance:

- Skills can be enabled per project.
- Generic records still work without a domain skill.
- Biomedical extension improves extraction quality on reviewed examples.

验收：

- 每个项目可以单独启用 skill。
- 不启用领域 skill 时，通用记录仍然有效。
- 生物医学扩展在人工审阅样例上提升提取质量。

### Phase 5: Multi-Agent And Application Surface / 多 Agent 与应用界面

Goal: add richer workflows only after artifacts, schemas, and evaluation are stable.

目标：只有在 artifact、schema 和评测稳定后，才增加复杂工作流。

Work:

- Add explicit agent role registry.
- Add permission boundaries for code execution and file writes.
- Add job queue and progress tracking.
- Add FastAPI backend.
- Add a web UI for upload, status, summaries, citations, and conversation.
- Add SQLite first; migrate to PostgreSQL only if multi-user or server deployment requires it.

Acceptance:

- The CLI and web UI use the same harness APIs.
- Long tasks expose progress and can resume.
- Agent actions are logged and permission-checked.

验收：

- CLI 和网页界面共用同一套 harness API。
- 长任务可查看进度并恢复。
- Agent 动作有日志且经过权限检查。

## 10. Immediate Next Sprint / 下一轮立即执行内容

The next implementation sprint should remain narrow:

下一轮实现应该保持聚焦：

1. Add typed schemas for project, paper, extraction status, and chunk artifacts.
2. Add `odracir status <research-folder>`.
3. Add deterministic section-aware chunking and `odracir chunk <research-folder>`.
4. Add OCR detection reporting without implementing OCR execution yet.
5. Add failure-mode tests and update docs.

1. 为项目、论文、提取状态和 chunk artifact 添加类型化 schema。
2. 添加 `odracir status <research-folder>`。
3. 添加确定性的章节感知 chunking 和 `odracir chunk <research-folder>`。
4. 添加 OCR 检测报告，暂时不实现 OCR 执行。
5. 添加失败模式测试并更新文档。

This sprint creates the contract needed before DeepSeek-based summaries are added.

这一轮会建立接入 DeepSeek 总结之前所需的数据契约。

## 11. Implementation Progress / 实现进度

Completed on 2026-05-30:

已于 2026-05-30 完成：

- Added typed index, paper, extraction, text artifact, and chunk artifact schemas.
- Added `odracir status <research-folder>` with OCR and failure reporting.
- Added deterministic page-traceable chunking and `odracir chunk <research-folder>`.
- Added source-change invalidation for extraction, chunking, summary, and translation states.
- Added a replaceable parser registry with `pymupdf` as the first backend.
- Added failure-mode tests for scanned PDFs, invalid PDFs, schema violations, source changes, and stable chunk IDs.
- Added inspectable lexical retrieval over chunks and exposed it as `search_research_chunks`.
- Added a DeepSeek provider adapter and evidence-aware map-reduce summary harness.
- Added summary input hashes, provider/model/prompt metadata, usage recording, and source-chunk citation allowlisting.
- Added an optional Docling parser adapter that preserves normalized page-level artifacts.
- Added OCRmyPDF capability detection and explicit `.odracir/ocr/` derivative preprocessing.
- Added extraction provenance so parser changes and OCR-derived inputs invalidate stale caches.
- Added explicit selective translation over traceable chunks with citations, selection hashes, and usage metadata.
- Decoupled summary and translation invalidation while keeping both parallel derivatives of chunk artifacts.
- Added no-cost translation dry runs and conservative heading-aware chunk selection.
- Added retrieval-first `odracir ask`, inspectable no-cost dry runs, answer artifacts, and lazy provider creation.
- Added answer context limits, cache revalidation, and citation allowlisting for structured claims and inline answer citations.
- Added an optional PyMuPDF4LLM adapter for layout-aware page-level Markdown extraction while keeping OCR explicit.
- Added read-only `odracir benchmark-parsers` so parser tradeoffs can be measured without modifying research artifacts.

- 添加索引、论文、提取、正文 artifact 和 chunk artifact 的类型化 schema。
- 添加带 OCR 与失败报告的 `odracir status <research-folder>`。
- 添加确定性的按页可追溯 chunking 和 `odracir chunk <research-folder>`。
- 添加源文件变化后对提取、chunking、摘要和翻译状态的失效传播。
- 添加可替换解析器注册表，并将 `pymupdf` 作为首个后端。
- 添加扫描件、损坏 PDF、schema 违规、源文件变化和稳定 chunk ID 的失败模式测试。
- 添加可独立检查的 chunk 关键词检索，并将其暴露为 `search_research_chunks`。
- 添加 DeepSeek provider adapter 和注重证据的 map-reduce 摘要 harness。
- 添加摘要输入 hash、provider/模型/prompt 元数据、用量记录和源 chunk 引用白名单校验。
- 添加可选 Docling parser adapter，并保持标准化按页 artifact。
- 添加 OCRmyPDF 能力检测和显式 `.odracir/ocr/` derivative 预处理。
- 添加提取 provenance，使 parser 变化和 OCR derivative 输入能够使旧缓存失效。
- 添加基于可追溯 chunk 的显式选择性翻译，记录引用、选择 hash 和用量元数据。
- 将摘要与翻译失效传播解耦，同时保持二者都是 chunk artifact 的并行派生物。
- 添加无费用翻译 dry-run 和保守的章节标题感知 chunk 选择。
- 添加检索优先的 `odracir ask`、可检查的无费用 dry-run、问答 artifact 和 provider 懒加载。
- 添加问答上下文上限、缓存重新校验，以及对结构化 claims 和正文内联引用的白名单校验。
- 添加可选 PyMuPDF4LLM adapter，用于版式感知的按页 Markdown 提取，同时保持 OCR 路径显式可审计。
- 添加只读 `odracir benchmark-parsers`，用于在不修改科研 artifact 的情况下测量 parser 差异。

## 12. External Parser Strategy / 外部解析器策略

Odracir should reuse mature open-source parsers behind adapters. The normalized artifact schema remains the contract consumed by chunking, retrieval, skills, and agents.

Odracir 应该通过适配器复用成熟开源解析器。Chunking、检索、skill 和 agent 继续消费统一 artifact schema，不直接依赖特定解析器格式。

```text
source document
-> parser registry
   -> pymupdf: lightweight default
   -> docling: optional complex-layout PDF adapter
   -> ocrmypdf: explicit derivative preprocessing route for needs_ocr
   -> pymupdf4llm: optional layout-aware Markdown adapter with read-only benchmarks
   -> grobid: planned scholarly metadata service
   -> mineru: optional heavier parsing service for benchmark cases
   -> marker: optional rich conversion benchmark with licensing review
   -> unstructured: future multi-format ETL candidate
-> normalized local artifact
-> stable traceable chunks
```

Next implementation sprint:

下一轮实现：

1. Install the optional Docling adapter and benchmark it against `pymupdf` on selected complex-layout papers.
2. Install OCRmyPDF system dependencies and validate the explicit OCR route on a scanned PDF fixture.
3. Review PyMuPDF4LLM output quality on representative complex-layout papers and define selective routing rules.
4. Benchmark DeepSeek summaries, selective translations, and cited answers on selected papers before folder-wide runs.
5. Add GROBID as a service adapter when scholarly metadata and citation graphs become the next concrete need.
6. Extend lexical retrieval with optional embeddings only after benchmark evidence justifies them.

1. 安装可选 Docling adapter，并在选定复杂版式论文上与 `pymupdf` 对比。
2. 安装 OCRmyPDF 系统依赖，并在扫描版 PDF fixture 上验证显式 OCR 路径。
3. 人工审阅代表性复杂版式论文的 PyMuPDF4LLM 输出质量，并定义选择性路由规则。
4. 在选定论文上评估 DeepSeek 摘要、选择性翻译和带引用问答，再考虑整文件夹运行。
5. 当学术元数据和引用图谱成为下一项明确需求时，将 GROBID 作为服务 adapter 接入。
6. 先评估关键词检索效果；只有基准证据证明有必要时，再增加可选 embedding。
