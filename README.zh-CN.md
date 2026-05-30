# Odracir

[English](README.md) | 中文

[版本记录](CHANGELOG.md)

[工作流](WORKFLOW.md)

[架构路线图](ARCHITECTURE.md)

<!-- ODRACIR_STATUS_START -->
## 项目状态

此区块由 `odracir sync-docs` 自动生成。

- 版本：`0.1.0`
- 阶段：带有解析器注册表、可追溯 chunk 和本地检索的模块化单 agent 原型
- 当前重点：可靠收纳、OCR 检测、按页可追溯 chunk 和带证据检索
- 最近同步：`2026-05-30T16:25:14+08:00`

当前命令：

- `odracir "message"`：与当前 Odracir agent 对话。
- `odracir scan <research-folder>`：为研究文件夹创建或更新 `odracir_index.json`。
- `odracir scan <research-folder> --papers-dir <paper-folder>`：扫描已有的自定义论文文件夹。
- `odracir extract <research-folder>`：将 PDF 正文提取到 `.odracir/texts/`。
- `odracir status <research-folder>`：报告处理状态、OCR 需求和失败项。
- `odracir chunk <research-folder>`：在 `.odracir/chunks/` 中创建可追溯 chunk。
- `odracir search <research-folder> "<query>"`：检索 chunk 并返回页码级引用。
- `odracir sync-docs`：刷新自动生成的文档状态区块。

<!-- ODRACIR_STATUS_END -->


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

当前 harness 已经实现这个流程的第一层：创建文件夹布局，扫描 `papers/`，并用文件元数据和等待后续 agent 填写的空研究字段创建或更新 `odracir_index.json`。

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

扫描一个研究文件夹：

```powershell
odracir scan D:\Research\diffusion-models
```

这个命令会在需要时创建文件夹，确保 `papers/`、`notes/` 和 `code/` 存在，并写入或更新 `odracir_index.json`。

扫描一个已有的自定义论文文件夹：

```powershell
odracir scan "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

这个命令会把研究索引保存在 `Mecidal World Model` 文件夹中，同时从已有的 `Paper Storage` 文件夹读取 PDF。

提取 PDF 正文：

```powershell
odracir extract "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

这个命令会把按页提取的正文 artifact 写入 `.odracir/texts/`，并在 `odracir_index.json` 中更新提取状态、页数、文本长度和 artifact 路径。

查看处理状态、OCR 需求和失败项：

```powershell
odracir status "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

为成功提取的 PDF 创建稳定、按页可追溯的 chunk：

```powershell
odracir chunk "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" --papers-dir "Paper Storage"
```

Chunk artifact 会写入 `.odracir/chunks/`。重复运行时，未变化的正文 artifact 会被跳过。

检索本地 chunk，并返回可检查的论文与页码引用：

```powershell
odracir search "D:\大学课程资料\留学\暑研\NEU Wengong Jin\Mecidal World Model" "world model" --limit 3
```

刷新自动生成的文档状态区块：

```powershell
odracir sync-docs
```

## 文档同步

README 文件里包含一个由程序生成的项目状态区块，位于这些标记之间：

```text
<!-- ODRACIR_STATUS_START -->
## 项目状态

此区块由 `odracir sync-docs` 自动生成。

- 版本：`0.1.0`
- 阶段：带有解析器注册表、可追溯 chunk 和本地检索的模块化单 agent 原型
- 当前重点：可靠收纳、OCR 检测、按页可追溯 chunk 和带证据检索
- 最近同步：`2026-05-30T16:25:14+08:00`

当前命令：

- `odracir "message"`：与当前 Odracir agent 对话。
- `odracir scan <research-folder>`：为研究文件夹创建或更新 `odracir_index.json`。
- `odracir scan <research-folder> --papers-dir <paper-folder>`：扫描已有的自定义论文文件夹。
- `odracir extract <research-folder>`：将 PDF 正文提取到 `.odracir/texts/`。
- `odracir status <research-folder>`：报告处理状态、OCR 需求和失败项。
- `odracir chunk <research-folder>`：在 `.odracir/chunks/` 中创建可追溯 chunk。
- `odracir search <research-folder> "<query>"`：检索 chunk 并返回页码级引用。
- `odracir sync-docs`：刷新自动生成的文档状态区块。

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
6. 在解析器注册表后面添加可选的 Docling 和 OCRmyPDF 适配器。
7. 添加论文翻译和结构化摘要工具。
8. 使用可选 embedding 和更丰富排序扩展本地 chunk 检索。
9. 添加能够引用文件夹证据的交流 agent。
10. 添加阅读路径、复现和实验规划工具。
11. 在科研记忆稳定后添加代码辅助工具。
12. 只有当单 agent 的 prompt 变得过大或职责冲突时，才拆分为多个 agent。

## 设计原则

- 本地优先：研究文件夹即使没有远程数据库也应该可理解。
- 结构化记忆：重要信息应该写入 JSON，而不是只困在聊天历史里。
- 注重证据：回答应该尽可能指回论文或笔记。
- 增量构建：先搭好一个可靠闭环，再增加多个 agent。
- 个人化：优先优化一个人的科研速度、偏好和工作流。
