# Odracir 2.0 代码取证报告

指定运行：run-20260713T015531Z

结论先行：Odracir 2.0 的实际主链是“PDF 页级文本缓存 → Recon → 战略分批 → 分批滚动上下文辅助 LLM 抽取 → 确定性修复/规范化 → 质量门 → Delivery/GlobalStateLedger 组装”。extract-paper-study CLI 本身到 assembly/run manifest 为止；final reconciliation 和 SciEngram exporter 是后续独立脚本，不在该 CLI 内。

本次取证基线：

- 当前分支：odracir_version2
- 当前 HEAD：d644d4d48f9e5cf5a95e1573909eb4af45bcefff
- [run_metadata.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/run_metadata.json) 记录的 revision 与 HEAD 相同。
- 当前源码和测试目录相对 HEAD 无差异。
- 当前测试执行结果：130 passed。
- 用当前代码加载并校验了该 run 的 assembly、Delivery、ledger、reconciliation；19/19 SciEngram packet、19/19 crosswalk 和 quality report 哈希全部匹配 manifest。
- 未修改任何代码文件。

下文标记：

- 【代码】当前代码直接证明。
- 【产物】指定 run 的文件直接证明。
- 【推断】代码与产物联合推断，但运行时没有完整记录。
- 【无法确认】当前代码/产物不足以证明。

---

# A. 主调用链与状态边界

## A1. extract-paper-study 的完整调用链

实际调用顺序如下。

~~~text
console script
  → cli.main
  → run_extract_paper_study
      → ensure_pdf_chunk_artifacts
      → discover_paper_entries
      → build_corpus_manifest_from_entries
      → write_corpus_manifest
      → 过滤 byte-identical duplicate representatives
      → MedoidBatcher.plan
      → DeepSeekJsonProvider.from_environment
      → run_paper_study_scheduler
          → PaperStudyPipeline.__call__ / _process
              → load_chunk_artifact
              → plan_paper_extraction / write_extraction_plan
              → GlobalContext.prompt_projection
              → extract_paper_study
              → plan_packet_canonicalization
              → apply_packet_canonicalization
              → PaperStudyPacketV2.model_validate
              → evaluate_packet_quality
              → 写单篇 packet/report
          → advance_global_context（每批结束）
      → assemble_scheduler_result
      → write_corpus_assembly
      → build_run_manifest / write_run_manifest
~~~

逐步对应如下：

1. 【代码】odracir 与 odracir-v2 均进入 odracir.cli:main，见 [pyproject.toml](/home/rchu/project_storage/SciEngram/pyproject.toml:20) 和 [cli.py](/home/rchu/project_storage/SciEngram/src/odracir/cli.py:37)。

2. 【代码】main() 识别 extract-paper-study，转入 run_extract_paper_study()，见 [cli.py](/home/rchu/project_storage/SciEngram/src/odracir/cli.py:77)。

3. 【代码】ensure_pdf_chunk_artifacts(paper_folder) 在读取 index 之前无条件执行，输入是论文目录，输出是 chunk artifact 路径列表；会写 .odracir/texts 和 .odracir/chunks，见 [ingestion.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/ingestion.py:17)。

4. 【代码】discover_paper_entries() 从 index 或 chunk 文件生成 PaperIndexEntry[]，见 [pipeline.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/pipeline.py:351)。

5. 【代码】build_corpus_manifest_from_entries() 读取全部 chunk，生成 CorpusManifest：含 PaperProfile、duplicate groups、complete-link clusters 和 digest；随后 write_corpus_manifest() 原子写入，见 [pipeline.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/pipeline.py:405) 和 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:659)。

6. 【代码】CLI 明确把 Recon manifest 作为 Batch 0 membership 边界，并删除 byte-identical duplicates 的非代表条目，见 [cli.py](/home/rchu/project_storage/SciEngram/src/odracir/cli.py:103)。

7. 【代码】MedoidBatcher.plan(manifest, entries, batch_size) 输出 StrategicBatchPlan，随后写 scheduler/strategic_batch_plan.json，见 [scheduler.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/scheduler.py:259)。

8. 【代码】DeepSeekJsonProvider.from_environment() 从 dotenv/process env 建立 provider；读取 dotenv 会修改进程环境，实际 completion 是网络副作用，见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:102)。

9. 【代码】run_paper_study_scheduler() 接收 PaperIndexEntry[]、PaperStudyPipeline、StrategicBatchPlan 和初始 GlobalContext，输出 SchedulerRunResult；同一批所有论文收到冻结的同一个输入 context，见 [scheduler.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/scheduler.py:582)。

10. 【代码】每篇进入 PaperStudyPipeline._process()：

    - 读取 ChunkArtifact
    - 生成、写入 PaperExtractionPlan
    - 取得 GlobalContext.prompt_projection()
    - 调用 LLM 抽取并验证
    - 生成、写入 canonicalization plan
    - 应用 canonicalization 并重新验证
    - 计算 quality
    - 写 PaperStudyCard.json、PaperStudyPacketV2.json、quality_report.json、extraction_report.json
    - 失败时写 pipeline_attempt.json

    见 [pipeline.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/pipeline.py:193)。

11. 【代码】每批结束后，成功 packet 中排序靠前的 Claim 被转为 ContextFinding，追加到下一批 GlobalContext；失败论文不进入 context，见 [scheduler.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/scheduler.py:486)。

12. 【代码】assemble_scheduler_result() 从各批 packet 构造 append-only GlobalStateLedger、ledger snapshots、generation/alignment receipts 和 Delivery，见 [assembly.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/assembly.py:223)。

13. 【代码】write_corpus_assembly() 写 assembly manifest、Delivery、ledger aliases/content-addressed snapshots；最后写 run manifest，见 [assembly.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/assembly.py:607) 和 [cli.py](/home/rchu/project_storage/SciEngram/src/odracir/cli.py:151)。

14. 【代码】final reconciliation/export 不在上述 CLI 链中。它们由 [finalize_stage3_corpus.py](/home/rchu/project_storage/SciEngram/scripts/finalize_stage3_corpus.py:54) 调用：

~~~text
load_corpus_assembly
  → reconcile_corpus
  → write/load_reconciliation
  → export_sciengram_packets
  → human conflict review
  → finalization manifest
~~~

配置来自 [CLI parser](/home/rchu/project_storage/SciEngram/src/odracir/cli.py:179) 和 provider 环境变量。CLI 当前默认值为 batch 10、max chunks 4、max output tokens 16000、validation retries 1、每篇 context claims 3、context cap 100、profile features 96、cluster threshold 0.45、quality floor 0.6。

【产物】本 run 不是一次完全无故障的单次 CLI：初次 7 批中 1_5 失败，随后 append-only recovery 把它作为实际 Batch 8 重新抽取，见 [recovery_manifest.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/full-19-recovered/recovery/recovery_manifest.json)。

【测试】CLI 全链、滚动 context、裸 PDF、重复 PDF、quality gate、fallback 等由 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:228) 覆盖；assembly 链由 [test_assembly.py](/home/rchu/project_storage/SciEngram/tests/test_assembly.py:210) 覆盖。

---

## A2. authoritative source 与派生产物

【代码】没有一个跨越所有阶段、被代码明确声明为“全局唯一真源”的单一对象；真源随阶段变化。

| 边界 | authoritative 内容 | 派生或索引 |
|---|---|---|
| 摄取前 | PDF 原始 bytes | 文件名、目录结构 |
| PDF 抽取阶段 | ChunkArtifact 中的页文本和 source_sha256 是后续读取证据的实际输入 | texts/*.json 是人可读页文本副本 |
| Batch 0 | CorpusManifest 决定有效代表论文、duplicate 和 cluster | profile/cluster 可由 chunk 重算 |
| 单篇抽取 | canonical PaperStudyPacketV2 是论文级科学结构 | PaperStudyCard.json 当前只是同内容别名；planning/report 是审计 |
| Assembly 后 | Delivery.packet + packet digest + generation/alignment receipts 是组装时绑定的论文提交物 | 单篇目录中的 packet 文件不再由 assembly loader 直接信任 |
| 全局状态 | GlobalStateLedger 是该 revision 的 assertion/relation materialized history | 它没有 Dataset/Method 等全部论文细节，不能替代 Packet |
| Final reconciliation | FinalReconciliationResult 是从 assembly 派生的、非修改性准入视图 | core_knowledge_snapshot 不是原始知识全集 |
| 下游交接 | SciEngram packet 是 Delivery + ledger + reconciliation 的适配输出 | crosswalk、CSV、manifest 是追踪/校验辅助 |

相关 schema：

- PaperStudyPacketV2、EvidenceSpan、Claim 等见 [models.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/models.py:214)。
- GlobalStateLedger、Delivery 见 [models.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/models.py:535) 和 [models.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/models.py:797)。
- CorpusManifest 见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:327)。

【代码】load_corpus_assembly() 明确不能只信 assembly manifest；它重新读取 content-addressed snapshot 和 Delivery，并验证 packet digest、receipt 及 ledger chain，见 [assembly.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/assembly.py:323)。

【产物】本 run 中：

- 19 份 PaperStudyCard.json 与 PaperStudyPacketV2.json 内容逐字节相同。
- 19 份最终 Packet 与对应 Delivery.packet 对象一致。
- final ledger revision 为 8，含 91 assertions、0 relations，见 [global_state_ledger.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/full-19-recovered/ledger/global_state_ledger.json)。
- 下游 19 个完整 packet 位于 [sciengram_export/packets](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/sciengram_export/packets)。
- [core_knowledge_snapshot.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/odracir/core_knowledge_snapshot.json) 只有 10 个准入 assertions，不能替代 19 个 packet。

副作用发生在各 writer；Packet/ledger/reconciliation 的模型验证本身不写文件。

【测试】Delivery digest、ledger append-only、manifest tamper、reconciliation binding、export closure 分别见 [test_ledger_models.py](/home/rchu/project_storage/SciEngram/tests/test_ledger_models.py:239)、[test_assembly.py](/home/rchu/project_storage/SciEngram/tests/test_assembly.py:210)、[test_reconciliation.py](/home/rchu/project_storage/SciEngram/tests/test_reconciliation.py:167) 和 [test_sciengram_export.py](/home/rchu/project_storage/SciEngram/tests/test_sciengram_export.py:151)。

---

## A3. 跳过 Recon、Scheduler、Context、Ledger、reconciliation/export 的开关

【代码】CLI 没有这些 skip/feature flags。

| 模块 | CLI 是否能跳过 | API 层行为及后果 |
|---|---|---|
| PDF ingestion | 否 | ensure_pdf_chunk_artifacts() 无条件在 discover/index 前执行 |
| Recon | 否 | 可直接自行调用低层 scheduler，但不属于 CLI 主链；CLI 的战略分批必须有匹配的 manifest |
| Strategic plan | CLI 否 | run_paper_study_scheduler(strategic_plan=None) 可退化为 publication chronology 分批 |
| Scheduler | 否 | 单独调用 PaperStudyPipeline 可抽单篇，但不会得到跨批 context、Delivery、ledger |
| GlobalContext | 否 | max_claims_per_paper=0 可使 findings 为空，但 context 对象、digest、through_batch、receipt 仍存在 |
| Ledger/Delivery | 否 | assembly、reconciliation、最终 exporter 需要它们；缺 snapshot/receipt/digest 会加载或绑定失败 |
| Final reconciliation | 不在 CLI 中 | exporter API 接受 reconciliation=None，此时以 ledger supported 作为 core；相关 reconciliation 权重/理由为空 |
| SciEngram exporter | 不在 CLI 中 | 可不运行，但不会产生 19 个下游 packet；finalization 脚本没有 skip 参数 |

【代码】战略计划的 batch size、paper IDs、Recon digest 不匹配会直接报错，见 [scheduler.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/scheduler.py:745)。缺 Delivery/ledger snapshot 会使 [load_corpus_assembly](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/assembly.py:323) 失败。

【无法确认】run manifest 没有保存完整原命令和所有 runtime config，因此无法确认该 run 的 env-file、provider timeout、SDK retry、thinking、completion max_tokens、quality floor 的精确值。

---

# B. PDF 解析、缓存与来源定位

## B1. PyMuPDF API 与特殊页面处理

【代码】每份 PDF 的调用只有：

~~~python
document = fitz.open(pdf_path)
for page_index, page in enumerate(document, start=1):
    text = page.get_text("text").strip()
~~~

见 [ingestion.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/ingestion.py:57)。

行为边界：

- 旋转页：没有显式 rotation 处理。
- 多栏：没有 block/column 重排；未传 sort=True。
- 隐藏文字层：没有显式过滤。
- 乱码：原样保留，没有字符质量检测。
- 重复文本：没有去重。
- 空页：跳过，不产生 chunk。
- 部分扫描 PDF：有文字的页保留，纯图像页静默跳过。
- 全部页面无文本：抛出“需要 OCR”的错误。
- 单页解析异常：没有 per-page try/except，会中止该 PDF 摄取。
- 加密/损坏 PDF：没有专门异常分类。
- OCR：完全未实现。

【无法确认】旋转、多栏、隐藏层在该 run 使用的具体 PyMuPDF 版本下会按什么内部顺序返回，因为依赖只限定 PyMuPDF>=1.24，没有锁定实际版本；run 也未保存依赖快照。

输入/输出：

- 输入：PDF 文件路径。
- 输出一：未定义 Pydantic schema 的 text JSON，含 paper_id/source_file/source_sha256/pages[{page,text}]。
- 输出二：ChunkArtifact，其中每个 SourceChunk 对应一个非空物理页，见 [planning.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/planning.py:22)。

副作用：原子写 .odracir/texts/<paper>.json 和 .odracir/chunks/<paper>.chunks.json。

质量：

- PDF 解析阶段没有页级质量分。
- Recon 的 quality_proxy 只看文本长度、token、section hint、内容 hash 唯一率，不是 OCR/版面质量评分。
- 后面的 packet quality 是结构/证据/边界分，不是 PDF 解析质量。

【产物】19 个代表 PDF 共 376 个物理页、352 个非空页级 chunks，即有 24 页没有进入 chunk。原始 20 份输入中 1_14 与 1_13 PDF bytes 重复，Recon 最终采用 19 个代表。

【测试】[test_ingestion.py](/home/rchu/project_storage/SciEngram/tests/test_ingestion.py:21) 覆盖普通 PDF 缓存和全扫描 PDF 拒绝；没有旋转、多栏、隐藏层、乱码、部分扫描、加密/损坏 PDF 的专项测试。

---

## B2. offset、bbox、reading order 与最细 EvidenceSpan 定位

【代码】texts 和 chunks 均不保存：

- 字符 offset
- line/block/span
- bbox
- 原 PDF x/y 坐标
- 字体/字号
- reading-order index
- 跨页段落关系

SourceChunk 只保存：

~~~text
chunk_id
ordinal
section_hint
page_start/page_end
text
character_count
token_estimate
content_sha256
~~~

EvidenceSpan 为：

~~~text
span_id
content
provenance {
  chunk_id,
  page_start,
  page_end,
  text_excerpt,
  paraphrased
}
~~~

见 [planning.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/planning.py:22) 和 [models.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/models.py:156)。

因此目前最细的持久化来源定位是：

- 页级 chunk_id
- 1-based PDF page range
- 一段 excerpt/paraphrase 文本

若 paraphrased=false，可事后在页文本里进行近似字符串定位，但 offset 没有被保存；若 true，代码无法定位到页内具体位置。

副作用：无；这是 schema/validator 行为。

【测试】exact excerpt 的局部窗口匹配和页范围修复由 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:616) 覆盖；没有 bbox/offset，因为 schema 中没有这些字段。

---

## B3. hash、chunk ID 与缓存命中

【代码】精确逻辑：

~~~text
source_sha256 = SHA256(PDF raw bytes)
page_content_sha256 = SHA256(stripped page text UTF-8)
chunk_id = SHA256(
    f"{source_sha256}:{physical_page_number}:{page_content_sha256}"
).hexdigest()[:20]
~~~

见 [ingestion.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/ingestion.py:74)。

另外：

- text_artifact_sha256 是写完后的整个 text JSON 文件 SHA-256。
- paper_id 默认由清洗后的文件 stem 产生；stem 冲突时追加 relative path hash 前 8 位。
- chunker metadata 固定写 odracir.pdf-page / 1.0，但不参与缓存判断。

缓存命中只检查：

1. 目标 chunk artifact 文件存在；
2. 能加载；
3. artifact paper_id 等于当前 paper ID；
4. artifact source_sha256 等于当前 PDF bytes hash。

因此：

| 变化 | 是否使当前目标缓存失效 |
|---|---|
| PDF bytes 变化 | 是 |
| 仅 PDF mtime 变化 | 否 |
| 文件名/stem 变化 | 生成新 paper ID/新目标；旧缓存不会清理 |
| 相同 stem、同 bytes 移动目录 | 可能继续命中，旧 source_file 可能保留 |
| 页文本变化但 PDF bytes 不变 | 正常情况下不可能被检测；缓存不会重解析 |
| parser/PyMuPDF 版本变化 | 否 |
| chunker name/version 变化 | 否 |
| chunker 配置变化 | 否 |
| text JSON 缺失/损坏 | 命中时不检查 |
| text_artifact_sha256 不匹配 | 命中时不检查 |
| 旧 orphan chunk | 不自动清理，后续 glob 可能发现 |

【代码】如果现有 chunk JSON 损坏，加载失败会直接传播，不会自动重建。

副作用是写缓存及可能保留 orphan；没有全局内存状态。

【测试】普通缓存复用由 [test_ingestion.py](/home/rchu/project_storage/SciEngram/tests/test_ingestion.py:21) 覆盖。没有 parser-version invalidation、text-artifact tamper、移动 PDF、orphan 清理测试。

---

## B4. title、authors、DOI、年份、section、caption、supplementary 来源

| 字段 | 当前来源 |
|---|---|
| title | Recon 仅从全文中匹配显式 Title: 标签 |
| authors | Recon 仅匹配显式 Authors: 标签 |
| year | Recon 仅匹配显式 Year: 标签 |
| DOI | 未实现 |
| PDF metadata | 完全未读取 document.metadata |
| section | 页首 500 字符中的关键词规则 |
| figure/table caption | 可能作为普通页文本进入 LLM，但没有专门识别或结构化 parser |
| supplementary | 没有特殊处理；同一 PDF 中按普通页，独立 supplementary PDF 会成为另一 paper |
| LLM metadata | LLM 即使生成也会被宿主覆盖，不能持久化 title/authors/year |

section hint 规则按优先顺序识别 abstract / methods / results / discussion / references，否则为空，见 [ingestion.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/ingestion.py:153)。

PaperStudyPacketV2.metadata 最终由宿主重建，主要含：

~~~text
source_file
source_sha256
chunk_schema_version
classified_domain
scientific_logic_mode
input_context_digest
input_context_through_batch
~~~

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:992)。

【产物】本 run 的 19 个 Recon profile 中，title/authors/year 全部为 null；最终 Packet metadata 均无 title/authors/DOI/year。SciEngram export 的 figure/table 结构为空。

【测试】显式标签 metadata extraction 在 [test_recon.py](/home/rchu/project_storage/SciEngram/tests/test_recon.py:129) 有覆盖；PDF metadata、DOI、caption、supplementary 无测试，也无实现。

---

# C. Recon、聚类与调度

## C1. Recon 的 feature、词表、权重和文本范围

【代码】extract_paper_profile() 使用该论文所有 chunks 的全文连接串，不做页选择，也不排除 references，见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:427)。

所以参考文献部分会参与：

- token frequency
- domain/logic classification
- conflict phrase count
- methods/systems/rungs 识别
- metadata regex

仅后面的页面选择器会对“文本以 references 开头的页”降权；Recon 不降权。

提取 feature：

1. domain：clinical / computational / wet-lab / general。
2. scientific_logic_mode：causal / contrastive / methodological / phenomenological。
3. title/authors/year 显式标签。
4. top tokens：正则 tokenization、casefold、去 stopwords 后按频率降序、词典序平分。
5. experimental systems：cell_line, cultured_cells, drosophila, ex_vivo, human_participants, in_vitro, in_vivo, mouse, organoid, primary_cells, rat, tissue, yeast, zebrafish。
6. methods：ablation, benchmark, confocal microscopy, crispr/cas9, cross-validation, elisa, flow cytometry, gene knockdown/siRNA, knockout, overexpression, immunoblot/western blot, mass spectrometry, microscopy, qPCR, randomized trial, regression, RNA-seq, simulation。
7. causal rungs：association / temporal order / intervention / mechanism / rescue。
8. section hints。
9. conflict signals：

~~~text
although
conflicting
contrary to
did not
disagree
failed to
however
in contrast
inconsistent
no evidence
opposite
whereas
~~~

10. quality_proxy：

~~~text
0.4 × proportion(chunks with character_count >= 80)
+ 0.2 × has any token
+ 0.2 × has any nonempty section_hint
+ 0.2 × unique content hash ratio
~~~

完整正则与词表见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:41)。

向量 namespace 权重：

| Namespace | 总权重 |
|---|---:|
| domain | 1.00 |
| logic mode | 1.00 |
| title tokens | 0.50 |
| author tokens | 0.25 |
| year | 0.25 |
| experimental systems | 0.75 |
| methods | 0.75 |
| causal rungs | 0.75 |
| top-token profile | 1.00 |
| section hints | 1.00 |
| conflict signals | 0.25 |

每个 namespace 内按计数相对分配，见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:508)。

输入是 paper_id + source path/hash + ChunkArtifact；输出是 PaperProfile，最终聚合为 CorpusManifest。核心提取函数是纯计算，write_corpus_manifest() 才写文件。

配置：max_profile_features、cluster_distance_threshold 来自 CLI。

【产物】本 run 19 个 profile 均保留 96 个 top tokens，cluster threshold 为 0.45；metadata 特征全空。Recon manifest 见 [corpus_manifest.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/full-19-provisional/recon/corpus_manifest.json)。

【测试】source-only、确定性、metadata、distance、duplicate、roundtrip 见 [test_recon.py](/home/rchu/project_storage/SciEngram/tests/test_recon.py:91)。

---

## C2. complete-link 的向量、距离、阈值和确定性

【代码】不是 embedding，也不是 TF-IDF。它是上述稀疏 feature map 的 cosine distance：

~~~text
distance = 1 - dot(a,b) / (||a|| × ||b||)
~~~

结果 clamp 到 [0,1]，并 round 到 12 位。零向量分别处理，见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:573)。

complete-link 两 cluster 的距离是所有跨 cluster paper-pair 距离的最大值。算法反复：

1. 找 distance <= threshold 的 cluster pair；
2. 选择 key 最小者：(complete_link_distance, sorted_merged_member_ids)；
3. 合并并稳定排序；
4. 无可合并 pair 时停止。

见 [recon.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/recon.py:590)。

medoid 为 cluster 内“到其他成员的距离总和最小”的 paper；平分时依次按较高 quality_proxy、paper ID、source path，见 [scheduler.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/scheduler.py:801)。

因此：

- 相同 PDF bytes、paper IDs、source paths、代码、词表和配置下，cluster 和 medoid 是确定性的。
- 输入遍历顺序不会改变结果。
- 文件名/path、paper ID、parser 输出、feature cap、threshold、代码版本变化时，tie 或向量可能变化；不能声称跨这些变化仍完全相同。

【产物】本 run 5 个 cluster：

~~~text
[1_1, 1_20, 1_4]                         medoid 1_20
[1_10, 1_12, 1_16, 1_17, 1_6, 1_9]     medoid 1_6
[1_11, 1_13, 1_15, 1_18, 1_19, 1_5]    medoid 1_13
[1_2, 1_3, 1_8]                          medoid 1_8
[1_7]                                    medoid 1_7
~~~

【测试】输入顺序稳定性见 [test_recon.py](/home/rchu/project_storage/SciEngram/tests/test_recon.py:165)，medoid/routing 见 [test_scheduler.py](/home/rchu/project_storage/SciEngram/tests/test_scheduler.py:250)。

---

## C3. Scheduler 顺序如何影响 extraction

【代码】Scheduler 对 extraction 的直接影响只有：

1. paper 执行顺序；
2. batch 边界；
3. 因此每篇能够看到哪些更早批次的 GlobalContext.findings。

以下变量不直接进入 prompt/page selection/canonical key：

- cluster ID
- medoid 标记
- seed/skeleton/conflict role
- anchor
- similarity
- conflict overlap
- 原计划 batch number

每篇 pipeline 是先完成分类和选页，再调用 global_context.prompt_projection()；所以历史 context 不影响 domain、logic、页面得分或 selected chunk IDs，见 [pipeline.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/pipeline.py:211)。

实际进入 prompt 的滚动对象为：

~~~text
GlobalContext {
  through_batch,
  findings[{
    paper_id,
    claim_id,
    statement,
    polarity,
    inference_basis_ids,
    source_chunk_ids
  }],
  dropped_finding_count,
  rendered_summary
}
~~~

同一批所有论文共享冻结 context；批内不滚动。每批结束只从成功 packet 中提取 findings，按以下优先级排序：

~~~text
有 inference basis
→ basis 数多
→ exact provenance 优先
→ additional provenance 多
→ statement 长
→ claim_id
→ statement
~~~

超过 cap 时从最旧 finding 开始丢弃。

batch/历史还会间接影响：

- Packet metadata 的 input_context_digest
- input_context_through_batch
- packet digest
- generation receipt
- ledger/Delivery binding

但不进入 canonical semantic key。

【产物】本 run 计划与实际：

~~~text
B1: 1_20, 1_6, 1_13
B2: 1_8, 1_7
B3: 1_1, 1_12, 1_4
B4: 1_19, 1_16, 1_5（1_5 失败）
B5: 1_18, 1_2, 1_11
B6: 1_15, 1_3, 1_17
B7: 1_10, 1_9
B8: 1_5 recovery
~~~

context finding 数轨迹：

~~~text
0→9→15→23→28→37→46→52→54
~~~

dropped count 为 0。1_5 recovery 看到的是 B7 后的 52 个 findings，而不是原计划 B4 前的 23 个；它仍使用与初次相同的 8 页计划。证据见 [run_manifest.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/full-19-recovered/run_manifest.json) 和 [batches.csv](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/full-19-recovered/visualizations/batches.csv)。

这就是当前“长程阅读”的实际认知滚动：前文少量 Claim 作为后文 LLM 的比较/召回提示，不是跨论文 evidence merge，也不影响页面检索。

【测试】冻结批内 context、失败不进入 context、cap、战略计划控制批界，见 [test_scheduler.py](/home/rchu/project_storage/SciEngram/tests/test_scheduler.py:151)。

---

# D. 单篇规划与证据检索

## D1. 页面评分公式

【代码】每个 chunk 就是一页。页面得分为：

~~~text
若 normalized_text.startswith("references "):
    score = -1000
否则:
    score =
        2 × Σ min(domain_signal 出现次数, 3)
      + 4 × Σ min(logic_signal 出现次数, 3)
      + 1 × Σ min(generic_signal 出现次数, 3)
~~~

见 [planning.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/planning.py:312)。

generic signals：

~~~text
result
experiment
method
limitation
significant
figure
~~~

domain signals：

- computational：computational biology, bioinformatics, transcriptomics, gene regulatory network, network biology, machine learning, deep learning, foundation model, perturbation prediction
- wet-lab：wet lab, cell biology, molecular biology, cancer biology, developmental biology, neuroscience, immunology, mechanobiology, morphogenesis, cell line, reagent, assay
- clinical：clinical trial, clinical study, patient cohort, human participants, inclusion criteria, exclusion criteria, treatment regimen, clinical endpoint, adverse event, epidemiology
- general：proposed method, framework, algorithm, benchmark, baseline, ablation, performance, modeling, mathematical model, theoretical model, simulation, review

logic signals：

- causal：knockout, knockdown, inhibition, overexpression, laser ablation, rescue, reconstitution, necessary, sufficient, causal mechanism
- contrastive：same phenotype, different mechanism, context dependent, opposite effect, opposite conclusion, in contrast, whereas, distinct mechanism, rather than, instead of, alternative mechanism, does not rely on
- methodological：benchmark, baseline, outperform, state of the art, ablation, runtime, memory usage, data efficiency, under the assumption, modeling, mathematical model, theoretical model, simulation, assumption, parameter sensitivity
- phenomenological：spatial transcriptomics, spatial proteomics, multiplex imaging, microscopy, spatial neighborhood, tissue architecture, ligand receptor, cell cell communication, colocalization, spatial gradient

完整词表见 [domains.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/domains.py:122)。

选择规则：

1. ordinal 最小的第一页无条件保留，即使得分低或是 references。
2. 其余页面按 (score, -ordinal) 降序。
3. 平分时 ordinal 更小的页优先。
4. 取到 max_chunks。
5. 最终把已选页面按 ordinal 升序重新排序后送给 LLM，而不是按得分顺序。

section_hint 不参与评分。references 降权也只匹配“页文本以 references 开头”，不是所有含引用文本的页。

输入是 ChunkArtifact + ClassificationDecision + max_chunks，输出 PaperExtractionPlan；函数纯计算，write_extraction_plan() 原子写 planning.json。

【产物】19 篇均有多于 8 个非空 chunks，且最终每篇都选了恰好 8 页，因此可确认本 run 的 max_chunks=8。总计选 152/352 chunks，所选文本约占全部代表页文本字符数的 56.3%。

【测试】页面宽度在 CLI 测试中有间接覆盖；没有一个单测逐项锁定全部权重、references -1000、第一页强制和平分 ordinal 规则。

---

## D2. max-chunks 8、token budget 与输入顺序

【代码】--max-chunks 8 是最多 8 个页级 chunks，不是 token budget。

SourceChunk.token_estimate = ceil(character_count/4) 只被记录，没有参与选页或 prompt 截断。--max-tokens 被传给 DeepSeek completion 的 max_tokens，限制输出，不限制输入，见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:175)。

如果 8 页加 system schema/context 超过模型输入限制：

- Odracir 内部没有进一步 truncation；
- 没有按页或 token 二次裁剪；
- 请求会交给 provider/API，可能返回 context-length/provider error；
- 该类错误是否由 SDK 重试取决于 provider，Odracir 没有缩短 prompt 后重试的分支。

输入页面按物理页/ordinal 顺序，不是得分顺序。

副作用只发生在写 planning 和后续网络调用。

【产物】该 run 没有保存实际 max_tokens、模型 context limit 或原命令，不能确认运行时 completion 上限。19 个成功 packet 证明最终请求被模型接受，但不能证明没有接近限制。

---

## D3. section、邻页、跨页、图表和二次检索

【代码】实际参与情况：

| 信号 | 参与 selection/retrieval | 参与 LLM prompt |
|---|---|---|
| section_hint | 否 | 是 |
| 邻接页扩展 | 否 | 不自动加入 |
| 跨页段落拼接 | 否 | 各页作为独立 chunk |
| 图注 | 仅作为普通文字命中 figure | 若所在页被选中则发送 |
| 表格结构 | 否 | 仅 PyMuPDF 扁平文本 |
| 当前已抽取对象 | 否 | 单次全包 completion |
| 前篇 Claim | 不参与选页 | 作为 GlobalContext |
| 未填槽位后的全文补检索 | 完全没有 | — |

repair 和 flat fallback 会重复使用同一组 selected pages、同一个初始 GlobalContext 和原 evidence request。没有“发现 Claim 缺 basis 后再读全文”的二次读取机制。

输入/输出仍是同一个 PaperExtractionPlan 和 PaperStudyPacketV2 schema；没有额外文件副作用。

【测试】repair 使用原 request、fallback、未知 provenance 拒绝分别见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:529)、[test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:996) 和 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:1059)。没有二次检索测试，因为不存在该路径。

---

# E. LLM 抽取、失败与修复

## E1. DeepSeek prompt 拼接顺序与 token 占比

相关类：

- DeepSeekJsonProvider
- JsonCompletionResult
- PaperExtractionResult
- PaperStudyPacketV2

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:78)。

### 初始 system prompt

【代码】顺序为：

1. source-only、GlobalContext 仅作 guidance；
2. hard provenance rule；
3. provenance few-shot；
4. 禁止编造、空列表、unique ID、同 StudyUnit basis 等规则；
5. domain focus；
6. scientific logic focus；
7. mandatory coverage targets；
8. 完整、minified 的 PaperStudyPacketV2.model_json_schema()；
9. 最终 hard provenance check；
10. silent self-correction 指令。

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:498)。

### 初始 user prompt

前缀之后按以下 JSON 插入顺序：

~~~text
paper_id
source_file
source_sha256
classified_domain
scientific_logic_mode
prior_global_context
chunks[
  chunk_id,
  ordinal,
  section_hint,
  page_start,
  page_end,
  text
]
~~~

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:547)。

### repair prompt

顺序：

1. 修复指令；
2. hard provenance rule；
3. few-shot；
4. validation errors；
5. 上次 payload 经安全修复后的旧 JSON；
6. 完整原始 evidence request；
7. final repair check；
8. silent check；
9. JSON-only 指令。

### flat fallback prompt

顺序：

1. flat marker；
2. 恰好一个 RQ、一个 StudyUnit 的 shape；
3. preservation 指令；
4. structural error；
5. 上次 hierarchical JSON；
6. 完整原 evidence request；
7. hard provenance rule；
8. silent check。

DeepSeek 请求固定：

~~~text
messages = [
  {role: system, content: system_prompt},
  {role: user, content: user_prompt}
]
response_format = {"type": "json_object"}
~~~

配置来自：

~~~text
DEEPSEEK_API_KEY
DEEPSEEK_MODEL
DEEPSEEK_BASE_URL
DEEPSEEK_TIMEOUT_SECONDS
DEEPSEEK_MAX_RETRIES
DEEPSEEK_THINKING
~~~

dotenv 使用 override=False，已有进程环境优先。

副作用：dotenv 可能修改 process environment；completion 有外部网络调用。

【产物】19 份 report 均为 provider=deepseek、model=deepseek-chat、finish_reason=stop。当前代码默认模型不是 deepseek-chat，说明运行时发生过配置覆盖，但覆盖来自 env-file 还是 process env 无法确认。

累计 usage：

~~~text
prompt_tokens       552,448
completion_tokens    98,469
total_tokens         650,917
~~~

即 provider 记录中 prompt 占总 API tokens 的约 84.87%，completion 占 15.13%。

【无法确认】无法再拆分 system/schema/domain/context/pages/old JSON/errors 的 token 占比，因为：

- report 只保存每篇所有 attempts 的累计 token；
- 未保存 tokenizer；
- 未保存失败的原始 payload 和 validation errors；
- 多轮 repair/fallback prompt 无法完整重建。

首轮 prompt 可以从 planning、chunks、对应 batch context 重建：system 约 14.5k 字符；user 约 31k–94.5k 字符；context JSON 从 172 增长到约 42k 字符。但字符占比不等于 token 占比。

【测试】dotenv 优先级见 [test_extraction_environment.py](/home/rchu/project_storage/SciEngram/tests/test_extraction_environment.py:38)；repair/hard provenance 见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:529)。没有真实 DeepSeek request 序列化的集成测试。

---

## E2. LLM 负责什么，宿主覆盖什么，什么会重试

### LLM 负责

【代码】LLM 生成：

- ResearchQuestion、StudyUnit、Dataset、Method、Result、Claim、EvidenceSpan 内容；
- 初始所有实体 ID；
- Claim→Result inference_basis_ids；
- provenance chunk/page/excerpt/paraphrased；
- polarity；
- limitations；
- 可能生成 metadata、status、quality 等字段。

### 宿主强制覆盖

_validate_payload() 会覆盖：

~~~text
schema_version = "2.0"
paper_id
metadata（整个对象）
coverage_ledger
quality_score = 0
status / requires_reconciliation
validation_warnings
~~~

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:992)。

之后 canonicalization：

- 重生成 StudyUnit ID；
- 重生成 Result ID；
- 重生成 Claim ID；
- 重写 Claim basis；
- Dataset、Method、ResearchQuestion、EvidenceSpan ID 不做一般 canonical rewrite；
- duplicate Method ID 可在前置 safe correction 中变成 __dup2 等。

### 确定性局部修复

只实现三类：

1. paraphrased=false 且已知 chunk 中相似度 <0.95：改为 true。
2. 页码为合法整数、非倒置、chunk 已知但超出页范围：两端重置为 chunk 权威页范围。
3. duplicate Method ID：按文档顺序追加 __dupN。

这些修复不重新调用 LLM。

### 全包重试

以下会使整个 packet 用 repair prompt 重生成：

- provider 返回空/无效/非 object JSON；
- Pydantic closed-schema/type/range 错误；
- coverage 不完整；
- ID 唯一性错误；
- Claim basis 指向错误 Result；
- unknown provenance chunk；
- provenance 页范围不合法；
- exact excerpt 对齐失败且不能安全修复；
- 其他 packet semantic validation 错误。

不存在 JSON Patch 或某个 Claim 的局部 LLM 修复。

在 hierarchical retries 耗尽后，只有 duplicate-ID 类错误才可能进入 flat fallback；canonicalization 和 quality 阶段发生在 extraction 返回之后，其失败不会触发 LLM repair。

【产物】应用层共 26 次 completion：

~~~text
16 篇 attempts=1
1_19 attempts=2
1_7、1_8 attempts=4，最终 flat_fallback
~~~

修复审计共：

~~~text
35 次 false→true
2 次 page correction
2 次 duplicate method correction
2 个 flat fallback warning
~~~

历史 attempt 的 correction 也会保留并令最终 packet provisional。例如 1_19 第二次成功，但第一次的 false→true correction 仍进入最终 warning；1_8 最终没有 methods，却保留了前几次 hierarchical attempt 的 duplicate-method warning。

【测试】上述修复分支见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:657)、[test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:717) 和 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:917)。

---

## E3. flat_fallback 的准确触发与损失

【代码】准确条件是：

1. 所有 hierarchical attempts 已耗尽；
2. 最后一个错误文本包含以下任一 marker：

~~~text
Duplicate question_id:
Duplicate unit_id:
Duplicate result_id in StudyUnit
Duplicate dataset_id:
Duplicate method_id:
Duplicate result_id:
Duplicate claim_id:
Duplicate evidence_span_id:
Duplicate span_id:
~~~

见 [extraction.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/extraction.py:944)。

unknown chunk、页码、excerpt、basis、类型错误等不会进入 flat fallback。

flat 不是宿主本地压平，而是再向 LLM 发一次请求。它仍使用：

- 相同 selected pages；
- 相同 GlobalContext；
- 相同 PaperStudyPacketV2 顶层 schema；
- 相同 completion max tokens；
- 原 hierarchical JSON 和错误作为附加输入。

但强制 shape：

~~~text
1 ResearchQuestion
1 StudyUnit，name = "Provisional flat extraction"
datasets = []
methods = []
~~~

因此永久丢失：

- 多个 ResearchQuestion 的层级；
- 多个 StudyUnit 的实验层级；
- Dataset 结构；
- Method 结构；
- 原始 Result/Claim/Evidence 是否完整保留只依赖 LLM，宿主没有等价性验证。

【产物】：

- 1_7：1 RQ / 1 Unit / 0 Dataset / 0 Method / 8 Results / 5 Claims。
- 1_8：1 RQ / 1 Unit / 0 Dataset / 0 Method；canonical 前 10 Results，后 9。
- 1_8 的 correction 路径直接证明此前 hierarchical payload 至少有 3 个 Unit 且有 Method，因此这些层级确实在 fallback 后消失。

【无法确认】失败的原始 hierarchical JSON 没有落盘，所以无法逐事实列出还丢了哪些 Dataset、Method、Result 或 Claim，也无法确认具体是上述哪个 duplicate marker 最终触发。

【测试】duplicate Result flat fallback 见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:996)；unknown provenance 不 fallback 见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:1059)。

---

# F. 验证、质量、准入与导出

## F1. 当前 validator 实现矩阵

| 检查 | 当前是否实现 | 精确边界 |
|---|---|---|
| JSON object | 是 | provider 拒绝空、无效、非 object JSON |
| closed schema | 是 | Pydantic extra="forbid"、strict types、assignment validation、禁止 NaN |
| ID 非空/唯一 | 是 | RQ/Unit/Dataset/Method/Result/Claim/EvidenceSpan 全局唯一；不验证科学身份是否正确 |
| Claim→Result | 是 | basis 必须指向同 StudyUnit Result；但空 basis 在 extraction 阶段允许 |
| duplicate basis | extraction 否；reconciliation 是 | extraction 不拒绝重复；final reconciliation 会标 invalid |
| 页码 | 是 | page_start>=1、非倒置、位于所指 selected chunk 范围 |
| chunk | 是 | extraction provenance 只能指 selected chunks |
| exact excerpt | 是 | paraphrased=false 时 best-local SequenceMatcher >=0.95 |
| paraphrase | 仅标志检查 | paraphrased=true 直接跳过词面对齐，没有 NLI/语义支持验证 |
| 数值 | 部分 | p_value∈[0,1]、n>=1、float/int 类型；不验证是否与原文数字一致 |
| condition | 部分 | canonicalization/ledger identity 提取有限保护条件；不验证 condition 是否有原文支持 |
| direction | 部分 | Claim polarity 是 enum；不验证 statement、Result 与 polarity 一致 |
| modality | 基本没有 | 仅 canonical key 中有有限 modality 词表，不是 typed validator |
| entity type | 结构有 | Dataset/Method/Result/Claim typed schema；不验证科学分类正确性 |
| semantic entailment | 完全没有 | 不检查 Claim 是否由 Result/证据语义蕴含 |
| scientific truth/recall | 完全没有 | quality score 不是科学真值评分 |

paraphrased=true 的具体分支见 [models.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/models.py:199)：直接 return None，不运行相似度或语义检查。

其他 validator：

- coverage ledger 必须覆盖全部 source chunks，selected 为 extracted，其余为 not_selected。
- causal logic 若 selected text 无 rescue/reconstitution/reversal/epistasis，宿主追加一条 boundary limitation，但不是验证失败。
- canonical output 验证 su_ / res_ / clm_ ID 唯一及 basis 闭包。
- quality evaluator 按结构、provenance、logic boundary 打分，不修改 packet。
- reconciliation 再验证 Delivery/digest/status、Claim 唯一、basis 非空且无重复、ledger Result 对齐、Claim/Result provenance chunk 闭包。

【产物】19 个 Packet：

~~~text
40 StudyUnits
193 Results
91 Claims
23 explicit EvidenceSpans
15 Claims 的 inference_basis 为空
~~~

最终 15 个空 basis Claim 全部成为 excluded_invalid。其中 1 个甚至来自 accepted paper 1_6，说明 accepted 不等于每个 Claim 都有完整链。

【测试】schema/provenance/paraphrase/page 在 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:556)；quality 在 [test_quality.py](/home/rchu/project_storage/SciEngram/tests/test_quality.py:85)；reconciliation complete/incomplete chain 在 [test_reconciliation.py](/home/rchu/project_storage/SciEngram/tests/test_reconciliation.py:102)。

未覆盖或未实现的重点是：paraphrased=true 的语义支持、Claim entailment、数字与原文一致性、direction/modality 一致性、重复 basis 的 extraction 端拒绝。

---

## F2. deterministic correction 与 canonicalization 修改内容

### Deterministic correction

修改：

- Provenance.paraphrased: false → true
- page_start/page_end → authoritative chunk page range
- duplicate method_id → method_id__dupN
- causal mode 可能追加 boundary limitation
- 宿主覆盖 metadata/status/coverage/quality 等字段

审计完整性：

| 修改 | 是否保存 before/after | 是否保存原因/路径 |
|---|---|---|
| false→true | 是 | 有 JSON path、原值、新值、相似度原因 |
| page correction | 是 | 有 path、原页码、新页码、chunk 范围 |
| duplicate Method ID | 是 | 有旧/新 ID 和路径 |
| causal boundary limitation | 否 | 只在最终 limitations 中出现，没有独立 correction record |
| 宿主字段覆盖 | 否 | 没有保存 LLM 原始值 |

### Canonicalization

【代码】只对 StudyUnit、Result、Claim 建 canonical key 和 ID；应用过程会：

- 重写三类 ID；
- 重写 Claim basis；
- 合并 exact-key cluster；
- union experiments/tasks、datasets、methods、provenance、basis 等；
- 稳定排序；
- 再验证。

见 [canonicalization.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/canonicalization.py:507)。

合并采用 exact semantic key，policy score 为 1_000_000；Result 若双方 p_value 或 n_sample_size 明确冲突则阻止合并。key 中包含规范化 statement/metric/value、polarity、部分实验条件、dataset split、study arm、perturbation、stage/time/dose/genotype、causal rung、direction、modality 等。

审计：

- canonicalization_plan.json 保存 source packet hash、source ID、content hash、semantic key、canonical ID 和 rewrite map。
- 实际 merge 会在 Packet merge_decisions 中保存 survivor、merged IDs、算法/key/score、来源对象及 provenance。
- 不保存完整字段级 JSON before/after。
- pre-canonical 完整 Packet 没有单独落盘，因此不能仅凭 run artifact 恢复所有原始 statement。

是否可能把条件不同的事实合并：可能。条件只有在被模型放入 key 使用的字段，或被有限条件词表识别时才受保护。若差异只存在于 provenance、未结构化语句或词表外条件，而规范化 key 相同，就可能合并。

【产物】本 run：

- 40 Unit、194 Result、91 Claim 输入 canonicalizer；
- 输出 40 Unit、193 Result、91 Claim；
- 325 个源 ID 全部被 canonical rewrite；
- 唯一 merge 出现在 1_8：

~~~text
res_single_pearson_k562
res_single_pearson_rpe1
→ res_570d88041e2c5b536194d175
~~~

这直接证明两个源 ID 命名为不同 cell line 的 Result 在当前 key 下合并了；仅凭代码审计不能进一步断言该科学合并一定错误。

【测试】isomorphic merge、hard-negative 保留、idempotence、complete-link 在 [test_canonicalizer.py](/home/rchu/project_storage/SciEngram/tests/test_canonicalizer.py:186)；没有完整 pre/post 字段逐项保真测试。

---

## F3. quality、accepted/provisional、core/deferred/excluded 状态机

真实状态机如下：

~~~text
LLM payload
  ↓ Pydantic + semantic/provenance validation
若所有 attempts 无 correction/fallback warning
  → Packet accepted, requires_reconciliation=false
若任一历史 attempt 有 deterministic correction 或 flat fallback
  → Packet provisional, requires_reconciliation=true
  ↓ canonicalization
  ↓ quality_score = 0.50 structural + 0.35 provenance + 0.15 boundary
  ↓ pipeline quality gate
  ↓ assembly
accepted evidence    → weight 1,000,000 → assertion supported
provisional evidence → weight   350,000 → assertion unresolved
  ↓ final reconciliation
accepted + complete chain    → core_accepted
provisional + complete chain → deferred
任意 status + invalid chain  → excluded_invalid
  ↓ SciEngram exporter
core_accepted basis → registered support edge
deferred/excluded   → relation_candidate
~~~

几个关键事实：

1. 【代码】accepted/provisional 不由 quality score 决定，而由 correction/fallback warning 历史决定。
2. 【代码】quality score 是：

~~~text
0.50 × structural
+ 0.35 × provenance
+ 0.15 × logic-boundary
~~~

见 [quality.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/quality.py:92)。

3. 【代码】accepted 低于 quality floor 会失败。provisional 只要 _has_complete_core_evidence_chain() 为真，可以绕过低分 floor；该函数只要求“存在 Result，至少一个 Claim 有 basis，非空 basis IDs 在全 packet Result 集内”，并不要求每个 Claim 有 basis，见 [pipeline.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/pipeline.py:507)。

4. 【代码】“accepted-only core”不是“科学真理已经验证”，而是“accepted packet 中具有完整结构/provenance/ledger 闭包的 Claim”。

【产物】本 run：

~~~text
Paper status:       3 accepted / 16 provisional
accepted papers:    1_12, 1_3, 1_6
quality range:      0.7236–0.9620
ledger assertions:  91
  supported:         11
  unresolved:        80
relations:            0

reconciliation:
  core_accepted:     10
  deferred:          66
  excluded_invalid:  15
~~~

15 个 excluded 原因全部是 claim_missing_inference_basis。完整逐 Claim 理由在 [reconciliation_decisions.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/odracir/reconciliation_decisions.json)。

### Exporter 如何复制字段

相关函数为 export_sciengram_packets()、_build_packet()、_append_entity_provenance()、_evidence_record()，见 [sciengram_export.py](/home/rchu/project_storage/SciEngram/src/odracir/paper_study/sciengram_export.py:87)。

- Claim statement：直接复制 claim.statement。
- Claim polarity：直接复制。
- Claim conditions：来自所属 StudyUnit.experiments_or_tasks，不是从 Claim 自身重新抽取的 protected condition atoms。
- Claim basis：复制原 inference_basis_ids，并映射为 registered edge 或 relation candidate。
- Result statement/value：复制 value_raw_text。
- Result conditions：同样来自所属 Unit 的 tasks/experiments。
- Evidence：每个 primary/additional provenance 都物化为独立 evidence record，复制 text_excerpt/chunk_id/page_start/page_end/paraphrased/source_locator。
- reconciliation disposition、weight、quality、alignment receipt 同时写入对象。
- validation warnings 映射成 validation_needs。

【产物】最终 export：

~~~text
19 packets
40 experiments
79 datasets
84 methods
193 results
91 claims
162 metrics
311 evidence records
85 limitations
57 validation_needs
164 Claim basis references
  19 registered support edges
 145 relation candidates
~~~

19 个下游文件在 [packets](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/sciengram_export/packets)；Odracir→SciEngram ID/JSONPath 追踪在 [crosswalks](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/sciengram_export/crosswalks)；哈希和闭包见 [export_manifest.json](/home/rchu/project_storage/SciEngram/data/formal_outputs/2_0_version/long_horizon/long_1_19/run-20260713T015531Z/final-reconciliation/sciengram_export/export_manifest.json)。

副作用：

- reconcile_corpus()、quality evaluator、canonicalization plan 是内存计算。
- apply_packet_canonicalization() 返回新 Packet。
- reconciliation writer 和 exporter 使用 staging/atomic publish 写文件。
- finalization 要求目标目录为空。

【测试】quality gate 见 [test_pipeline_cli.py](/home/rchu/project_storage/SciEngram/tests/test_pipeline_cli.py:433)；accepted/provisional ledger 传播见 [test_assembly.py](/home/rchu/project_storage/SciEngram/tests/test_assembly.py:76)；reconciliation 见 [test_reconciliation.py](/home/rchu/project_storage/SciEngram/tests/test_reconciliation.py:102)；export 字段/准入/确定性见 [test_sciengram_export.py](/home/rchu/project_storage/SciEngram/tests/test_sciengram_export.py:151)。

---

# 无法确认事项汇总

1. run 没有保存完整 CLI argv、env-file、provider base URL/timeout/SDK retry/thinking、completion max tokens、完整依赖版本，因此这些不能从产物反推为精确值。
2. 失败的 LLM 原始 JSON、validation errors 和逐轮 prompt 没有持久化，因此无法完整审计 flat fallback 的事实损失，也无法拆分各 prompt 组件的 token 占比。
3. 当前 validator 没有语义蕴含、科学真值、数字原文一致性或 paraphrased=true 支持性验证；accepted/core 都只能按代码定义理解为结构和证据链准入状态。
