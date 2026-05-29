# Changelog / 版本记录

This file records meaningful changes to Odracir.

本文件用于记录 Odracir 的重要版本变化、设计演进和阶段性计划。

The format loosely follows Keep a Changelog, but stays practical for a personal research agentic system.

本文件大致参考 Keep a Changelog 的风格，但会优先服务于个人科研 agentic system 的实际迭代。

## [Unreleased] / 未发布

### Planned / 计划

- Add a research-folder scanner.
- Add PDF text extraction.
- Design the first `odracir_index.json` schema.
- Add paper translation and structured summary tools.
- Add retrieval over paper records and extracted text.
- Add a research conversation agent that can use folder-level evidence.

- 添加研究文件夹扫描器。
- 添加 PDF 文本提取能力。
- 设计第一版 `odracir_index.json` schema。
- 添加论文翻译和结构化摘要工具。
- 添加基于论文记录和提取文本的检索能力。
- 添加能够使用文件夹级证据的科研交流 agent。

## [0.1.0] - 2026-05-30 / 初始版本

### Added / 新增

- Created the initial Odracir project structure.
- Added DeepSeek API configuration through an OpenAI-compatible client.
- Added a minimal agent loop with tool calling.
- Added a small tool registry with example project-planning tools.
- Added a command-line entry point.
- Added initial unit tests for tool execution.
- Added English and Chinese README files describing Odracir as a personal research agentic system.
- Added this changelog file for future version tracking.

- 创建 Odracir 初始项目结构。
- 通过 OpenAI-compatible 客户端添加 DeepSeek API 配置。
- 添加支持工具调用的最小 agent loop。
- 添加小型工具注册表和示例项目规划工具。
- 添加命令行入口。
- 添加工具执行相关的初始单元测试。
- 添加英文和中文 README，将 Odracir 定位为个人科研 agentic system。
- 添加本版本记录文件，用于后续版本追踪。

### Notes / 记录

- The project is intentionally still a single-agent prototype.
- The first real milestone is not multi-agent orchestration, but a reliable loop for paper intake, structured summary, and folder-level memory.
- GitHub publishing still requires a GitHub remote and authentication on the local machine.

- 当前项目仍然刻意保持为单 agent 原型。
- 第一个真实里程碑不是多 agent 编排，而是跑通论文收纳、结构化摘要和文件夹级记忆的可靠闭环。
- 推送到 GitHub 仍需要本地配置 GitHub 远程仓库和认证。
