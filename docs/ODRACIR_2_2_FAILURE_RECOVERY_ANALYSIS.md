# Odracir 2.2 初次运行失败与恢复成功分析

## 1. 目的与范围

本文总结 Odracir 2.2 在正式运行
`data/formal_outputs/2_2_version_71` 中出现的论文级初次失败、定向恢复和最终成功案例，重点回答：

- 初次运行为什么会失败；
- 哪些失败可以通过重新抽取恢复；
- 扩大抽取上下文和增加校验重试分别发挥了什么作用；
- 哪些问题不能靠重复运行解决；
- 后续应如何形成稳定、可审计的失败恢复流程。

本文仅依据仓库中保留的 `papers.jsonl`、`recovery_attempts.jsonl`、
`summary.json`、`RECOVERY.md`、最终 packet 及相关代码提交进行分析。

## 2. 当前架构中的失败位置

Odracir 2.2 的论文级处理链路为：

```text
PDF ingestion
  -> page-level chunks
  -> chunk selection and extraction plan
  -> LLM structured extraction
  -> schema and provenance validation
  -> canonicalization
  -> deterministic quality diagnostics
  -> full-paper semantic quality judge
  -> semantic F1 quality gate
  -> final paper-local JSON
```

失败可以发生在以下几个阶段：

1. **PDF 导入阶段**：PDF 损坏、加密、没有可抽取文本或需要 OCR。
2. **模型调用阶段**：连接失败、超时、限流、空响应、无效 JSON。
3. **结构校验阶段**：字段缺失、类型错误、重复 ID、跨 StudyUnit 引用、非法 provenance。
4. **语义质量阶段**：抽取错误过多、遗漏核心内容过多，导致 precision、recall 或 F1 不达标。
5. **协议边界阶段**：输入并非研究论文，正确的空抽取却被评价协议错误拒绝。

当前 CLI 默认选择最多 4 个 page-level chunks 进行抽取，但语义 Judge 使用整篇论文的全部 chunks 核验遗漏。因此，较少的抽取上下文不能通过“只评价已选页面”获得虚高召回率；长论文中未被抽取器看到的核心方法、实验和结果会被 Judge 计为遗漏。

## 3. 历史恢复概况

`2_2_version_71` 中共有 5 篇论文留下了“失败后恢复成功”的记录，累计保留 7 条失败尝试：

| 论文 | 初次失败类型 | 初始配置/状态 | 恢复结果 | 主要恢复措施 |
|---|---|---|---|---|
| `1_10` | DeepSeek 返回无效 JSON | 4/15 chunks | F1 = 0.8400 | 定向重跑，选择 8 chunks，重试预算增至 3 |
| `1_16` | 语义 F1 低于 0.6 | P = 0.5294，R = 0.6429，F1 = 0.5806 | P = 1.0，R = 0.8438，F1 = 0.9153 | 选择 chunks 从 4 增至 8，并重新抽取 |
| `2_19` | DeepSeek 返回无效 JSON | 4/15 chunks | F1 = 0.9348 | 定向重跑，选择 8 chunks |
| `3_10` | Claim 跨 StudyUnit 引用 Result | 两次校验后仍失败 | P = 1.0，R = 0.94，F1 = 0.9691 | 选择 8 chunks 后重新生成结构 |
| `2_13` | 空抽取被质量代码拒绝 | 一页作者勘误，连续失败 3 次 | P = R = F1 = 1.0 | 修正空非研究文档的评价语义 |

长论文三个分组的恢复说明分别位于：

- `long-group1-run-20260719T192803Z/report/RECOVERY.md`
- `long-group2-run-20260719T195212Z/report/RECOVERY.md`
- `long-group3-run-20260719T200409Z/report/RECOVERY.md`

## 4. 逐篇案例分析

### 4.1 `1_10`：无效 JSON 后恢复

初次失败记录为：

```text
error_type: ValueError
error_message: DeepSeek returned invalid JSON content
selected_chunks: 4
source_chunks: 15
```

恢复运行选择了 8 个 chunks，最终结果为：

```text
precision: 1.0
recall: 0.7241
F1: 0.8400
incorrect_item_count: 0
missed_core_item_count: 16
extraction.attempts: 1
```

该案例说明无效 JSON 通常是可恢复的模型生成失败。恢复后的 `extraction.attempts=1` 表明，恢复运行的第一次调用就返回了合法结果；因此成功不能简单归因于“内部多重试了几次”。更准确的解释是：重新调用模型，并改变输入上下文后，生成轨迹发生变化并得到合法 JSON。提高重试预算主要提供额外保险。

最终 recall 仍只有 0.7241，说明恢复成功仅代表越过 F1 门槛，并不代表没有遗漏。该论文仍有进一步提高抽取覆盖率的空间。

### 4.2 `1_16`：低 F1 和召回不足后恢复

初次运行结果：

```text
selected_chunks: 4 / 15
precision: 0.5294
recall: 0.6429
F1: 0.5806
incorrect_item_count: 8
missed_core_item_count: 5
```

恢复运行结果：

```text
selected_chunks: 8 / 15
precision: 1.0
recall: 0.8438
F1: 0.9153
incorrect_item_count: 0
missed_core_item_count: 10
extraction.attempts: 1
```

这是“扩大抽取上下文能够补救质量门槛失败”的最直接证据。增加 chunks 后：

- 模型获得了更完整的方法、实验和结果上下文；
- 错误项从 8 个降为 0，precision 从 0.5294 升至 1.0；
- recall 从 0.6429 升至 0.8438；
- F1 从不及格的 0.5806 升至 0.9153。

恢复后 `missed_core_item_count` 从 5 增至 10 并不矛盾。第二次抽取产生了更多正确原子项，Judge 同时识别了更多剩余遗漏；recall 的分母和分子都发生了变化。不能只比较遗漏项绝对数量，应联合检查 correct、incorrect、precision、recall 和 F1。

该案例还表明，上下文不足不仅造成遗漏，也可能造成误解和过度概括。增加证据页面同时改善了召回率和准确率。

### 4.3 `2_19`：第二个无效 JSON 恢复案例

初次失败：

```text
error_message: DeepSeek returned invalid JSON content
selected_chunks: 4 / 15
```

恢复结果：

```text
selected_chunks: 8 / 15
precision: 0.9773
recall: 0.8958
F1: 0.9348
incorrect_item_count: 1
missed_core_item_count: 5
extraction.attempts: 1
```

这进一步说明，无效 JSON 不应被视为论文不可抽取。对于一次性的 JSON 生成失败，定向重跑具有较高成功率。若频繁出现，则应进一步检查：

- 输出 token 上限是否导致截断；
- provider 的 `finish_reason` 是否为 `length`；
- prompt 和 schema 是否过于复杂；
- 模型是否在 JSON 前后输出了额外文字；
- provider 是否实际保证 JSON object 格式。

### 4.4 `3_10`：跨 StudyUnit 引用错误后恢复

初次运行经过两次校验后仍失败：

```text
Model output failed v2 validation after 2 attempts:
Claim C5 references results outside its StudyUnit: ['R6', 'R7']
```

这是语法上有效但语义结构非法的 JSON：Claim 的 `inference_basis_ids` 只能引用同一个 StudyUnit 内的 Result。

恢复运行选择 8 个 chunks，最终结果为：

```text
precision: 1.0
recall: 0.94
F1: 0.9691
incorrect_item_count: 0
missed_core_item_count: 3
extraction.attempts: 1
```

恢复后的第一次抽取即通过校验。因此，成功主要来自重新生成了一份结构一致的 packet；增加上下文可能帮助模型更清楚地区分实验单元及其结果归属。增加验证重试次数仍有价值，但在该次成功记录中没有实际消耗额外尝试。

### 4.5 `2_13`：重复运行无效，必须修正评价协议

`2_13` 是一页作者勘误，不包含研究问题、方法、实验结果或研究 claim。模型连续三次都给出了空抽取，但旧代码均报错：

```text
semantic quality evaluation requires extracted items
```

这不是模型失败，而是质量评价协议把“没有抽取项”错误等同于“抽取失败”。重复运行无法改变文档本身没有研究内容的事实。

提交 `06d5b70`（`fix(odracir): score audited empty nonstudy packets`）进行了两项关键修复：

1. 移除“语义质量评估必须至少有一个 extracted item”的硬限制；
2. 当抽取项和遗漏项都为零时，将 precision 和 recall 定义为 1.0。

修复后，Judge 使用完整的一页文档审计空抽取，没有发现错误项或遗漏项：

```text
incorrect_item_count: 0
missed_core_item_count: 0
precision: 1.0
recall: 1.0
F1: 1.0
```

该案例确立了一个重要原则：只有在完整源文档审计确认不存在目标科学信息时，空抽取才应被视为完整，而不能对任意空输出直接赋满分。

## 5. 哪些恢复措施真正起作用

### 5.1 定向重跑，而不是全量重跑

恢复只针对失败论文进行，成功论文保持不变。这能够：

- 减少 API 成本和运行时间；
- 避免成功论文因 provider 非确定性产生不必要变化；
- 清晰保留初始失败与恢复成功之间的对应关系；
- 让失败原因、参数变化和恢复效果可以逐篇审计。

### 5.2 从 4 chunks 增加到 8 chunks

这是本批次恢复中最有实证支持的参数变化，尤其适用于：

- recall 低或遗漏核心方法、实验、结果；
- 上下文不足导致的错误概括；
- 复杂论文中 StudyUnit、Result 和 Claim 的归属混乱。

但不应机械地把所有论文都扩展到全部页面。过大的 prompt 会增加：

- 上下文超限风险；
- 输出截断风险；
- 成本和延迟；
- 注意力分散和结构混乱。

更理想的长期方案是使用 Judge 报告的 `missed_core_items.source_chunk_id` 定向选择遗漏页面，而不是简单扩大到固定数量。

### 5.3 将 `validation_retries` 增加到 3

更高的重试预算可以缓解结构化抽取阶段的：

- 无效 JSON；
- schema 字段错误；
- provenance 错误；
- ID 和跨字段引用错误；
- 临时连接、超时或限流。

需要注意旧版 2.2 的作用域：`validation_retries` 只包围
`extract_paper_study` 的结构化抽取和结构修复，不包围后续的全文语义质量
Judge。若主抽取已经成功、Judge 的 provider 响应却是无效 JSON，旧代码会直接让
整篇失败；下一次人工恢复会从主抽取重新开始。`2_2_version_228` 的 `9_2`
证明这会造成显著的重复成本。后文第 12.4 节给出证据和对应代码修正。

但是，本批恢复后的成功记录均显示 `extraction.attempts=1`。因此，不能把成功主要归因于三次校验重试。它更像风险缓冲：如果恢复运行第一次仍失败，系统还有机会自动修复。

### 5.4 修正系统性协议错误

当相同输入重复产生相同且语义合理的输出，而失败来自固定代码规则时，应停止盲目重跑。`2_13` 连续三次失败就是典型信号。

此类问题应通过以下步骤处理：

1. 检查文档类型和原始全文；
2. 判断模型输出是否实际上正确；
3. 明确评价指标在边界条件下的数学语义；
4. 修改代码并增加回归测试；
5. 对受影响论文重新审计，而不是直接绕过质量门槛。

## 6. 推荐的失败分类与恢复决策

### 6.1 高概率可直接恢复

以下情况适合先进行一次定向重跑：

- `DeepSeek returned invalid JSON content`；
- 空响应或偶发 provider 连接错误；
- `finish_reason=length` 导致的输出截断；
- 一次性的字段缺失、类型错误或 ID 冲突；
- provenance 页码、paraphrased 标记等可修正问题。

推荐动作：

```text
保留失败记录
-> 检查 finish_reason 和 error_message
-> 必要时提高 max_tokens
-> validation_retries 提高到 3
-> 使用新的恢复输出目录定向重跑
```

### 6.2 需要扩大或优化上下文

以下情况优先调整 chunk 策略：

- F1 低于质量门槛且 recall 明显偏低；
- `missed_core_item_count` 较高；
- Judge 指出的遗漏集中在未选页面；
- Claim、Result、Method 的关系因上下文不足而混乱。

推荐动作：

```text
查看 missed_core_items 的 source_chunk_id
-> 优先加入对应页面
-> 其次将 max_chunks 从 4 增至 8
-> 重新抽取并使用全文重新评审
```

### 6.3 不能靠重复运行解决

以下情况必须先修复外部条件或系统逻辑：

- 扫描 PDF 没有可抽取文本：先 OCR；
- PDF 损坏或加密：先修复或解密；
- API Key、权限、模型访问或余额问题：先修配置；
- chunk 缓存损坏或与 paper ID 不一致：重建缓存；
- 非研究文档的正确空抽取被规则拒绝：修正评价协议；
- 同一确定性错误连续多次出现：检查代码或 prompt 约束，不要继续盲目付费重跑。

## 7. 推荐的恢复记录规范

一次可审计恢复至少应保留：

- 初始失败的完整 `PaperRunRecord`；
- 失败阶段、异常类型和原始错误消息；
- 初始与恢复时的 `max_chunks`、`max_tokens`、`validation_retries`；
- provider、模型、finish reason、token、延迟和成本；
- 恢复后的 precision、recall、F1、错误项和遗漏项数量；
- 恢复 packet 的实际相对路径和内容摘要；
- 恢复策略及其原因；
- 未计量调用造成的成本下界说明。
- 失败发生在 extraction 还是 quality Judge，而不能只保留模糊的
  `invalid JSON`；
- 无效响应的 finish reason、字符数、内容摘要哈希和 JSON 解析位置，但默认不落盘
  原始响应正文；
- 每个阶段的失败调用 token 使用量，以及 usage 是否完整。

初始失败记录不应被覆盖。最终主报告可以选择恢复后的成功记录，但必须通过单独的 `recovery_attempts.jsonl` 或等价审计文件保留历史失败，并在总成本中计入所有已知尝试。

## 8. 当前快照发现的交付一致性问题

Group 2 的报告存在一项需要单独处理的完整性问题：

- `papers.jsonl` 将 `2_13` 标记为 `succeeded`；
- `summary.json` 声明该组 `20/20` 成功；
- `RECOVERY.md` 声明成功 packet 已合并；
- 但当前仓库的 Group 2 `packets/` 目录只有 19 个 JSON，缺少 `2_13.json`；
- `papers.jsonl` 中的 `output_file` 仍指向历史迁移前的绝对路径。

因此，可以确认 `2_13` 的评价逻辑已经修复，报告也记录了成功评审，但不能据当前快照断言其最终 packet 已完整交付。后续正式发布前应：

1. 从原始运行位置找回并校验 `2_13.json`，或使用当前代码重新生成；
2. 将 packet 放入规范的版本化运行目录；
3. 更新相对路径元数据，而不是依赖旧机器绝对路径；
4. 重新核对 packet 数量、报告成功数和内容摘要；
5. 保留历史报告，不通过静默修改掩盖迁移遗漏。

## 9. 后续架构改进建议

### 9.1 自动质量驱动的第二轮抽取

当前流程在 F1 不达标后直接失败，没有利用 Judge 已经返回的遗漏位置。建议增加受控恢复阶段：

```text
初次抽取
  -> 全文 Judge
  -> 若 recall/F1 不达标
  -> 收集 missed_core_items.source_chunk_id
  -> 对遗漏 chunks 定向补抽
  -> 与初次 packet 做确定性合并
  -> 再次全文 Judge
  -> 最多执行一次或两次
```

这样可以减少固定地从 4 扩大到 8 所带来的冗余成本。

### 9.2 区分生成失败、校验失败和质量失败

恢复策略应由失败类别驱动：

| 类别 | 典型表现 | 建议恢复策略 |
|---|---|---|
| Provider/JSON 失败 | 空响应、无效 JSON、超时 | 原参数重试，必要时提高 token 上限 |
| Schema 失败 | 缺字段、重复 ID、非法引用 | 带错误反馈修复；复杂时扩大上下文后重抽 |
| Precision 失败 | incorrect items 多 | 收紧证据约束，减少推断，必要时更换模型 |
| Recall 失败 | missed core items 多 | 根据遗漏 chunk 定向补抽 |
| 输入失败 | OCR、损坏、加密 | 修复输入后再跑 |
| 协议失败 | 正确边界输出被规则拒绝 | 修改代码并增加回归测试 |

### 9.3 避免只用 F1 门槛掩盖偏科

单一 F1 门槛可能允许 precision 很高但 recall 较低的结果通过，例如恢复后的 `1_10`：

```text
precision = 1.0
recall = 0.7241
F1 = 0.84
```

后续可考虑同时设置：

- 最低 precision；
- 最低 recall；
- 最低 F1；
- 对关键方法、主要数据集和核心实验的必备覆盖检查。

是否采用更严格门槛，应先通过人工标注集校准，不能仅依据少量正式运行样本决定。

## 10. 结论

`2_2_version_71` 的历史结果证明，初次失败论文通常可以恢复，但必须区分原因：

- **无效 JSON**：定向重跑成功率高；增加重试预算属于合理保险。
- **召回不足或上下文不足**：扩大或定向补充 chunks 是最有效的措施。
- **结构引用错误**：重新生成可以恢复，更多上下文可能改善实体归属。
- **确定性的协议边界错误**：重复运行无效，必须修正代码和评价定义。

在 `2_2_version_71` 的普通论文恢复记录中，共同操作是将 `max_chunks` 从 4
增加到 8，并把 `validation_retries` 增加到 3；但最终成功记录均只用了一次
extraction attempt。因此，该批历史证据更支持以下判断：

> 恢复成功的核心是针对失败类型重新生成，并在需要时扩大有效证据范围；增加重试次数提供容错，但不是本批成功的主要直接原因。

后续应把这套人工恢复经验固化为“失败分类、定向补抽、重新评审、完整审计”的自动化恢复流程。

## 11. `2_2_version_228` 大规模正式运行补充

### 11.1 运行范围与输入前检

2026-07-22 使用 `deepseek-v4-pro` 完成了
`data/formal_outputs/2_2_version_228`。本轮输入为 228 篇 PDF、17 个组、
累计 5265 页。两篇原扫描件被替换后，228 篇均满足：

- PDF 可打开且页数非零；
- 能抽取非空文本；
- 文件名、组号和 paper ID 一致；
- 组内没有字节级重复；
- API、模型、输出目录和费用参数在正式运行前经过真实 smoke test。

因此，本轮没有 PDF 损坏、加密、OCR 缺失或空文档输入失败。这个结果再次说明：
输入前检应作为 API 批处理的硬门，而不是让不可恢复输入进入付费生成阶段。

同源 smoke test 曾成功生成 `short/1/1_1`，其 PDF SHA-256 与正式输入完全相同。
正式首轮中该篇偶发返回无效 JSON，因此最终直接复用了这份已经通过相同 schema、
质量门槛和源哈希核验的 smoke packet，并把它放回正常的
`short/1/1_1.json` 位置；smoke 报告作为独立恢复证据保留。

### 11.2 首轮失败分布

首轮使用 `max_chunks=4`、`validation_retries=1`。结果为 192/228 成功，
首轮成功率 84.21%，36 篇失败：

| 首轮失败类别 | 篇数 | 占首轮失败比例 | 典型表现 |
|---|---:|---:|---|
| Provider/无效 JSON | 27 | 75.00% | `DeepSeek returned invalid JSON content` |
| 语义 F1 低于 0.6 | 7 | 19.44% | 低 precision、低 recall 或两者兼有 |
| 结构引用错误 | 2 | 5.56% | Claim 跨 StudyUnit 引用 Result |
| 输入失败 | 0 | 0% | 无 |

首轮墙钟时间约 43 分钟。报告能够确认的首轮费用为 5.01226150 美元。
需要注意，旧报告中的 `invalid JSON` 文本没有直接写明失败发生在主抽取还是语义
Judge；必须联合查看 `extraction` 和 `quality_judge` 阶段字段才能定位。

### 11.3 分轮恢复结果

`1_1` 由同源 smoke packet 补齐后，其余 35 篇进入受控恢复。第一轮遵循历史经验，
使用 `max_chunks=8`、`validation_retries=3`，没有重跑任何首轮成功论文：

| 阶段 | 待处理 | 本轮成功 | 剩余 | 说明 |
|---|---:|---:|---:|---|
| 同源 smoke 归位 | 1 | 1 | 35 | 不重复调用 API |
| 恢复第 1 轮 | 35 | 23 | 12 | 8 chunks、3 次结构校验重试 |
| 恢复第 2 轮 | 12 | 7 | 5 | 先分类，再保持 8/3 独立重生成 |
| 恢复第 3 轮 | 5 | 4 | 1 | 只处理仍缺失论文 |
| `9_2` 诊断运行 | 1 | 1 | 0 | 单篇、单次独立诊断轨迹 |

第一轮恢复后的 12 个剩余项可进一步分成：9 个无效 JSON、2 个反复结构引用
错误、1 个高 recall 但低 precision。这个分类决定了第二轮没有机械增加到
12 或 16 chunks：无效 JSON 继续独立重生成，结构错误重新生成完整结构，低
precision 项则避免继续无条件扩大上下文。

恢复审计共保留 53 条正式恢复尝试记录，外加 1 条同源 smoke 记录。所有成功
packet 都直接插入正常的 `long/<group>/` 或 `short/<group>/` 交付队列；恢复目录
只保存报告和审计，不保存另一套“最终 packet”。

### 11.4 最终交付、质量、时间与费用

最终结果为：

- 228/228 PDF 均有唯一对应 JSON；
- 228 个 JSON 全部通过 `PaperStudyPacketV2` 2.2 schema；
- 文件名、`paper_id`、组号和当前 PDF SHA-256 全部一致；
- 228 个 packet 均为 `accepted`；
- 最低 F1 为 0.6176，平均 F1 为 0.9600，最高为 1.0；
- 正式运行至最终恢复完成约 1 小时 19 分 49 秒；包含 smoke test 约
  1 小时 22 分 28 秒。

按显式价格快照（输入 0.435 美元/百万 token、输出 0.87 美元/百万 token）统计：

| 阶段 | 已记录费用（美元） |
|---|---:|
| 首轮 | 5.01226150 |
| 同源 smoke | 0.03050176 |
| 恢复 | 1.70528348 |
| 合计下界 | 6.74804674 |

报告累计记录 13,306,166 tokens。但有 9 条失败记录没有保存 usage，错误文本至少
对应 22 次 API 调用。因此 6.74804674 美元是可审计下界，不是 provider 发票总额。
按其余 273 个已计量调用的单次费用分布估计，总费用中心值约 6.9859 美元，
四分位区间约为 6.9445–7.0479 美元；该估计不能替代账单。

最终权威文件为：

- `data/formal_outputs/2_2_version_228/reports/final_summary.json`；
- `data/formal_outputs/2_2_version_228/reports/final_manifest.jsonl`；
- `data/formal_outputs/2_2_version_228/reports/final_manifest.csv`；
- `data/formal_outputs/2_2_version_228/reports/recovery_manifest.json`；
- `data/formal_outputs/2_2_version_228/reports/recovery_attempts.csv`。

## 12. 本轮新增的逐类恢复认识

### 12.1 低 F1 恢复：8 chunks 有效，但效果不是线性的

本轮再次出现了 4 chunks 下明显低分、8 chunks 后恢复的案例：

| 论文 | 首轮 F1 | 最终 F1 | 最终恢复轮 |
|---|---:|---:|---:|
| `long/3/3_15` | 0.1364 | 1.0000 | 1 |
| `long/5/5_24` | 0.5424 | 0.8800 | 1 |
| `long/7/7_26` | 0.4074 | 1.0000 | 1 |
| `short/4/4_2` | 0.4400 | 1.0000 | 1 |
| `short/8/8_1` | 0.1111 | 1.0000 | 1 |
| `short/8/8_6` | 0.2727 | 1.0000 | 3 |

这支持“4→8 chunks 是合理的第一恢复动作”，但 `8_6` 直到第三次独立轨迹才
成功，说明上下文宽度不是唯一变量。模型生成轨迹、结构合法性和 Judge 响应格式
同样影响最终结果。不能把一次恢复后的高分全部解释为增加 chunks 的因果效果。

### 12.2 结构引用错误：内部修复耗尽后，独立重生成仍可能成功

`long/3/3_20` 和 `short/4/4_1` 的跨 StudyUnit 引用在第一轮恢复即成功。
更有启发性的是：

- `long/4/4_24` 在恢复第 1 轮经过 4 次内部校验仍有跨单元引用，但第 2 轮
  独立生成成功；
- `long/6/6_11` 首轮先表现为 F1=0.2069，恢复第 1 轮转为结构引用错误，
  第 2 轮独立生成成功。

所以“同一运行内多次结构修复失败”不自动等同于代码缺陷。合理做法是保留完整
错误反馈后再允许一次独立重生成；若独立轨迹仍稳定复现相同约束错误，再升级为
prompt、确定性修复或 schema 设计问题。

### 12.3 `7_25`：高 recall、低 precision 不应继续盲目加 chunks

`long/7/7_25` 的第一次恢复得到：

```text
precision = 0.1633
recall = 0.8889
F1 = 0.2759
```

这不是上下文不足型失败。继续扩到更多 chunks 可能带来更多误抽取和更高成本。
第二次轨迹返回无效 JSON，第三次在相同 8-chunk 配置下得到 P=R=F1=1.0。
这个案例表明，恢复分类必须至少区分 precision 和 recall：低 recall 才优先补充
证据范围；低 precision 优先重新约束证据和推断，而不是无条件扩大上下文。

### 12.4 `9_2`：错误消息相同，但实际失败阶段不同

`short/9/9_2` 是本轮最重要的新案例。首轮及前三次恢复均记录
`DeepSeek returned invalid JSON content`，但这些失败记录同时具有完整
`extraction` 指标、没有 `quality_judge` 指标。这说明主抽取已经成功，异常发生在
随后语义 Judge 的 provider 调用，而不是主抽取。

其中两次恢复的主抽取已经消耗 5 次 extraction attempts，随后 Judge 的一次无效
JSON 又让整篇失败。下一轮人工恢复只能从 PDF 重新抽取，形成不必要的重复成本。
`9_2` 的已记录费用下界累计达到 0.26434645 美元，约为全批已记录单篇平均费用的
8.9 倍，且仍不包含 Judge 无效响应丢失的 usage。

最后一次诊断运行没有降低任何门槛：主抽取通过一次结构 fallback 在 2 个 attempts
内成功，Judge 第一次响应也成功，最终得到：

```text
precision = 0.9857
recall = 0.8961
F1 = 0.9388
```

因此，`9_2` 不是不可抽取论文，也没有稳定的 JSON 语法故障；它暴露的是旧架构中
“主抽取有 provider 重试、Judge 没有 provider 重试”的阶段不对称。恢复系统如果
只看最终错误字符串，会把一个应在 Judge 本地重试的问题误判成整篇重抽问题。

## 13. 对恢复决策树的修订

### 13.1 先定位阶段，再分类错误

对独立论文报告建议使用以下定位规则：

| 报告状态 | 更可能的失败阶段 | 动作 |
|---|---|---|
| `extraction=null` | 主抽取/provider/结构前段 | 查看 provider 与结构错误 |
| `extraction!=null`、`quality_judge=null`、错误为无效 JSON | Judge provider | 只重试 Judge，不重抽论文 |
| `quality_score!=null` 且低于门槛 | 语义质量门 | 按 precision/recall 决策 |
| packet 已生成但 merge 缺失 | 交付一致性 | 校验 SHA/schema 后原子归位 |

长期应增加显式 `failure_stage` 字段，而不是让使用者从空字段组合推断。

### 13.2 重试预算必须是阶段本地的

- 主抽取的 provider/JSON 重试应只重做当前结构化调用；
- 结构 payload 已存在时应使用带错误反馈的 repair，而不是重新读 PDF；
- Judge 的 provider/JSON 重试应只重做 Judge；
- 质量不达标才进入 chunk 调整或定向补抽；
- 独立整篇重生成是上一层恢复动作，不能代替每个阶段自己的局部重试。

### 13.3 独立重生成必须有上限和停机条件

本轮证明独立轨迹能够解决偶发 JSON 和结构问题，但也证明没有上限会导致单篇成本
膨胀。建议默认：一次 8/3 受控恢复；剩余项分类后最多再允许一次同类独立轨迹。
若仍失败，应进入诊断模式并检查阶段、finish reason、响应诊断和 source 类型，
而不是自动升级到 12、16 chunks 或无限循环。

### 13.4 最终交付与恢复审计必须分离

恢复成功的 packet 应直接进入正常版本化队列，且不得覆盖已有成功文件；恢复目录只
保存新 run report、参数、成本、失败历史和 merge audit。最终发布必须另建一份
输入—输出清单，逐一核对 PDF SHA、packet SHA、schema、paper ID、质量分和路径。

## 14. 已落地的代码改进

基于本轮问题，当前代码已做以下改进：

1. `ProviderResponseError` 在不保存原始响应正文的前提下，保留 usage、
   finish reason、响应字符数、SHA-256 和 JSON 解析位置；
2. 主抽取 provider 重试或 schema/结构校验耗尽后，通过带遥测的 extraction-stage
   异常把累计 usage 和 attempts 写回失败报告，不再把已付费调用全部记为零；
3. 语义质量 Judge 现在会在本阶段内重试 provider/无效 JSON，并累计两次调用的
   usage；若仍失败，报告保留 `quality_judge` 阶段遥测，不重新触发主抽取；
4. 阶段、论文记录和 run summary 增加 usage 完整性；缺失 usage 时显式把费用标为
   lower bound，避免把未知费用误报成精确的 0；
5. 汇总 token 数统一由 prompt+completion 重算，避免混合响应中部分缺少
   `total_tokens` 时低估；
6. 新增 `scripts/recover_independent_run.py`，将本轮临时流程固化为通用的单组恢复
   工具。

该脚本具有以下保护：

- 只选择原 `papers.jsonl` 中状态为 failed 的论文；
- 默认 8 chunks、3 次结构校验重试；
- 使用全新 work/report 目录，保留原报告；
- 当前 PDF SHA 与失败报告不一致时默认停止，替换输入必须显式确认；
- 成功 packet 重新通过 schema、paper ID、source SHA 和质量门槛核验；
- 使用原子、禁止覆盖的方式补入正常 delivery 目录；
- `recovery.json` 单独记录尝试、参数、失败和最终交付路径。

示例：

```bash
PYTHONPATH=src .venv/bin/python scripts/recover_independent_run.py \
  --source-report data/formal_outputs/2_2_version_228/reports/long/2/papers.jsonl \
  --paper-folder data/formal_corpus/long/2 \
  --delivery-folder data/formal_outputs/2_2_version_228/long/2 \
  --work-folder /tmp/odracir-long-2-recovery-attempt-1 \
  --report-folder data/formal_outputs/2_2_version_228/reports/recovery/long/2/attempt_1 \
  --env-file .env \
  --max-chunks 8 \
  --validation-retries 3 \
  --minimum-quality-score 0.6
```

相关回归测试覆盖：无效 JSON usage 保留、schema 校验耗尽后的 usage 保留、Judge
局部重试、Judge 重试耗尽后的遥测、恢复 packet 原子归位、已有交付不被覆盖、
输入 SHA 变化默认拒绝。

## 15. 更新后的推荐正式流程

```text
PDF/OCR/命名/SHA 前检
  -> 小规模真实 API smoke
  -> 首轮 4-chunk 独立抽取
  -> 按 failure_stage + error_class 分类
  -> Provider/JSON：阶段本地重试
  -> Schema：带错误反馈修复；必要时一次独立重生成
  -> Recall：优先定向加入 missed chunks，其次 4->8
  -> Precision：收紧证据和推断，不自动扩大 chunks
  -> Input/协议：停止付费重跑，先修输入或代码
  -> 成功 packet 原子补入正常队列
  -> 保留恢复审计
  -> 逐 PDF 做最终 manifest、schema、SHA、质量与数量核验
```

## 16. 更新后的结论

`2_2_version_228` 将早期 5 篇案例扩展成了 228 篇、53 条恢复尝试的正式证据。
最重要的新结论不是“多重跑几次就会成功”，而是：

- 失败必须精确定位到 extraction、schema、Judge、质量门或交付层；
- 8 chunks 是低覆盖恢复的有效第一选择，但不是对所有失败的通用答案；
- Judge 的无效 JSON 必须在 Judge 本地恢复，不能让整篇从头重抽；
- 独立重生成有效但必须有预算和诊断停机条件；
- usage、finish reason 和安全响应诊断是成本审计的一部分；
- 最终 packet 只有一套正常队列，恢复历史另存审计，二者不能混为一谈。

这使恢复从“人工观察失败后重新运行”升级为可分类、可限额、可归位、可核验、
可审计的正式交付流程。
