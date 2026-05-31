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
-> explicitly summarize chosen papers through DeepSeek
-> write .odracir/summaries/*.json
-> explicitly translate selected chunks through DeepSeek
-> write .odracir/translations/*.json
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
-> 通过 DeepSeek 显式总结选定论文
-> 写入 .odracir/summaries/*.json
-> 通过 DeepSeek 显式翻译选定 chunk
-> 写入 .odracir/translations/*.json
-> 后续：交流、规划、代码实现
```

## Commands / 命令

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
odracir scan "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir status "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "world model" --limit 3
odracir ask "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
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
  .odracir/
    texts/
      paper-id.json
    ocr/
      paper-id.pdf
    summaries/
    translations/
    answers/
    chunks/
    parser-routing/
```

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

## Future Skill Strategy / 后续 Skill 策略

Odracir should not make one giant prompt for every discipline. It should keep a stable core workflow and add discipline-specific skills.

Odracir 不应该为所有学科写一个巨大的 prompt。它应该保持稳定核心工作流，再增加面向学科的 skill。

Possible future skills:

未来可能的 skill：

- `biomedical-paper-skill`: population, intervention, comparator, outcome, mechanism, assay, clinical relevance, safety, ethics.
- `computer-science-paper-skill`: task, model, dataset, metric, baseline, ablation, implementation details, reproduction plan.
- `materials-science-paper-skill`: composition, synthesis, characterization, properties, mechanism, experimental conditions.
- `review-skill`: check whether summaries preserve evidence, limitations, and uncertainty.
- `coding-reproduction-skill`: turn paper records into environment setup and implementation tasks.

## Near-Term Roadmap / 近期路线图

1. Keep scan, extract, status, and chunk reliable.
2. Review cached parser-routing recommendations and representative PyMuPDF4LLM outputs before accepting per-paper overrides.
3. Benchmark and refine DeepSeek-based structured paper summaries.
4. Benchmark selective Chinese translation on reviewed abstract, method, conclusion, and chosen-passage examples.
5. Benchmark the cited `odracir ask` route and add optional embeddings only when retrieval evidence justifies them.
6. Validate the explicit OCRmyPDF path on a scanned fixture after installing system dependencies.
7. Add a GROBID service adapter when scholarly metadata and citation graphs become the next concrete need.
8. Add discipline-specific skills only after the generic extraction and memory loop is stable.

1. 先让 scan、extract、status 和 chunk 稳定。
2. 审阅缓存的 parser 路由建议和代表性 PyMuPDF4LLM 输出，再接受逐篇 parser override。
3. 对基于 DeepSeek 的结构化论文总结进行基准评估和优化。
4. 在人工审阅的摘要、方法、结论和选定段落样例上评估选择性中文翻译。
5. 评估带引用的 `odracir ask` 路径；只有检索证据证明有必要时，才添加可选 embedding。
6. 安装系统依赖后，在扫描版 fixture 上验证显式 OCRmyPDF 路径。
7. 当学术元数据和引用图谱成为明确需求时，添加 GROBID 服务 adapter。
8. 等通用提取和记忆闭环稳定后，再添加学科专用 skill。

## Execution Log / 执行记录

### 2026-05-30

Environment setup:

```powershell
cd D:\PycharmProjectsStorage\odracir
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

环境配置：

```powershell
cd D:\PycharmProjectsStorage\odracir
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Medical World Model extraction:

```powershell
odracir scan "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

医学世界模型论文提取：

```powershell
odracir scan "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

Result:

- PDFs found: 9.
- PDFs extracted: 9.
- Failures: 0.
- Output index: `D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\odracir_index.json`.
- Text artifacts: `D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\.odracir\texts\`.

结果：

- 发现 PDF：9 篇。
- 成功提取：9 篇。
- 失败：0 篇。
- 输出索引：`D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\odracir_index.json`。
- 文本 artifact：`D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\.odracir\texts\`。

Medical World Model status and chunking validation:

```powershell
odracir status "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

Medical World Model 状态与 chunking 验证：

```powershell
odracir status "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

Result:

- Status before chunking: 9 extracted PDFs, 9 with `chunking_status=not_started`, 0 OCR needs, 0 failures.
- First chunk run: 9 chunked, 0 blocked, 0 failures.
- Second chunk run: 0 regenerated, 9 skipped.
- Status after chunking: 9 extracted PDFs and 9 chunked PDFs.
- Chunk artifacts: `D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\.odracir\chunks\`.
- Chunk count: 128 total chunks, with 6 to 23 chunks per paper.

结果：

- Chunking 前状态：9 篇 PDF 已提取，9 篇为 `chunking_status=not_started`，0 篇需要 OCR，0 篇失败。
- 第一次 chunk：9 篇完成，0 篇阻塞，0 篇失败。
- 第二次 chunk：0 篇重复生成，9 篇跳过。
- Chunking 后状态：9 篇 PDF 已提取，9 篇 PDF 已完成 chunking。
- Chunk artifact：`D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model\.odracir\chunks\`。
- Chunk 数量：共 128 个，每篇论文包含 6 至 23 个 chunk。

Medical World Model lexical retrieval validation:

```powershell
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "world model" --limit 3
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" clinical --limit 3 --json
```

Medical World Model 关键词检索验证：

```powershell
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "world model" --limit 3
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" clinical --limit 3 --json
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
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

可选文档工具 adapter 迁移：

```powershell
odracir capabilities
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
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
odracir ask "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
```

带证据问答与解析器候选检查：

```powershell
odracir ask "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
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
odracir benchmark-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage" --parser pymupdf --parser pymupdf4llm
```

PyMuPDF4LLM adapter 与只读 parser benchmark：

```powershell
pip install -e ".[pymupdf4llm]"
odracir capabilities
odracir benchmark-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage" --parser pymupdf --parser pymupdf4llm
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
odracir recommend-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir recommend-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

带缓存的建议式 parser 路由：

```powershell
odracir recommend-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
odracir recommend-parsers "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
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
