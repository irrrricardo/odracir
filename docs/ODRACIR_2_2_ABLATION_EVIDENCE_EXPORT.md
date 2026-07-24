# Odracir 2.2 → SciEngram Ablation evidence 材料包

`export-ablation-evidence` 是无模型、确定性的交付命令。它只在需要评估
raw retrieval、counter-evidence、exact locator 或 typed provenance 时使用；仅构建
packet/source graph 不需要运行它。

## 设计边界

- 不调用 DeepSeek，不读取 API key。
- 不修改 `formal_corpus` 或已经完成的 `formal_outputs`。
- 从正式 PDF 重新执行冻结的 `odracir.pdf-page/1.0` page chunking。
- packet 的 `coverage_ledger` 必须与重建 chunk ID 集合完全相等，否则失败。
- 每个 provenance 必须通过 chunk ID、页码和非改写 excerpt 相似度校验。
- 输出 packet、chunk、crosswalk 使用相同的全局唯一 `paper_id`。
- 原始 packet SHA、原始 `paper_id`、PDF SHA 和命名空间映射写入 manifest。

历史正式 packet 保持原 ID，例如 `1_1`。Ablation 材料包采用：

```text
<original_paper_id>_<horizon>
```

例如：

```text
long/1/1_1.json  -> 1_1_long.json  / paper_id=1_1_long
short/1/1_1.json -> 1_1_short.json / paper_id=1_1_short
```

不能只改文件名：包内 packet、chunk document、locator crosswalk 的 `paper_id` 会
同步变更。原 ID 保存在 packet metadata 和 group manifest 中。

## 单篇验收

```bash
odracir export-ablation-evidence \
  --corpus-root data/formal_corpus \
  --packets-root data/formal_outputs/2_2_version_228 \
  --output-folder /tmp/odracir-ablation-single \
  --horizon long \
  --group 1 \
  --paper-id 1_1
```

目标目录必须不存在，避免把不同运行静默混合。

## 全量导出

```bash
odracir export-ablation-evidence \
  --corpus-root data/formal_corpus \
  --packets-root data/formal_outputs/2_2_version_228 \
  --output-folder data/ablation_evidence/2_2_version_228
```

输出结构：

```text
data/ablation_evidence/2_2_version_228/
├── bundle_manifest.json
├── long/
│   ├── 1/
│   │   ├── group_manifest.json
│   │   ├── packets/
│   │   │   └── 1_1_long.json
│   │   └── evidence/
│   │       ├── chunks/
│   │       │   └── 1_1_long.json
│   │       └── crosswalks/
│   │           └── 1_1_long.json
│   └── ...
└── short/
    ├── 1/
    └── ...
```

`chunks/*.json` 使用 `sciengram-odracir22-chunk-document/1`；
`crosswalks/*.json` 使用 `sciengram-odracir22-locator-crosswalk/1`，并且当前正式
语料必须全部为 `mode=exact_chunk_id`。导出器不做模糊猜测或 silent rebind。

## 交给 Ablation Lab

以 `long/1` 为例：

```bash
SciEngram_Core_v1/.venv/bin/python -m sciengram_ablation_lab snapshot \
  --packets /path/to/2_2_version_228/long/1/packets \
  --chunks /path/to/2_2_version_228/long/1/evidence \
  --queries /path/to/benchmark/queries.jsonl \
  --references /path/to/benchmark/references.jsonl \
  --episodes /path/to/benchmark/dynamic_episodes.jsonl \
  --splits /path/to/benchmark/splits.json \
  --output inputs/snapshots
```

Lab 的 `--chunks` 参数指向整个 `evidence/`，由 Lab 递归识别 `chunks/` 和
`crosswalks/` 两类文件。

## 228 篇现有材料包

当前已经生成：

```text
data/ablation_evidence/2_2_version_228
```

闭合统计：

- 17 个课题组；
- 228 个 packet、228 个 chunk document、228 个 locator crosswalk；
- 228 个全局唯一 Ablation `paper_id`；
- 5,213 个 raw chunks；
- 5,543 条 provenance→chunk bindings；
- 非改写 excerpt 最低相似度 0.95；
- chunk namespace、artifact SHA、crosswalk digest 问题数为 0。

该材料包只补齐 evidence plane。要形成 assessed Observation/BeliefState，仍需
benchmark 阶段冻结的 grounding sidecar；导出器不会把 Odracir inference basis
自动升级成科学支持关系。
