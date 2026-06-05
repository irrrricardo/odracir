# Odracir

[English](README.md) | 中文

[版本记录](CHANGELOG.md) | [路线图](ROADMAP.md)

<!-- ODRACIR_STATUS_START -->
## 项目状态

此区块由 `odracir sync-docs` 自动生成。

- 版本：`0.3.1`
- 阶段：带审计文件夹 state、引用问答、缓存 parser 建议和版本化科研 skill 的可恢复论文库摄取 MVP
- 当前重点：高层 read 工作流、项目简报、保留原始模型阅读结果、可选摘要规范化和受监督审阅
- 最近同步：`2026-06-06T02:31:25+08:00`

当前命令：

- `odracir "message"`：与当前 Odracir agent 对话。
- `odracir read <research-folder> --papers-dir <paper-folder> --skill <skill>`：运行端到端论文库流程，并写入 Markdown 项目简报。
- `odracir ingest-library <research-folder> --skill <skill>`：准备、逐篇总结、审计、刷新可见文件夹 state，并写入摄取运行记录。
- `odracir brief <research-folder> --papers-dir <paper-folder>`：从 `research_catalog.json` 重建人类可读的 `project_summary.md`。
- `odracir synthesize <research-folder> --papers-dir <paper-folder>`：基于已审计 summaries 生成跨论文综合理解。
- `odracir review-synthesis <research-folder> --papers-dir <paper-folder>`：无 API 用量地审阅最新 synthesis artifact。
- `odracir prepare <research-folder>`：无 API 用量地扫描、提取、切块并重建本地记忆。
- `odracir scan <research-folder>`：为研究文件夹创建或更新 `odracir_index.json`。
- `odracir plan-reading <research-folder> --query "<focus>"`：可选地、无 API 用量地排序可检查的下一步阅读行动。
- `odracir scan <research-folder> --papers-dir <paper-folder>`：扫描已有的自定义论文文件夹。
- `odracir capabilities`：检查可选解析器和预处理器是否可用。
- `odracir benchmark-parsers <research-folder> --limit 1`：在不修改科研 artifact 的情况下比较 parser 后端。
- `odracir recommend-parsers <research-folder>`：在不修改 extraction artifact 的情况下缓存 parser 审阅建议。
- `odracir skills [name]`：检查版本化科研 skill manifest。
- `odracir extract <research-folder>`：将 PDF 正文提取到 `.odracir/texts/`。
- `odracir ocr <research-folder>`：为标记为 `needs_ocr` 的 PDF 创建 OCR derivative。
- `odracir status <research-folder>`：报告处理状态、OCR 需求和失败项。
- `odracir chunk <research-folder>`：在 `.odracir/chunks/` 中创建可追溯 chunk。
- `odracir search <research-folder> "<query>"`：检索 chunk 并返回页码级引用。
- `odracir ask <research-folder> "<question>" --dry-run`：无 API 用量地预览问答证据。
- `odracir ask <research-folder> "<question>"`：通过 DeepSeek 基于检索证据回答问题。
- `odracir summarize <research-folder> --paper <paper-id>`：通过 DeepSeek 生成带引用摘要。
- `odracir summarize <research-folder> --skill biomedical-paper --dry-run`：无 API 用量地预览生物医学摘要范围。
- `odracir evaluate-summaries <research-folder> --skill biomedical-paper`：无 API 用量地审计本地摘要。
- `odracir normalize-summaries <research-folder> --skill <skill>`：通过 DeepSeek 规范化已保留的原始模型阅读结果。
- `odracir review-summary <research-folder> --paper <paper-id>`：检查单篇摘要、provenance、引用片段和人工审阅状态。
- `odracir build-memory <research-folder>`：重建可见且经过审计的 `research_catalog.json`。
- `odracir translate <research-folder> --paper <paper-id> --dry-run`：无 API 用量地预览翻译范围。
- `odracir translate <research-folder> --paper <paper-id>`：通过 DeepSeek 翻译选定 chunk。
- `odracir sync-docs`：刷新自动生成的文档状态区块。

<!-- ODRACIR_STATUS_END -->


[工作流](WORKFLOW.md)

[架构路线图](ARCHITECTURE.md)

[下一步路线图](ROADMAP.md)



Odracir 是一个个人化的 agentic system，用于快速进入、理解并实现某个新的科研领域。它的目标是帮助一个人收纳论文、翻译和总结论文、提取结构化知识、围绕该领域与 agent 交流，并逐步把科研理解转化成可执行的计划和代码。

当前项目计划通过 OpenAI-compatible 的客户端接口调用 DeepSeek API。

## 产品目标

Odracir 应该成为一个科研陪伴工具，帮助你：

1. 从你选择的科研论文中建立本地知识库。
2. 快速翻译和总结论文。
3. 提取重要概念、方法、数据集、公式、实验、局限和实现线索。
4. 将每篇论文的信息记录到研究文件夹内的 JSON 索引中。
5. 与一个理解已积累论文内容的 agent 交流。
6. 规划学习路径、实验、复现步骤和代码任务。
7. 在需要实现时调用代码工具。

第一原则是实际加速：Odracir 应该帮助你更快进入一个领域，而不只是生成漂亮的摘要。

## 初始使用场景

一个典型的研究文件夹可以长这样：

```text
research-folder/
  papers/
    paper-a.pdf
    paper-b.pdf
  notes/
  code/
  odracir_index.json
  research_catalog.json
```

你把选好的论文放入 `papers/`。Odracir 读取它们，生成翻译和摘要，提取结构化信息，更新运行台账 `odracir_index.json`，并重建可见的 `research_catalog.json`，让这个文件夹逐渐变成一个本地科研记忆。

当前 harness 已经实现这个流程的本地优先主干：文件夹扫描、正文提取、OCR 路由、可追溯 chunks、检索、带引用问答、版本化摘要 skills、摘要审计、选择性翻译，以及确定性重建 `research_catalog.json`。

对于新的研究文件夹，首先运行 `odracir prepare <research-folder>`。它会在不读取 API 配置、不调用 DeepSeek 的情况下，串联本地扫描、提取、切块和 catalog 构建。OCR、摘要和翻译仍然使用显式后续命令。

## 计划功能

### 论文收纳

- 监控或扫描包含已选论文的文件夹。
- 发现新的 PDF 或文本文档。
- 尽可能提取标题、作者、摘要、章节、参考文献和关键图表。
- 记录每篇论文是否已经处理过。

### 翻译与总结

- 将论文或指定章节翻译成中文。
- 生成短摘要、中等摘要和详细摘要。
- 保留技术术语和重要公式。
- 突出对理解和实现最重要的内容。

### 结构化科研索引

每个研究文件夹应该包含一个 JSON 索引，比如 `odracir_index.json`，用于保存所有已处理论文的结构化记录。

可能的字段：

```json
{
  "papers": [
    {
      "id": "paper-a",
      "title": "Paper Title",
      "authors": ["Author A", "Author B"],
      "year": 2026,
      "source_file": "papers/paper-a.pdf",
      "research_area": "field or topic",
      "core_problem": "what problem the paper solves",
      "main_contribution": "main idea or contribution",
      "methods": ["method 1", "method 2"],
      "datasets": ["dataset 1"],
      "experiments": ["important experiment"],
      "limitations": ["limitation 1"],
      "implementation_notes": ["code or reproduction clue"],
      "summary_short": "short summary",
      "summary_detailed": "detailed summary",
      "processed_at": "2026-05-30T00:00:00+08:00"
    }
  ]
}
```

### 科研交流 Agent

agent 应该能够：

- 基于文件夹中已经处理过的论文回答问题。
- 比较论文，并解释不同思想之间的关系。
- 识别开放问题和仍未解决的冲突。
- 推荐下一步阅读内容。
- 帮助把论文理解转化成实验或实现任务。

### 规划与代码辅助

Odracir 后续应该支持：

- 复现规划。
- 环境配置规划。
- 代码脚手架生成。
- 实验任务拆解。
- 调试支持。
- 在安全且有用时调用本地代码工具。

## 建议的 Agent 角色

系统可以先从一个 agent 开始，等确实需要时再拆分职责。

初始单 agent 角色：

- `research_companion`：读取文件夹上下文，与用户交流，使用工具，并给出科研或实现建议。

未来可能的角色：

- `paper_intake_agent`：发现并处理新论文。
- `paper_summary_agent`：翻译、总结并提取结构化记录。
- `research_memory_agent`：维护和查询文件夹级 JSON 索引。
- `planning_agent`：创建学习、复现和实现计划。
- `coding_agent`：帮助生成代码骨架、运行检查并解释实现细节。
- `review_agent`：检查摘要、计划和代码中缺失的假设或薄弱证据。

## 项目结构

```text
src/odracir/
  agent.py      # agent loop：模型调用、工具调用、最终回答
  config.py     # DeepSeek provider 配置
  tools.py      # 工具注册和示例工具
  retrieval.py  # 带论文、页码和 chunk 引用的本地关键词检索
  providers.py  # 可替换 LLM provider 适配器
  docling_adapter.py # 可选的复杂版式 PDF 解析器
  pymupdf4llm_adapter.py # 可选的版式感知 Markdown PDF 解析器
  ocr.py        # 显式 OCRmyPDF derivative 预处理
  parser_benchmark.py # 只读 parser 比较
  parser_routing.py # 带缓存的 parser 审阅建议
  skills/        # 版本化、多学科科研 skill manifest
  summary_evaluation.py # 本地摘要质量审计
  summarization.py # 注重证据的 map-reduce 论文摘要
  translation.py # 可追溯的选择性 chunk 翻译
  question_answering.py # 检索优先、带引用的科研问答
  cli.py        # 命令行入口
tests/
  test_tools.py
```

计划中的项目结构：

```text
src/odracir/
  agents/
  tools/
  ingestion/
  memory/
  schemas/
  planning/
  coding/
  cli.py
```

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

然后编辑 `.env`，设置 `DEEPSEEK_API_KEY`。

Odracir 默认使用 DeepSeek `deepseek-v4-pro` 处理文本。需要不同的费用、延迟或
推理深度时，可以在 `.env` 中覆盖 `DEEPSEEK_MODEL` 或 `DEEPSEEK_THINKING`。
适配层接受 `enabled`、`disabled` 或空的 thinking 值。

## 运行

```powershell
odracir "帮我规划一个用于阅读扩散模型论文的科研助手。"
```

或者：

```powershell
python -m odracir.cli "帮我总结当前项目目标。"
```

摄取论文库并刷新可见文件夹 state：

```powershell
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic --dry-run
odracir ingest-library <research-folder> --papers-dir <paper-folder> --skill generic
```

运行完整受监督阅读流程，并写入项目简报：

```powershell
odracir read <research-folder> --papers-dir <paper-folder> --skill generic
odracir brief <research-folder> --papers-dir <paper-folder>
```

在 summaries 已经通过审计后，生成并审阅跨论文综合：

```powershell
odracir synthesize <research-folder> --papers-dir <paper-folder>
odracir review-synthesis <research-folder> --papers-dir <paper-folder>
```

`synthesize` 会调用 DeepSeek，写入人类可读的 `research_synthesis.md`，并在
`.odracir/synthesis/` 下保存可复用的结构化 artifact。它会跨论文比较主题、方法、主张、
证据、benchmark、冲突、研究空白，以及阅读或复现优先级。

`review-synthesis` 是确定性工具，不会调用 DeepSeek。它会检查最新 synthesis artifact 的
论文覆盖率、主张引用、强主张证据支撑、benchmark 可比性，以及阅读或复现优先级覆盖，
并写入 `synthesis_review.md` 和 `.odracir/synthesis/reviews/` 下的机器可读审阅 artifact。
`warning` 表示综合结果可用但有质量问题需要检查；`fail` 表示 artifact 结构错误或缺少必要证据。

`read` 是日常使用的高层入口。它会运行准备、摘要生成、本地评估、记忆重建，
并写入人类可读的 `project_summary.md`。如果论文直接放在研究文件夹根目录，
需要显式传入 `--papers-dir "."`。

`ingest-library` 是论文库主工作流。它会准备本地正文和 chunk，使用版本化结构化
科研 prompt 阅读每篇普通论文，审计摘要，并刷新根目录下可见的
`research_catalog.json` state。默认情况下，每篇普通论文只调用一次 DeepSeek；
如果某篇论文超过保守 single-pass 阈值，或其结构化输出未通过校验，Odracir
会透明降级为 map-reduce，并在 provenance 中记录原因。如果模型返回了有价值的
内容，但无法解码为结构化 JSON，Odracir 会将原始阅读结果保留到
`.odracir/raw-summaries/`，并把论文标记为 `raw_captured`，而不是丢弃内容。
之后可以使用 `odracir normalize-summaries` 将原始阅读结果规范化为经过审计的
摘要记忆。使用 `--dry-run` 可以在不调用 DeepSeek 的情况下准备 artifact 并
预览范围。
每次运行（包括 dry-run）都会在 `.odracir/jobs/ingestion/` 下写入紧凑审计记录；
`latest.json` 指向最近一次运行。记录会保留输入、阶段计数、摘要策略、API 用量、
失败项和输出路径，但不会重复存储完整论文摘要。

规范化已保存的原始模型阅读结果，并检查一篇结构化摘要：

```powershell
odracir normalize-summaries <research-folder> --papers-dir <paper-folder> --skill generic
odracir review-summary <research-folder> --papers-dir <paper-folder> --paper <paper-id>
```

除非显式提供人工决定，否则 `review-summary` 只读：

```powershell
odracir review-summary <research-folder> --paper <paper-id> --decision accepted
odracir review-summary <research-folder> --paper <paper-id> --decision needs-revision --note "<reason>"
```

仅准备可检索本地 artifact 并重建文件夹记忆，不调用 API：

```powershell
odracir prepare <research-folder> --papers-dir <paper-folder>
```

可选地、无 API 用量地规划下一步阅读行动：

```powershell
odracir plan-reading <research-folder> --papers-dir <paper-folder> --query "<research focus>" --skill biomedical-paper
```

确定性队列会记录就绪状态、缺失摘要、查询相关性、标题语料中心性、工作量、
可追溯证据片段和建议的受监督命令，并写入 `.odracir/planning/reading-queues/`。
它是可选辅助工具，不是摄取流程的必要步骤。使用 `--no-write` 可以只做临时预览。

扫描一个研究文件夹：

```powershell
odracir scan D:\Research\diffusion-models
```

这个命令会在需要时创建文件夹，确保 `papers/`、`notes/` 和 `code/` 存在，并写入或更新 `odracir_index.json`。

扫描一个已有的自定义论文文件夹：

```powershell
odracir scan "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

这个命令会把研究索引保存在 `medical-world-models` 文件夹中，同时从已有的 `Paper Storage` 文件夹读取 PDF。

提取 PDF 正文：

```powershell
odracir extract "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

这个命令会把按页提取的正文 artifact 写入 `.odracir/texts/`，并在 `odracir_index.json` 中更新提取状态、页数、文本长度和 artifact 路径。

检查可选文档工具是否可用：

```powershell
odracir capabilities
```

安装 `pip install -e ".[docling]"` 后，可以为复杂版式 PDF 使用 Docling：

```powershell
odracir extract <research-folder> --paper <paper-id> --parser docling --force
```

安装可选 PyMuPDF4LLM 后端，并在不修改科研 artifact 的情况下将其与轻量默认后端进行比较：

```powershell
pip install -e ".[pymupdf4llm]"
odracir benchmark-parsers <research-folder> --papers-dir <paper-folder> --limit 1
```

完成 benchmark 后，缓存保守的审阅建议：

```powershell
odracir recommend-parsers <research-folder> --papers-dir <paper-folder>
```

建议会写入 `.odracir/parser-routing/`。默认策略继续选择 `pymupdf`；只有人工审阅某篇论文后，才显式运行 `extract --parser pymupdf4llm --force`。候选后端只有在至少多提取 1,000 个字符且文本增幅至少达到 3% 时，才会进入审阅队列。

人工审阅比较结果后，可以选择性使用版式感知 Markdown 后端：

```powershell
odracir extract <research-folder> --paper <paper-id> --parser pymupdf4llm --force
```

安装 `pip install -e ".[ocr]"` 和 OCRmyPDF 所需的系统依赖后，可以为报告为 `needs_ocr` 的 PDF 创建 OCR derivative：

```powershell
odracir ocr <research-folder> --papers-dir <paper-folder> --language eng
odracir extract <research-folder> --papers-dir <paper-folder>
```

OCR derivative 会写入 `.odracir/ocr/`；原始 PDF 不会被修改。下一次提取会自动使用当前 OCR derivative。

查看处理状态、OCR 需求和失败项：

```powershell
odracir status "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

为成功提取的 PDF 创建稳定、按页可追溯的 chunk：

```powershell
odracir chunk "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

Chunk artifact 会写入 `.odracir/chunks/`。重复运行时，未变化的正文 artifact 会被跳过。

检索本地 chunk，并返回可检查的论文与页码引用：

```powershell
odracir search "D:\Research\medical-world-models" "world model" --limit 3
```

在不读取 API 配置、不调用 DeepSeek 的情况下预览文件夹级科研问题所使用的证据：

```powershell
odracir ask "D:\Research\medical-world-models" "How do medical world models predict clinical trajectories?" --query "medical world model clinical trajectories" --limit 4 --dry-run
```

根据检索到的本地证据回答问题：

```powershell
odracir ask <research-folder> "<question>" --query "<focused retrieval query>"
```

非 dry-run 路径会显式调用 DeepSeek，并在 `.odracir/answers/` 下写入可复现的问答 artifact。答案、结构化 claims 和缓存 artifact 都会根据检索证据的引用白名单进行校验。

为一篇明确选择的论文生成带引用摘要：

```powershell
odracir summarize "D:\Research\medical-world-models" --papers-dir "Paper Storage" --paper <paper-id>
```

这个命令会显式调用 DeepSeek，并产生 API 用量。Odracir 会把结果写入 `.odracir/summaries/`，记录 provider、模型、prompt 版本、输入 hash、token 用量和引用；后续重复运行时会跳过未变化摘要。

检查内置科研 skill，并在不读取 API 配置、不调用 DeepSeek 的情况下预览生物医学摘要范围：

```powershell
odracir skills
odracir skills biomedical-paper
odracir summarize "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper --dry-run
odracir evaluate-summaries "D:\Research\medical-world-models" --papers-dir "Paper Storage" --skill biomedical-paper
odracir build-memory "D:\Research\medical-world-models" --papers-dir "Paper Storage"
```

`generic` 仍然是默认的跨学科 skill。`biomedical-paper` 添加版本化、注重证据的字段：研究人群、干预或暴露、对照、结局、机制、assay 或测量、临床相关性，以及安全或伦理。每一个结构化生物医学条目都必须保留来源引用，或者显式设置 `inference=true`。实际执行后的摘要会记录所选 skill 及其版本，因此切换 skill 会使旧摘要缓存失效。

`evaluate-summaries` 是确定性工具，不会调用 DeepSeek。它会在 `.odracir/evaluations/summaries/` 下写入带缓存的报告，检查 artifact 是否缺失或过期，根据当前 chunks 重新校验引用，并报告 limitations 缺失、生物医学字段为空等需要人工复核的 warning。

`build-memory` 也是确定性工具，不会调用 DeepSeek。它根据精简索引和经过审计的 summary artifact 重建可见的 `research_catalog.json`。缺失、过期或无效的摘要会保持显式状态，不会被悄悄当作已经积累的知识。agent 也可以通过 `get_research_memory` 临时读取同一目录，而不写入文件。

将默认选择的摘要、方法和结论段落翻译为中文：

```powershell
odracir translate "D:\Research\medical-world-models" --papers-dir "Paper Storage" --paper <paper-id>
```

在不读取 API 配置、不调用 DeepSeek 的情况下预览选定 chunks：

```powershell
odracir translate "D:\Research\medical-world-models" --papers-dir "Paper Storage" --paper <paper-id> --dry-run
```

默认路径最多翻译 8 个选定 chunk。可以重复使用 `--section` 或 `--chunk` 精确控制范围。`--all-chunks` 被刻意设计为显式参数，因为它可能产生较多 API 用量。Odracir 会将带 provenance 的译文写入 `.odracir/translations/`，并在后续运行时跳过未变化选择。

刷新自动生成的文档状态区块：

```powershell
odracir sync-docs
```

## 文档同步

README 文件里包含一个由程序生成的项目状态区块，位于这些标记之间：

```text
<!-- ODRACIR_STATUS_START -->
<!-- ODRACIR_STATUS_END -->
```

只有这个区块会被自动管理。Markdown 文件里的其他内容仍然保持手写，这样项目叙事不会变成失控的自动生成文本。

如果希望每次提交前自动同步：

```powershell
odracir install-hooks
```

这个命令会配置 git 使用 `.githooks/pre-commit`。该 hook 会运行文档同步命令，并在 commit 创建前把更新后的 README 文件重新加入暂存区。

## 开发路线图

1. 将第一版保持为单 agent 加小型工具注册表。
2. 使用研究文件夹 harness 创建并更新 `odracir_index.json`。
3. 将 PDF 正文提取到 `.odracir/texts/` 下的本地 artifact。
4. 验证类型化 `odracir_index.json` schema，并检查处理状态。
5. 将提取正文切分为 `.odracir/chunks/` 下稳定、按页可追溯的 artifact。
6. 使用 `odracir prepare` 作为扫描、提取、切块和 catalog 重建的可恢复本地入口。
7. 审阅缓存的 parser 路由建议，并检查代表性 PyMuPDF4LLM 输出，再接受逐篇 parser override。
8. 审阅生物医学摘要 dry-run，并运行受控的 DeepSeek 摘要和选择性翻译基准。
9. 在添加可选 embedding 前，先评估和优化带引用的 `odracir ask` 路径。
10. 安装系统依赖后，在扫描版 fixture 上验证显式 OCRmyPDF 路径。
11. 添加复用已审计问答与检索路径的科研 companion agent。
12. 添加阅读路径、复现和实验规划工具。
13. 在科研记忆稳定后添加代码辅助工具。
14. 只有当单 agent 的 prompt 变得过大或职责冲突时，才拆分为多个 agent。

## 设计原则

- 本地优先：研究文件夹即使没有远程数据库也应该可理解。
- 结构化记忆：重要信息应该写入 JSON，而不是只困在聊天历史里。
- 注重证据：回答应该尽可能指回论文或笔记。
- 增量构建：先搭好一个可靠闭环，再增加多个 agent。
- 个人化：优先优化一个人的科研速度、偏好和工作流。
