# Odracir 2.2

[English](README.md)

Odracir 是一个面向单篇论文的科学证据编译器。它把文件夹中的每篇 PDF
彼此独立地转换为一个有类型、绑定原文出处、经过质量门控的 JSON packet，供
SciEngram 等下游系统继续处理。

Odracir 2.2 不比较论文、不滚动注入前文上下文、不生成论文间关系，也不维护
belief state。这些均属于下游任务。它的核心交付协议是：

```text
文件夹中的 N 篇 PDF -> N 个相互独立的 JSON + 一份独立运行报告
```

## JSON 中有什么

每篇论文被表示为：

```text
ResearchQuestion
  -> StudyUnit / 实验
       -> Dataset 与 Method
       -> ResultObservation
       -> Claim
            -> inference_basis_ids
            -> 页码、chunk、原文 provenance
```

Claim 只能引用同一 `StudyUnit` 内的 Result。每个主要科学对象都能追踪到来源
页码和 chunk，并区分忠实转述与接近逐字的原文证据。

## 主流程

1. 递归发现 PDF，并通过 PyMuPDF 提取逐页文本。
2. 在 `.odracir/` 下生成稳定的逐页 chunk 和源文件哈希。
3. 判断论文领域和 scientific logic mode。
4. 选择高价值页面进行 LLM 结构化抽取。
5. 用严格的 2.2 schema 验证输出，必要时进行修复重试。
6. 合并单篇论文内部的重复对象。
7. 验证 ID、StudyUnit 内支持关系、页码、chunk 和 excerpt。
8. 计算确定性的结构与 provenance 诊断分。
9. 第二次 LLM 调用对照全文检查错误项和遗漏项。
10. semantic F1 达到阈值后才把 JSON 写入交付目录。

单篇失败不会影响其他论文，也不会在交付目录留下半成品。

## 安装

需要 Python 3.11 以上、可提取文本的 PDF，以及 DeepSeek-compatible API key。
扫描版 PDF 应先做 OCR。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
```

在 `.env` 中设置 `DEEPSEEK_API_KEY`。默认模型为 `deepseek-v4-pro`。

## 用户主命令

```bash
odracir extract-paper-study \
  --paper-folder /path/to/pdfs \
  --output-folder /path/to/run/packets \
  --report-folder /path/to/run/report \
  --env-file .env
```

程序会递归查找 PDF，但忽略 `.odracir` 目录。

常用参数：

- `--max-chunks 4`：首次抽取最多使用的 chunks 数。
- `--max-tokens 16000`：单次模型响应 token 上限。
- `--validation-retries 1`：结构输出不合法时的重试次数。
- `--minimum-quality-score 0.6`：semantic F1 交付阈值。
- `--index PATH`：可选的输入索引。
- 两个 `--*-usd-per-million-tokens` 参数：为报告提供价格快照。

若有论文失败，命令返回非零退出码，但已经成功的 packets 和全部报告都会保留。

## 输出

```text
run/
├── packets/
│   ├── paper-a.json
│   └── paper-b.json
└── report/
    ├── summary.json
    ├── papers.jsonl
    └── papers.csv
```

`packets/` 只包含通过门控的正式 JSON。报告独立记录每篇论文的 extraction/judge
调用次数、token、耗时、估算费用、precision、recall、F1、失败原因和 telemetry
是否完整。

## 质量控制

系统包含三层互补控制：

- **硬性验证：** schema、唯一 ID、合法引用、页码/chunk 和同一 StudyUnit 内的
  Claim-to-Result 支持关系。
- **确定性诊断：** 结构完整度 50%、provenance coverage 35%、boundary
  richness 15%。
- **语义审计：** judge 对照整篇论文的全部页面，检查错误与核心遗漏并计算
  precision、recall 和 F1。

semantic score 衡量的是抽取忠实度，不是原论文本身的证据强度。p-value 和样本量
可观测性因此单独报告。详见 [ODRACIR_2_2_QUALITY.md](ODRACIR_2_2_QUALITY.md)。

## 恢复失败论文

恢复脚本只重试失败项，验证源文件 SHA，并且绝不覆盖已经验收的 packet：

```bash
python scripts/recover_independent_run.py \
  --source-report /path/to/run/report/papers.jsonl \
  --paper-folder /path/to/pdfs \
  --delivery-folder /path/to/run/packets \
  --work-folder /path/to/recovery/work \
  --report-folder /path/to/recovery/report \
  --env-file .env
```

恢复默认使用 8 个 chunks 和 3 次 validation retries。

## SciEngram 消融证据导出

以下命令完全确定性执行，不调用模型：

```bash
odracir export-ablation-evidence \
  --corpus-root /path/to/formal_corpus \
  --packets-root /path/to/formal_outputs \
  --output-folder /path/to/ablation_evidence
```

它导出 namespace 后的 packet、重建 chunks 和 exact locator crosswalk。详见
[docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md](docs/ODRACIR_2_2_ABLATION_EVIDENCE_EXPORT.md)。

## 228 篇正式验证

仓库内已有完整的 228 篇运行：

- 228 篇 PDF 最终交付 228 个 schema 2.2 JSON；
- 全部最终 packet 达到 0.6 的 semantic-F1 门槛；
- 最终 F1 平均 0.9600，最低 0.6176；
- 消融证据材料包含 5,543 条 provenance-to-chunk bindings；
- 记录约 1,345 万 tokens；
- 模型费用中央估计约 7.06 美元，缺失 telemetry 被明确标记。

这些是基于模型 judge 的工程运行结果，不等同于人工金标准上的抽取准确率。详见
[ODRACIR_2_2_RUN_REPORT.md](ODRACIR_2_2_RUN_REPORT.md)。

## 当前限制

- PyMuPDF 文本层不能完整恢复复杂表格、图片、公式和扫描页面。
- 首次生成只读取选择出的页面；全文 judge 和 recovery 能降低但不能消除遗漏风险。
- 抽取模型和语义 judge 可能具有相关错误。
- 当前正式语料不是双盲人工标注的 gold benchmark。

## 开发

```bash
python -m pytest -q
```

受支持的公开 CLI 只有 `extract-paper-study` 和 `export-ablation-evidence`。
跨论文关系、综合推理和 belief 更新属于 SciEngram。
