# Hippocampus / 记忆脑区

`hippocampus` is the reserved memory brain region for Odracir Brain.

`hippocampus` 是 Odracir Brain 中预留的记忆脑区。

It is not the whole brain and it is not the future `orchestra`. The orchestra
will decide what to do, which agents or skills to use, and how to evaluate the
result. The hippocampus should provide durable, searchable, linked memory.

它不是整个大脑，也不是未来的 `orchestra`。`orchestra` 负责决定要做什么、调用哪些
agent 或 skill、如何评估结果。`hippocampus` 负责提供可持久化、可检索、可连接的记忆。

## Scope

The hippocampus can eventually manage:

- literature memory from papers and summaries
- conversation memory from user interactions
- project memory from decisions, roadmap, changelog, and run artifacts
- skill memory from prompt patterns, domain workflows, and reviewed examples
- user memory from preferences and repeated habits
- tool memory from environment facts, failures, and successful repairs
- logic memory from reusable rules and reasoning templates

未来 hippocampus 可以管理：

- 来自论文和总结的文献记忆
- 来自用户交流的对话记忆
- 来自决策、路线图、更新记录和运行 artifact 的项目记忆
- 来自 prompt 模式、领域 workflow 和已审阅样例的 skill 记忆
- 来自偏好和重复习惯的用户记忆
- 来自环境事实、失败和成功修复的工具记忆
- 来自可复用规则和推理模板的逻辑记忆

## Non-Goals

This placeholder does not implement RAG, embeddings, graph storage, or a database
yet. It only fixes the architectural name and boundary.

此占位暂不实现 RAG、embedding、图存储或数据库。它只固定架构命名和边界。

The hippocampus should not:

- make global orchestration decisions
- own provider selection
- bypass evidence and provenance requirements
- become a single unstructured dump of all memory

hippocampus 不应该：

- 做全局编排决策
- 负责 provider 选择
- 绕过证据和 provenance 要求
- 变成一个不分结构的巨大记忆堆

## First Implementation Target

The first real implementation should be a typed local memory substrate backed by
SQLite metadata, artifact files, lexical search, optional vector search, and
explicit graph links. The API should support `write`, `search`, `link`,
`retrieve_context`, `promote`, and `audit`.
