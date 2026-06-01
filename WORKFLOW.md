# Odracir Workflow / 工作流

This document records how Odracir should run today and how its modules should grow.

本文档记录 Odracir 当前应该如何运行，以及后续模块应该如何扩展。

## Current Workflow / 当前工作流

The current local workflow is:

```text
research folder
-> scan paper storage
-> update odracir_index.json
-> optionally cache advisory parser-routing recommendations
-> write .odracir/parser-routing/*.json
-> extract PDF page text
-> write .odracir/texts/*.json
-> report extraction state and likely OCR needs
-> optionally create .odracir/ocr/*.pdf derivatives with OCRmyPDF
-> re-extract from current OCR derivatives
-> create stable page-traceable chunks
-> write .odracir/chunks/*.json
-> search chunks with paper/page citations
-> preview or answer folder-level questions from retrieved evidence
-> write .odracir/answers/*.json
-> ingest each ordinary paper through one versioned structured DeepSeek request
-> transparently fall back to map-reduce only when required
-> write .odracir/summaries/*.json
-> locally audit summary evidence quality
-> write .odracir/evaluations/summaries/*.json
-> explicitly translate selected chunks through DeepSeek
-> write .odracir/translations/*.json
-> rebuild the visible audited research_catalog.json
-> later: chat, plan, code
```

当前本地工作流是：

```text
研究文件夹
-> 扫描论文存储目录
-> 更新 odracir_index.json
-> 可选：缓存 parser 路由审阅建议
-> 写入 .odracir/parser-routing/*.json
-> 提取 PDF 按页正文
-> 写入 .odracir/texts/*.json
-> 报告提取状态和可能需要 OCR 的文件
-> 可选：使用 OCRmyPDF 创建 .odracir/ocr/*.pdf derivative
-> 从当前 OCR derivative 重新提取正文
-> 创建稳定、按页可追溯的 chunk
-> 写入 .odracir/chunks/*.json
-> 检索 chunk，并返回论文与页码引用
-> 根据检索证据预览或回答文件夹级问题
-> 写入 .odracir/answers/*.json
-> 通过一次版本化结构化 DeepSeek 请求摄取每篇普通论文
-> 仅在必要时透明降级为 map-reduce
-> 写入 .odracir/summaries/*.json
-> 在本地审计摘要证据质量
-> 写入 .odracir/evaluations/summaries/*.json
-> 通过 DeepSeek 显式翻译选定 chunk
-> 写入 .odracir/translations/*.json
-> 重建可见且经过审计的 research_catalog.json
-> 后续：交流、规划、代码实现
```

## Commands / 命令

Ingest one paper library, audit summaries, and refresh its visible root state:

```powershell
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic --dry-run
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic
```

摄取一个论文库、审计摘要，并刷新其根目录下的可见 state：

```powershell
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic --dry-run
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic
```

`ingest-library` is the primary resumable library entry point. Ordinary papers
use one versioned structured DeepSeek call. Oversized papers and single-pass
structured-output validation failures transparently fall back to map-reduce.
Every strategy, request count, input size, and fallback reason is preserved in
provenance. Each run also writes a compact audit record under
`.odracir/jobs/ingestion/` and refreshes `latest.json`.

`ingest-library` 是论文库默认的可恢复入口。普通论文使用一次版本化结构化
DeepSeek 调用；超长论文和 single-pass 结构化输出校验失败项会透明降级为
map-reduce。策略、请求次数、输入规模和 fallback 原因都会保留在 provenance
中。每次运行还会在 `.odracir/jobs/ingestion/` 下写入紧凑审计记录，并刷新
`latest.json`。

Prepare searchable local artifacts and rebuild folder memory without API usage:

```powershell
odracir prepare <research-folder> --papers-dir <paper-folder>
```

在无 API 用量的情况下准备可检索本地 artifact 并重建文件夹记忆：

```powershell
odracir prepare <research-folder> --papers-dir <paper-folder>
```

`prepare` is the resumable default local entry point. It runs scan, PDF extraction, chunking, catalog rebuilding, and final status reporting. Current extraction and chunk artifacts are skipped. It intentionally does not run OCRmyPDF, DeepSeek summaries, translations, or answers.

`prepare` 是默认的可恢复本地入口。它会依次执行扫描、PDF 正文提取、切块、catalog 重建和最终状态报告。仍然有效的 extraction 和 chunk artifact 会被跳过。它刻意不会运行 OCRmyPDF、DeepSeek 摘要、翻译或问答。

Scan a research folder with the default `papers/` directory:

```powershell
odracir scan <research-folder>
```

扫描默认 `papers/` 目录：

```powershell
odracir scan <research-folder>
```

Scan an existing paper storage directory:

```powershell
odracir scan <research-folder> --papers-dir <paper-folder>
```

扫描已有论文存储目录：

```powershell
odracir scan <research-folder> --papers-dir <paper-folder>
```

Extract PDF text:

```powershell
odracir extract <research-folder> --papers-dir <paper-folder>
```

提取 PDF 正文：

```powershell
odracir extract <research-folder> --papers-dir <paper-folder>
```

Inspect optional document tools:

```powershell
odracir capabilities
```

检查可选文档工具：

```powershell
odracir capabilities
```

Use the optional Docling backend for complex layouts:

```powershell
pip install -e ".[docling]"
odracir extract <research-folder> --paper <paper-id> --parser docling --force
```

为复杂版式使用可选 Docling 后端：

```powershell
pip install -e ".[docling]"
odracir extract <research-folder> --paper <paper-id> --parser docling --force
```

Compare the default parser with the optional layout-aware PyMuPDF4LLM adapter without changing extraction artifacts or index state:

```powershell
pip install -e ".[pymupdf4llm]"
odracir benchmark-parsers <research-folder> --papers-dir <paper-folder> --limit 1
```

在不修改 extraction artifact 或索引状态的情况下，将默认 parser 与可选版式感知 PyMuPDF4LLM adapter 进行比较：

```powershell
pip install -e ".[pymupdf4llm]"
odracir benchmark-parsers <research-folder> --papers-dir <paper-folder> --limit 1
```

Cache conservative parser review recommendations without modifying extraction artifacts:

```powershell
odracir recommend-parsers <research-folder> --papers-dir <paper-folder>
```

在不修改 extraction artifact 的情况下，缓存保守的 parser 审阅建议：

```powershell
odracir recommend-parsers <research-folder> --papers-dir <paper-folder>
```

The advisory policy keeps `pymupdf` selected by default. A paper becomes a `review_candidate` only when `pymupdf4llm` adds at least 1,000 characters and at least 3% more text. The result is cached under `.odracir/parser-routing/`; source PDF changes, parser package upgrades, or policy changes invalidate the cache.

建议策略默认继续选择 `pymupdf`。只有当 `pymupdf4llm` 至少多提取 1,000 个字符且文本增幅至少达到 3% 时，论文才会成为 `review_candidate`。结果会缓存到 `.odracir/parser-routing/`；源 PDF 变化、parser 包升级或策略变化都会使缓存失效。

After reviewing representative outputs, selectively extract with the layout-aware backend:

```powershell
odracir extract <research-folder> --paper <paper-id> --parser pymupdf4llm --force
```

Create OCR derivatives for papers reported as `needs_ocr`:

```powershell
pip install -e ".[ocr]"
odracir ocr <research-folder> --papers-dir <paper-folder> --language eng
odracir extract <research-folder> --papers-dir <paper-folder>
```

为报告为 `needs_ocr` 的论文创建 OCR derivative：

```powershell
pip install -e ".[ocr]"
odracir ocr <research-folder> --papers-dir <paper-folder> --language eng
odracir extract <research-folder> --papers-dir <paper-folder>
```

OCRmyPDF also needs its documented system dependencies. Odracir writes derivatives under `.odracir/ocr/`, preserves source PDFs, and automatically uses current derivatives on the next extraction run.

OCRmyPDF 还需要其文档中说明的系统依赖。Odracir 将 derivative 写入 `.odracir/ocr/`，保留原始 PDF，并在下一次提取时自动使用当前 derivative。

Inspect processing status:

```powershell
odracir status <research-folder> --papers-dir <paper-folder>
```

检查处理状态：

```powershell
odracir status <research-folder> --papers-dir <paper-folder>
```

Chunk extracted text:

```powershell
odracir chunk <research-folder> --papers-dir <paper-folder>
```

切分已提取正文：

```powershell
odracir chunk <research-folder> --papers-dir <paper-folder>
```

Search traceable chunks:

```powershell
odracir search <research-folder> "<query>" --limit 5
```

Preview evidence for a folder-level question without API usage:

```powershell
odracir ask <research-folder> "<question>" --query "<focused retrieval query>" --dry-run
```

基于文件夹级问题预览证据，不产生 API 用量：

```powershell
odracir ask <research-folder> "<question>" --query "<focused retrieval query>" --dry-run
```

Answer from retrieved evidence through DeepSeek:

```powershell
odracir ask <research-folder> "<question>" --query "<focused retrieval query>"
```

`ask` uses ranked local chunks only, validates citations against that evidence set, and writes reproducible artifacts under `.odracir/answers/`. When no evidence matches, it does not create a provider or call DeepSeek.

`ask` 只使用排序后的本地 chunk，根据该证据集合校验引用，并在 `.odracir/answers/` 下写入可复现 artifact。没有匹配证据时，它不会创建 provider，也不会调用 DeepSeek。

Generate an evidence-aware summary for a chosen paper:

```powershell
odracir summarize <research-folder> --papers-dir <paper-folder> --paper <paper-id>
```

为选定论文生成注重证据的摘要：

```powershell
odracir summarize <research-folder> --papers-dir <paper-folder> --paper <paper-id>
```

`summarize` calls DeepSeek and consumes API usage. Use `--paper` or `--limit` for supervised runs before processing a whole folder.

`summarize` 会调用 DeepSeek 并产生 API 用量。批量处理前，请使用 `--paper` 或 `--limit` 进行受控运行。

Inspect built-in research skills and preview biomedical summary scope without API usage:

```powershell
odracir skills
odracir skills biomedical-paper
odracir summarize <research-folder> --papers-dir <paper-folder> --skill biomedical-paper --dry-run
odracir evaluate-summaries <research-folder> --papers-dir <paper-folder> --skill biomedical-paper
odracir build-memory <research-folder> --papers-dir <paper-folder>
```

检查内置科研 skill，并在无 API 用量的情况下预览生物医学摘要范围：

```powershell
odracir skills
odracir skills biomedical-paper
odracir summarize <research-folder> --papers-dir <paper-folder> --skill biomedical-paper --dry-run
odracir evaluate-summaries <research-folder> --papers-dir <paper-folder> --skill biomedical-paper
odracir build-memory <research-folder> --papers-dir <paper-folder>
```

`generic` remains the default cross-disciplinary skill. `biomedical-paper` is the first domain manifest. It adds versioned summary instructions, a biomedical schema extension, tool bindings, and evaluation rules. Each biomedical field item must carry source citations or set `inference=true`. Executed summaries store the chosen skill name and version; switching skills invalidates stale summary caches.

`generic` 仍然是默认跨学科 skill。`biomedical-paper` 是首个领域 manifest。它添加版本化摘要说明、生物医学 schema 扩展、工具绑定和评测规则。每一个生物医学字段条目都必须携带来源引用，或者设置 `inference=true`。实际执行摘要会保存所选 skill 名称和版本；切换 skill 会使旧摘要缓存失效。

`evaluate-summaries` is a deterministic local audit. It does not call DeepSeek or modify the index. It checks missing and stale artifacts, citation validity against current chunks, skill-version provenance, findings, limitations, and populated domain fields. Cached reports are written under `.odracir/evaluations/summaries/`. Use `--no-write` when only an ephemeral report is needed.

`evaluate-summaries` 是确定性的本地审计工具。它不会调用 DeepSeek，也不会修改索引。它会检查缺失和过期 artifact、当前 chunks 上的引用有效性、skill 版本 provenance、findings、limitations 和已填充领域字段。带缓存的报告写入 `.odracir/evaluations/summaries/`。只需要临时报告时，可以使用 `--no-write`。

`build-memory` is a deterministic local catalog builder. It does not call DeepSeek or modify the compact index. It writes `research_catalog.json` at the research-folder root and aggregates processing states, artifact paths, audited summaries, skill provenance, warnings, and failures. Missing or failed summaries remain explicit. Use `--no-write` for an ephemeral report; the `get_research_memory` agent tool uses this read-only path.

`build-memory` 是确定性的本地目录构建器。它不会调用 DeepSeek，也不会修改精简索引。它会在研究文件夹根目录写入 `research_catalog.json`，聚合处理状态、artifact 路径、经过审计的摘要、skill provenance、warning 和失败原因。缺失或失败的摘要仍保持显式状态。使用 `--no-write` 可以只生成临时报告；`get_research_memory` agent tool 使用的就是这条只读路径。

Translate the default abstract, methods, and conclusion selection:

```powershell
odracir translate <research-folder> --papers-dir <paper-folder> --paper <paper-id>
```

翻译默认选择的摘要、方法和结论：

```powershell
odracir translate <research-folder> --papers-dir <paper-folder> --paper <paper-id>
```

Preview the selected citations without API usage:

```powershell
odracir translate <research-folder> --papers-dir <paper-folder> --paper <paper-id> --dry-run
```

在无 API 用量的情况下预览选定引用：

```powershell
odracir translate <research-folder> --papers-dir <paper-folder> --paper <paper-id> --dry-run
```

The default selective route translates at most 8 chunks. Repeat `--section` or `--chunk` for precise selection. Use `--all-chunks` only when a full-paper translation is intentional. Like `summarize`, `translate` explicitly calls DeepSeek and consumes API usage.

默认选择性路径最多翻译 8 个 chunk。可以重复使用 `--section` 或 `--chunk` 进行精确选择。只有明确需要全文翻译时才使用 `--all-chunks`。与 `summarize` 一样，`translate` 会显式调用 DeepSeek 并产生 API 用量。

The provider adapter follows DeepSeek's official [OpenAI-compatible API](https://api-docs.deepseek.com/) and [JSON Output](https://api-docs.deepseek.com/guides/json_mode) guidance.

Provider adapter 遵循 DeepSeek 官方的 [OpenAI-compatible API](https://api-docs.deepseek.com/) 与 [JSON Output](https://api-docs.deepseek.com/guides/json_mode) 指南。

检索可追溯 chunk：

```powershell
odracir search <research-folder> "<query>" --limit 5
```

For the Medical World Model folder:

```powershell
odracir scan "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir status "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir search "D:\Research\medical-world-models" "world model" --limit 3
odracir ask "D:\Research\medical-world-models" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
```

## Artifact Layout / Artifact 布局

Odracir keeps `odracir_index.json` as the folder-level summary index. Large generated artifacts should live under `.odracir/`.

Odracir 将 `odracir_index.json` 保持为文件夹级总索引。较大的生成内容应该放在 `.odracir/` 下。

```text
research-folder/
  Paper Storage/
  notes/
  code/
  odracir_index.json
  research_catalog.json
  .odracir/
    texts/
      paper-id.json
    ocr/
      paper-id.pdf
    summaries/
    evaluations/
      summaries/
    translations/
    answers/
    chunks/
    parser-routing/
    jobs/
      ingestion/
        latest.json
        <run-id>.json
```

Ingestion run records are compact workflow provenance. They keep stage counts,
strategy and API-usage summaries, failures, and output paths without duplicating
full summary payloads.

摄取运行记录是紧凑的工作流 provenance。它保留阶段计数、策略和 API 用量汇总、
失败项与输出路径，但不会重复存储完整摘要内容。

The index should point to artifacts instead of storing full text directly.

索引应该指向 artifact 路径，而不是直接存储全文。

## Tools, Agent Tools, And Skills / Tool、Agent Tool 与 Skill

In Odracir, a `tool` can mean a normal software capability, such as a PDF parser, JSON writer, file scanner, or command-line operation.

在 Odracir 中，`tool` 可以指普通软件能力，例如 PDF 解析器、JSON 写入器、文件扫描器或命令行操作。

An `agent tool` is a tool that is exposed to an LLM agent through a tool schema. The agent can decide when to call it, with what arguments, and how to use the result.

`agent tool` 是暴露给 LLM agent 的工具，通常带有工具 schema。agent 可以决定什么时候调用它、传入什么参数、如何使用结果。

A `skill` is a higher-level reusable capability package. It can contain instructions, prompts, workflows, schemas, examples, and tool bindings for a domain.

`skill` 是更高层的可复用能力包。它可以包含说明、prompt、工作流、schema、示例，以及某个领域需要的工具绑定。

Recommended layering:

推荐分层：

```text
parser/tool: extract PDF text
agent tool: expose extract_pdf_text(folder, paper_id) to an agent
skill: biomedical paper reading workflow, including prompts, fields, evaluation rules, and tools
agent: chooses which skill/tool to use for the user's goal
harness: runs the workflow, records state, handles retries, writes artifacts
```

## Parser Backends / 解析器后端

PDF parsing is a replaceable deterministic tool. Odracir uses a parser registry, keeps `pymupdf` as the default lightweight backend, and exposes optional `pymupdf4llm` and `docling` adapters. `pymupdf4llm` adds layout-aware Markdown conversion but is intentionally selective because it is slower and carries AGPL/commercial licensing considerations. `odracir recommend-parsers` turns read-only benchmark evidence into cached advisory review candidates; it never switches extraction artifacts automatically. OCRmyPDF is an explicit preprocessor rather than a parser. Additional projects should enter through adapters or service clients only after representative benchmarks. Backends preserve the normalized artifact contract instead of leaking backend-specific formats into agents.

PDF 解析是一个可替换的确定性工具。Odracir 使用解析器注册表，将 `pymupdf` 保留为默认轻量后端，并暴露可选 `pymupdf4llm` 和 `docling` adapter。`pymupdf4llm` 增加版式感知 Markdown 转换，但由于速度更慢且存在 AGPL/商业许可证注意事项，只应选择性使用。`odracir recommend-parsers` 会把只读 benchmark 证据转化为带缓存的审阅候选，但绝不会自动切换 extraction artifact。OCRmyPDF 是显式预处理器，而不是 parser。其他项目只有在代表性样例基准证明有价值后，才应通过 adapter 或服务客户端接入。各后端遵守标准化 artifact 契约，不会让后端专属格式泄漏到 agent 中。

Recommended external projects:

推荐评估的外部项目：

- [Docling](https://github.com/docling-project/docling): integrated optional adapter for complex-layout PDFs; see its [official usage docs](https://docling-project.github.io/docling/usage/).
- [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF): integrated optional preprocessing route for PDFs reported as `needs_ocr`; see its [official cookbook](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html).
- [PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm): integrated optional layout-aware Markdown adapter with a read-only benchmark route; review its AGPL/commercial licensing before distribution.
- [GROBID](https://github.com/grobidOrg/grobid): planned service adapter for scholarly metadata, references, citation contexts, and TEI output.
- [MinerU](https://github.com/opendatalab/MinerU): heavier optional service candidate for Chinese, formula-heavy, scanned, or complex-layout documents; it supports CPU and GPU modes and uses a custom license based on Apache 2.0.
- [Marker](https://github.com/datalab-to/marker): benchmark candidate for rich Markdown/JSON conversion and scientific layouts; keep it optional because code, model, and commercial-use licensing need deliberate review.
- [Unstructured](https://github.com/Unstructured-IO/unstructured): future multi-format ETL candidate when the project expands beyond research PDFs.

## Research Skill Strategy / 科研 Skill 策略

Odracir should not make one giant prompt for every discipline. It should keep a stable core workflow and add discipline-specific skills.

Odracir 不应该为所有学科写一个巨大的 prompt。它应该保持稳定核心工作流，再增加面向学科的 skill。

Available built-in skills:

当前可用的内置 skill：

- `generic`: cross-disciplinary evidence-aware paper reading.
- `biomedical-paper`: population, intervention or exposure, comparator, outcome, mechanism, assay, clinical relevance, safety, ethics.

Possible future skills:

未来可能的 skill：

- `computer-science-paper-skill`: task, model, dataset, metric, baseline, ablation, implementation details, reproduction plan.
- `materials-science-paper-skill`: composition, synthesis, characterization, properties, mechanism, experimental conditions.
- `review-skill`: check whether summaries preserve evidence, limitations, and uncertainty.
- `coding-reproduction-skill`: turn paper records into environment setup and implementation tasks.

## Near-Term Roadmap / 近期路线图

1. Keep scan, extract, status, and chunk reliable.
2. Review cached parser-routing recommendations and representative PyMuPDF4LLM outputs before accepting per-paper overrides.
3. Benchmark and refine single-pass DeepSeek paper ingestion and its transparent fallback.
4. Benchmark selective Chinese translation on reviewed abstract, method, conclusion, and chosen-passage examples.
5. Benchmark the cited `odracir ask` route and add optional embeddings only when retrieval evidence justifies them.
6. Validate the explicit OCRmyPDF path on a scanned fixture after installing system dependencies.
7. Add a GROBID service adapter when scholarly metadata and citation graphs become the next concrete need.
8. Review biomedical summary artifacts, then add further discipline skills only when representative examples justify their schemas.

1. 先让 scan、extract、status 和 chunk 稳定。
2. 审阅缓存的 parser 路由建议和代表性 PyMuPDF4LLM 输出，再接受逐篇 parser override。
3. 对 single-pass DeepSeek 论文摄取及其透明 fallback 进行基准评估和优化。
4. 在人工审阅的摘要、方法、结论和选定段落样例上评估选择性中文翻译。
5. 评估带引用的 `odracir ask` 路径；只有检索证据证明有必要时，才添加可选 embedding。
6. 安装系统依赖后，在扫描版 fixture 上验证显式 OCRmyPDF 路径。
7. 当学术元数据和引用图谱成为明确需求时，添加 GROBID 服务 adapter。
8. 审阅生物医学摘要 artifact；只有代表性样例证明 schema 合理后，才继续添加其他学科 skill。

## Optional Explainable Reading Queue / 可选可解释阅读队列

Optionally, after local preparation, rank supervised reading actions:

可选：完成本地准备后，对受监督阅读行动排序：

```powershell
odracir plan-reading "D:\Research\medical-world-models" --papers-dir "Paper Storage" --query "medical world model clinical trajectories" --skill biomedical-paper
odracir plan-reading "D:\Research\medical-world-models" --papers-dir "Paper Storage" --query "medical world model clinical trajectories" --skill biomedical-paper --no-write
```

The planner is deterministic and makes no DeepSeek API call. It records
readiness, missing-summary state, query relevance, title-corpus centrality,
workload, traceable evidence snippets, and suggested supervised commands under
`.odracir/planning/reading-queues/`. The read-only `plan_research_reading` agent
tool exposes the same behavior without writing artifacts.

规划器是确定性的，不调用 DeepSeek API。它会把就绪状态、摘要缺失状态、查询
相关性、标题语料中心性、工作量、可追溯证据片段和建议的受监督命令记录到
`.odracir/planning/reading-queues/`。只读 `plan_research_reading` agent tool
提供相同行为，但不会写入 artifact。

## Execution Log / 执行记录

### 2026-05-30

Environment setup:

```powershell
cd D:\Projects\odracir
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

环境配置：

```powershell
cd D:\Projects\odracir
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Medical World Model extraction:

```powershell
odracir scan "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

医学世界模型论文提取：

```powershell
odracir scan "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- PDFs found: 9.
- PDFs extracted: 9.
- Failures: 0.
- Output index: `D:\Research\medical-world-models\odracir_index.json`.
- Text artifacts: `D:\Research\medical-world-models\.odracir\texts\`.

结果：

- 发现 PDF：9 篇。
- 成功提取：9 篇。
- 失败：0 篇。
- 输出索引：`D:\Research\medical-world-models\odracir_index.json`。
- 文本 artifact：`D:\Research\medical-world-models\.odracir\texts\`。

Medical World Model status and chunking validation:

```powershell
odracir status "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Medical World Model 状态与 chunking 验证：

```powershell
odracir status "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- Status before chunking: 9 extracted PDFs, 9 with `chunking_status=not_started`, 0 OCR needs, 0 failures.
- First chunk run: 9 chunked, 0 blocked, 0 failures.
- Second chunk run: 0 regenerated, 9 skipped.
- Status after chunking: 9 extracted PDFs and 9 chunked PDFs.
- Chunk artifacts: `D:\Research\medical-world-models\.odracir\chunks\`.
- Chunk count: 128 total chunks, with 6 to 23 chunks per paper.

结果：

- Chunking 前状态：9 篇 PDF 已提取，9 篇为 `chunking_status=not_started`，0 篇需要 OCR，0 篇失败。
- 第一次 chunk：9 篇完成，0 篇阻塞，0 篇失败。
- 第二次 chunk：0 篇重复生成，9 篇跳过。
- Chunking 后状态：9 篇 PDF 已提取，9 篇 PDF 已完成 chunking。
- Chunk artifact：`D:\Research\medical-world-models\.odracir\chunks\`。
- Chunk 数量：共 128 个，每篇论文包含 6 至 23 个 chunk。

Medical World Model lexical retrieval validation:

```powershell
odracir search "D:\Research\medical-world-models" "world model" --limit 3
odracir search "D:\Research\medical-world-models" clinical --limit 3 --json
```

Medical World Model 关键词检索验证：

```powershell
odracir search "D:\Research\medical-world-models" "world model" --limit 3
odracir search "D:\Research\medical-world-models" clinical --limit 3 --json
```

Result:

- Searched 9 papers and 128 chunks.
- `world model` returned page-level citations from EHRWorld.
- `clinical` returned page-level citations from ClinAgent.
- The same retrieval function is exposed to the LLM as `search_research_chunks`.

结果：

- 共检索 9 篇论文和 128 个 chunk。
- `world model` 返回了 EHRWorld 的页码级引用。
- `clinical` 返回了 ClinAgent 的页码级引用。
- 同一个检索函数已作为 `search_research_chunks` 暴露给 LLM。

Medical World Model summary readiness check:

- Status reports `summaries: not_started=9`.
- `odracir summarize` was not run automatically because it calls DeepSeek and consumes API usage.

Medical World Model 摘要就绪检查：

- 状态报告显示 `summaries: not_started=9`。
- 未自动运行 `odracir summarize`，因为它会调用 DeepSeek 并产生 API 用量。

### 2026-05-31

Optional document-tool adapter migration:

```powershell
odracir capabilities
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

可选文档工具 adapter 迁移：

```powershell
odracir capabilities
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- Added the optional `docling` backend and explicit OCRmyPDF derivative route.
- Local capability check reports `pymupdf=available`, `docling=unavailable`, and `ocrmypdf=unavailable` before optional installation.
- Provenance migration re-extracted 9 PDFs once; the next extraction run skipped all 9.
- Provenance migration re-chunked 9 PDFs once; the next chunk run skipped all 9.
- Final status: 9 extracted PDFs, 9 chunked PDFs, 0 OCR needs, 0 failures, and 128 chunks.
- DeepSeek summary execution remained intentionally disabled during this no-cost migration.
- Selective translation readiness reports `translations: not_started=9`.
- DeepSeek translation execution remained intentionally disabled during this no-cost migration.
- `odracir translate ... --dry-run` reports 9 ready papers, 0 blocked papers, 0 failures, and 12 conservatively selected chunks.
- The default selector keeps the first abstract-oriented chunk and only adds method or conclusion chunks when heading context is credible. Use `--chunk` for deliberate additions.

结果：

- 添加可选 `docling` 后端和显式 OCRmyPDF derivative 路径。
- 在可选安装前，本机能力检查报告 `pymupdf=available`、`docling=unavailable` 和 `ocrmypdf=unavailable`。
- Provenance 迁移首次重新提取 9 篇 PDF；下一次提取全部跳过。
- Provenance 迁移首次重新 chunk 9 篇 PDF；下一次 chunk 全部跳过。
- 最终状态：9 篇 PDF 已提取、9 篇 PDF 已 chunk、0 篇需要 OCR、0 篇失败，共 128 个 chunk。
- 此次无费用迁移期间仍然刻意不运行 DeepSeek 摘要。
- 选择性翻译就绪状态为 `translations: not_started=9`。
- 此次无费用迁移期间仍然刻意不运行 DeepSeek 翻译。
- `odracir translate ... --dry-run` 报告 9 篇论文 ready、0 篇阻塞、0 篇失败，并保守选择 12 个 chunks。
- 默认选择器保留面向摘要的首页 chunk；只有章节标题上下文可信时才增加方法或结论 chunk。需要补充时，请显式使用 `--chunk`。

Evidence-backed question and parser-candidate check:

```powershell
odracir ask "D:\Research\medical-world-models" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
```

带证据问答与解析器候选检查：

```powershell
odracir ask "D:\Research\medical-world-models" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
```

Result:

- Added retrieval-first `odracir ask`, a no-cost dry-run, answer artifacts, cache validation, context limits, and citation allowlisting.
- The real-folder dry-run searched 9 papers and 128 chunks, then selected 4 evidence chunks containing 20,220 characters without calling DeepSeek.
- Reviewed official GitHub repositories for Docling, PyMuPDF4LLM, OCRmyPDF, GROBID, MinerU, Marker, and Unstructured.
- Kept the next parser move narrow: benchmark a PyMuPDF4LLM adapter spike before adding heavier service integrations.

结果：

- 添加检索优先的 `odracir ask`、无费用 dry-run、问答 artifact、缓存校验、上下文上限和引用白名单。
- 真实文件夹 dry-run 检索了 9 篇论文和 128 个 chunk，选择 4 个证据 chunk，共 20,220 个字符，未调用 DeepSeek。
- 检查 Docling、PyMuPDF4LLM、OCRmyPDF、GROBID、MinerU、Marker 和 Unstructured 的官方 GitHub 仓库。
- 下一步解析器演进保持聚焦：先评估 PyMuPDF4LLM adapter spike，再决定是否加入更重的服务集成。

PyMuPDF4LLM adapter and read-only parser benchmark:

```powershell
pip install -e ".[pymupdf4llm]"
odracir capabilities
odracir benchmark-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage" --parser pymupdf --parser pymupdf4llm
```

PyMuPDF4LLM adapter 与只读 parser benchmark：

```powershell
pip install -e ".[pymupdf4llm]"
odracir capabilities
odracir benchmark-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage" --parser pymupdf --parser pymupdf4llm
```

Result:

- Added optional `pymupdf4llm` parser registration, capability detection, and normalized page-level Markdown artifacts.
- Disabled PyMuPDF4LLM implicit OCR so Odracir keeps its explicit OCRmyPDF derivative route auditable.
- Added read-only `odracir benchmark-parsers`; it does not overwrite extraction artifacts or index state.
- Real-folder comparison: both parsers succeeded on 9/9 papers.
- `pymupdf`: 1.611 seconds total, 595,281 extracted characters.
- `pymupdf4llm`: 139.505 seconds total, 629,117 extracted characters.
- PyMuPDF4LLM extracted 33,836 more characters but was substantially slower, so it remains a selective backend.
- The `odracir_index.json` SHA-256 remained identical before and after the benchmark.

结果：

- 添加可选 `pymupdf4llm` parser 注册、能力检测和标准化按页 Markdown artifact。
- 禁用 PyMuPDF4LLM 隐式 OCR，使 Odracir 继续保持显式、可审计的 OCRmyPDF derivative 路径。
- 添加只读 `odracir benchmark-parsers`；它不会覆盖 extraction artifact 或索引状态。
- 真实目录比较：两个 parser 均成功处理 9/9 篇论文。
- `pymupdf`：总耗时 1.611 秒，提取 595,281 个字符。
- `pymupdf4llm`：总耗时 139.505 秒，提取 629,117 个字符。
- PyMuPDF4LLM 多提取 33,836 个字符，但明显更慢，因此继续作为选择性后端。
- benchmark 前后 `odracir_index.json` 的 SHA-256 完全一致。

Cached advisory parser routing:

```powershell
odracir recommend-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir recommend-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

带缓存的建议式 parser 路由：

```powershell
odracir recommend-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir recommend-parsers "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- Added cached, advisory `odracir recommend-parsers` without automatic extraction mutation.
- The conservative policy marks a paper for review only when `pymupdf4llm` adds at least 1,000 characters and at least 3% more text.
- Real-folder recommendations: 8 `review_candidate`, 1 `keep_baseline`.
- `medos-ai-xr-cobot-world-model-for-clinical-perception-and-action` stayed on `pymupdf` because the candidate added only 147 characters, or 0.34%.
- The second run hit the cache and completed in approximately 0.85 seconds.
- The recommendation artifact was written to `.odracir/parser-routing/2d1c6407b8199c2995e6.json`.
- The `odracir_index.json` SHA-256 remained identical before and after recommendation generation.
- No DeepSeek API call was made.

结果：

- 添加带缓存、建议式的 `odracir recommend-parsers`，不会自动修改 extraction artifact。
- 保守策略只有在 `pymupdf4llm` 至少多提取 1,000 个字符且文本增幅至少达到 3% 时，才将论文标记为待审阅。
- 真实目录建议：8 篇 `review_candidate`，1 篇 `keep_baseline`。
- `medos-ai-xr-cobot-world-model-for-clinical-perception-and-action` 继续使用 `pymupdf`，因为候选后端只增加 147 个字符，即 0.34%。
- 第二次运行命中缓存，约 0.85 秒完成。
- 推荐 artifact 写入 `.odracir/parser-routing/2d1c6407b8199c2995e6.json`。
- 生成推荐前后，`odracir_index.json` 的 SHA-256 完全一致。
- 未调用 DeepSeek API。

Versioned biomedical research skill and summary dry run:

```powershell
odracir skills
odracir skills biomedical-paper
odracir summarize "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper --dry-run
```

版本化生物医学科研 skill 与摘要 dry-run：

```powershell
odracir skills
odracir skills biomedical-paper
odracir summarize "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper --dry-run
```

Result:

- Added a versioned research-skill registry with `generic@0.1` and `biomedical-paper@0.1`.
- Added `odracir skills [name]` and the read-only `list_research_skills` agent tool.
- Added `odracir summarize --skill biomedical-paper --dry-run` without API configuration loading or DeepSeek usage.
- Biomedical summaries require citation-backed or explicitly inferred items for population, intervention or exposure, comparator, outcomes, mechanisms, assays or measurements, clinical relevance, and safety or ethics.
- Executed summary artifacts record the selected skill manifest; skill or skill-version changes invalidate stale summary caches.
- Real-folder dry run: 9 ready papers, 0 blocked, 0 failed, and 128 chunks.
- No DeepSeek API call was made.

结果：

- 添加版本化科研 skill registry，包含 `generic@0.1` 和 `biomedical-paper@0.1`。
- 添加 `odracir skills [name]` 和只读 `list_research_skills` agent tool。
- 添加 `odracir summarize --skill biomedical-paper --dry-run`，无需读取 API 配置，也不会调用 DeepSeek。
- 生物医学摘要要求研究人群、干预或暴露、对照、结局、机制、assay 或测量、临床相关性、安全或伦理等条目带引用，或者显式标记为推断。
- 实际执行的 summary artifact 会记录所选 skill manifest；skill 或 skill 版本变化会使旧摘要缓存失效。
- 真实目录 dry-run：9 篇 ready、0 篇 blocked、0 篇 failed，共 128 个 chunks。
- 未调用 DeepSeek API。

Deterministic local summary evaluation:

```powershell
odracir evaluate-summaries "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper
odracir evaluate-summaries "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper
```

确定性本地摘要评测：

```powershell
odracir evaluate-summaries "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper
odracir evaluate-summaries "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper
```

Result:

- Added deterministic `odracir evaluate-summaries` and the read-only `evaluate_research_summaries` agent tool.
- Real-folder audit: 9 `missing_summary`, matching the intentionally deferred paid-summary state.
- The second evaluation run loaded the cached report.
- The report was written to `.odracir/evaluations/summaries/bfc89a4fbb0c141e3dd0.json`.
- The `odracir_index.json` SHA-256 remained identical before and after evaluation.
- No DeepSeek API call was made.

结果：

- 添加确定性 `odracir evaluate-summaries` 和只读 `evaluate_research_summaries` agent tool。
- 真实目录审计：9 篇 `missing_summary`，与刻意暂缓付费摘要的状态一致。
- 第二次评测运行读取了缓存报告。
- 报告写入 `.odracir/evaluations/summaries/bfc89a4fbb0c141e3dd0.json`。
- 评测前后，`odracir_index.json` 的 SHA-256 完全一致。
- 未调用 DeepSeek API。

Visible audited folder memory:

```powershell
odracir build-memory "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir build-memory "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

可见且经过审计的文件夹记忆：

```powershell
odracir build-memory "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir build-memory "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- Added deterministic `odracir build-memory` and the read-only `get_research_memory` agent tool.
- Real-folder catalog: 9 papers with explicit `missing_summary` state, matching the intentionally deferred paid-summary state.
- The catalog was written to `research_catalog.json` at the research-folder root.
- The second build loaded the cached catalog.
- The `odracir_index.json` SHA-256 remained `471A28AD6F08530CF5F3B289B8BF24F81DFD69C34DB45BC252F76CFA8AB8921F` before and after both builds.
- No DeepSeek API call was made.

结果：

- 添加确定性 `odracir build-memory` 和只读 `get_research_memory` agent tool。
- 真实目录 catalog：9 篇论文均为显式 `missing_summary` 状态，与刻意暂缓付费摘要的状态一致。
- catalog 已写入研究文件夹根目录的 `research_catalog.json`。
- 第二次构建读取了缓存 catalog。
- 两次构建前后，`odracir_index.json` 的 SHA-256 始终为 `471A28AD6F08530CF5F3B289B8BF24F81DFD69C34DB45BC252F76CFA8AB8921F`。
- 未调用 DeepSeek API。

Resumable zero-API local preparation:

```powershell
odracir prepare "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir prepare "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

可恢复、零 API 的本地准备流水线：

```powershell
odracir prepare "D:\Research\medical-world-models" --papers-dir "Paper Storage"
odracir prepare "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Result:

- Added `LocalPreparationHarness` and `odracir prepare`.
- Real-folder scan: 9 papers, 0 new, 0 updated, 0 missing.
- Both runs skipped all 9 current extraction artifacts and all 9 current chunk artifacts.
- The first run rebuilt `research_catalog.json` under the semantic cache key; the second run reported `cached=yes`.
- Final status: 0 OCR candidates and 0 failures.
- No DeepSeek API call was made.

结果：

- 添加 `LocalPreparationHarness` 和 `odracir prepare`。
- 真实目录扫描：9 篇论文，0 篇新增，0 篇更新，0 篇缺失。
- 两次运行均跳过全部 9 个仍然有效的 extraction artifact 和全部 9 个仍然有效的 chunk artifact。
- 第一次运行按照新的语义缓存键重建 `research_catalog.json`；第二次运行报告 `cached=yes`。
- 最终状态：0 个 OCR 候选，0 个失败项。
- 未调用 DeepSeek API。
