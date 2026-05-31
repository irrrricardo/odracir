# Odracir Workflow / 工作流

This document records how Odracir should run today and how its modules should grow.

本文档记录 Odracir 当前应该如何运行，以及后续模块应该如何扩展。

## Current Workflow / 当前工作流

The current local workflow is:

```text
research folder
-> scan paper storage
-> update odracir_index.json
-> extract PDF page text
-> write .odracir/texts/*.json
-> report extraction state and likely OCR needs
-> optionally create .odracir/ocr/*.pdf derivatives with OCRmyPDF
-> re-extract from current OCR derivatives
-> create stable page-traceable chunks
-> write .odracir/chunks/*.json
-> search chunks with paper/page citations
-> explicitly summarize chosen papers through DeepSeek
-> write .odracir/summaries/*.json
-> later: translate, chat, plan, code
```

当前本地工作流是：

```text
研究文件夹
-> 扫描论文存储目录
-> 更新 odracir_index.json
-> 提取 PDF 按页正文
-> 写入 .odracir/texts/*.json
-> 报告提取状态和可能需要 OCR 的文件
-> 可选：使用 OCRmyPDF 创建 .odracir/ocr/*.pdf derivative
-> 从当前 OCR derivative 重新提取正文
-> 创建稳定、按页可追溯的 chunk
-> 写入 .odracir/chunks/*.json
-> 检索 chunk，并返回论文与页码引用
-> 通过 DeepSeek 显式总结选定论文
-> 写入 .odracir/summaries/*.json
-> 后续：翻译、交流、规划、代码实现
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
    chunks/
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

PDF parsing is a replaceable deterministic tool. Odracir uses a parser registry, keeps `pymupdf` as the default lightweight backend, and exposes the optional `docling` backend for complex layouts. OCRmyPDF is an explicit preprocessor rather than a parser. Backends preserve the normalized artifact contract instead of leaking backend-specific formats into agents.

PDF 解析是一个可替换的确定性工具。Odracir 使用解析器注册表，将 `pymupdf` 保留为默认轻量后端，并暴露用于复杂版式的可选 `docling` 后端。OCRmyPDF 是显式预处理器，而不是 parser。各后端遵守标准化 artifact 契约，不会让后端专属格式泄漏到 agent 中。

Recommended external projects:

推荐评估的外部项目：

- [Docling](https://github.com/docling-project/docling): integrated optional adapter for complex-layout PDFs; see its [official usage docs](https://docling-project.github.io/docling/usage/).
- [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF): integrated optional preprocessing route for PDFs reported as `needs_ocr`; see its [official cookbook](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html).
- [GROBID](https://github.com/kermitt2/grobid): optional service for scholarly metadata, references, and citation structures.
- [MinerU](https://github.com/opendatalab/MinerU): heavier optional backend to benchmark on Chinese, formula-heavy, or complex-layout papers.

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
2. Benchmark the integrated Docling and OCRmyPDF routes on real papers after optional installation.
3. Benchmark and refine DeepSeek-based structured paper summaries.
4. Add Chinese translation for abstract, method, conclusion, and selected key passages.
5. Extend retrieval over `odracir_index.json` and `.odracir/chunks/` with optional embeddings.
6. Add discipline-specific skills only after the generic extraction and memory loop is stable.

1. 先让 scan、extract、status 和 chunk 稳定。
2. 可选安装后，在真实论文上评估已接入的 Docling 和 OCRmyPDF 路径。
3. 对基于 DeepSeek 的结构化论文总结进行基准评估和优化。
4. 添加摘要、方法、结论和关键段落的中文翻译。
5. 使用可选 embedding 扩展对 `odracir_index.json` 和 `.odracir/chunks/` 的检索。
6. 等通用提取和记忆闭环稳定后，再添加学科专用 skill。

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

结果：

- 添加可选 `docling` 后端和显式 OCRmyPDF derivative 路径。
- 在可选安装前，本机能力检查报告 `pymupdf=available`、`docling=unavailable` 和 `ocrmypdf=unavailable`。
- Provenance 迁移首次重新提取 9 篇 PDF；下一次提取全部跳过。
- Provenance 迁移首次重新 chunk 9 篇 PDF；下一次 chunk 全部跳过。
- 最终状态：9 篇 PDF 已提取、9 篇 PDF 已 chunk、0 篇需要 OCR、0 篇失败，共 128 个 chunk。
- 此次无费用迁移期间仍然刻意不运行 DeepSeek 摘要。
