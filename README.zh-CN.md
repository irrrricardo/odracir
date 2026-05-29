# Odracir

[English](README.md) | 中文

[版本记录](CHANGELOG.md)

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
```

你把选好的论文放入 `papers/`。Odracir 读取它们，生成翻译和摘要，提取结构化信息，并更新 `odracir_index.json`，让这个文件夹逐渐变成一个本地科研记忆。

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

## 运行

```powershell
odracir "帮我规划一个用于阅读扩散模型论文的科研助手。"
```

或者：

```powershell
python -m odracir.cli "帮我总结当前项目目标。"
```

## 开发路线图

1. 将第一版保持为单 agent 加小型工具注册表。
2. 添加研究文件夹扫描器。
3. 添加 PDF 文本提取。
4. 设计并验证第一版 `odracir_index.json` schema。
5. 添加论文翻译和结构化摘要工具。
6. 添加基于 JSON 索引和论文文本的检索。
7. 添加能够引用文件夹证据的交流 agent。
8. 添加阅读路径、复现和实验规划工具。
9. 在科研记忆稳定后添加代码辅助工具。
10. 只有当单 agent 的 prompt 变得过大或职责冲突时，才拆分为多个 agent。

## 设计原则

- 本地优先：研究文件夹即使没有远程数据库也应该可理解。
- 结构化记忆：重要信息应该写入 JSON，而不是只困在聊天历史里。
- 注重证据：回答应该尽可能指回论文或笔记。
- 增量构建：先搭好一个可靠闭环，再增加多个 agent。
- 个人化：优先优化一个人的科研速度、偏好和工作流。
