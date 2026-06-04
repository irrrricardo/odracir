# Odracir Roadmap / 路线图

This roadmap records the next practical steps after the `0.3.1` read workflow.
It is intentionally execution-oriented: each milestone should produce a visible
artifact, a test, or a real-folder verification result.

本文档记录 `0.3.1` 高层阅读流程之后的下一步。它偏向可执行计划：每个里程碑都应
产出可见 artifact、测试，或真实文件夹验证结果。

## Current Baseline / 当前基线

- `odracir read` can process a small real paper folder end to end.
- `odracir brief` can generate `project_summary.md` from folder memory.
- Built-in research skills are `generic@0.1` and `biomedical-paper@0.1`.
- Raw model output can be preserved and normalized later.
- Summary review, evaluation artifacts, and ingestion run artifacts are auditable.
- Collaboration is now branch-based: contributors can work on feature branches,
  test locally, then merge into `main`.

- `odracir read` 已经可以端到端处理小型真实论文文件夹。
- `odracir brief` 可以从文件夹记忆生成 `project_summary.md`。
- 当前内置科研 skill 为 `generic@0.1` 和 `biomedical-paper@0.1`。
- 原始模型输出可以被保留，并在之后规范化。
- 摘要审阅、评估 artifact 和摄取运行 artifact 已具备可审计性。
- 协作方式已经进入分支开发：贡献者可以在 feature branch 上开发、本地测试，
  再合并进入 `main`。

## Guiding Rules / 推进原则

- Keep `main` runnable and documented.
- Prefer real-folder smoke tests before declaring a workflow useful.
- Add domain skills only when they improve extraction or evaluation criteria,
  not just because a new label is attractive.
- Keep generated research-folder state out of Git.
- Preserve source evidence and provenance before adding UI or automation layers.

- 保持 `main` 可运行、文档同步。
- 宣称某个流程可用之前，优先跑真实文件夹 smoke test。
- 只有当新领域 skill 能改善提取或评估标准时再添加，而不是为了多一个标签。
- 不把生成的研究文件夹 state 提交进 Git。
- 在 UI 或自动化层之前，先保证来源证据和 provenance 可追踪。

## Milestone 1: Collaboration Hygiene / 里程碑 1：协作规范

Goal: make user and collaborator changes easy to review and recover.

目标：让用户和合作者的修改容易 review、合并和回滚。

Deliverables:

- Add a short contributor workflow: branch naming, PR review, local test command,
  and when direct `main` commits are acceptable.
- Add a PR checklist template or equivalent Markdown checklist.
- Document the real-folder smoke-test pattern:
  `read --dry-run`, real `read`, `status`, `evaluate-summaries`, inspect brief.

Acceptance:

- A new contributor can read one document and know how to submit a safe change.
- The checklist mentions tests, docs, privacy audit, and generated-state files.

## Milestone 2: Skill System Expansion / 里程碑 2：skill 体系扩展

Goal: make domain skills scalable before adding many built-in fields.

目标：在大量添加领域字段之前，先让 skill 扩展方式稳定。

Deliverables:

- Define a clear skill manifest contract: name, version, instructions,
  domain namespace, schema extension, evaluation rules, and examples.
- Decide whether external skills should be loaded from JSON/YAML/Markdown files
  in addition to built-in Python manifests.
- Add at least one non-biomedical pilot skill, preferably `computer-science-paper`
  or `review-paper`, because current test folders already include AI/LLM papers.
- Add fixture tests showing that switching skills invalidates stale summaries and
  changes expected domain fields.

Acceptance:

- `odracir skills` can show the new skill.
- A real or fixture paper can be summarized with the new skill.
- `evaluate-summaries` reports meaningful field coverage for that skill.

## Milestone 3: Reading Quality Loop / 里程碑 3：阅读质量闭环

Goal: make summary quality easier to inspect and improve without rerunning the
whole library blindly.

目标：让摘要质量更容易检查和改进，而不是盲目重跑整个论文库。

Deliverables:

- Improve warning categories so review papers, clinical trials, method papers,
  and non-biomedical AI papers do not all look like the same warning.
- Add a compact command or report for "what should I review next?"
- Record human review decisions in a way that `project_summary.md` can display.
- Add a small sample-output directory or sanitized fixture showing expected
  `project_summary.md` structure.

Acceptance:

- Warnings distinguish missing evidence, wrong skill choice, weak field coverage,
  and real validation errors.
- A user can identify the next paper or summary requiring attention in one command.

## Milestone 4: Usability Defaults / 里程碑 4：易用默认值

Goal: reduce command friction for ordinary research folders.

目标：减少普通研究文件夹的命令负担。

Deliverables:

- Improve folder-layout detection or prompts around `--papers-dir "."` versus
  the default `papers/`.
- Add clearer status output when zero papers are found.
- Consider a `--yes` or guided mode later, but keep the CLI deterministic first.
- Add setup documentation for virtual environments and dependencies.

Acceptance:

- If PDFs are directly under the root, users get an actionable suggestion.
- A fresh environment setup can be completed from documented commands.

## Milestone 5: Agentic Layer / 里程碑 5：agentic layer

Goal: turn the reliable CLI workflows into callable agent tools.

目标：把可靠的 CLI 工作流转化成 agent 可调用工具。

Deliverables:

- Expose `read`, `brief`, summary review, and skill inspection as safe tool
  operations with explicit API-spending boundaries.
- Add a lightweight planner that proposes actions before spending API calls.
- Keep every tool auditable: command, inputs, outputs, artifact paths, failures.

Acceptance:

- The agent can explain what it plans to run before paid calls.
- The same result can be reproduced from recorded CLI commands.

## Milestone 6: UI Or Service Boundary / 里程碑 6：UI 或服务边界

Goal: prepare for a future local app or web UI without destabilizing the core.

目标：为未来本地应用或网页 UI 做准备，同时不破坏核心流程。

Deliverables:

- Define a thin service boundary around research folders, papers, summaries,
  reviews, and briefs.
- Keep PDF parsing and model calls behind existing tool/provider interfaces.
- Build UI only after the CLI outputs and artifacts are stable enough.

Acceptance:

- A UI can call documented commands or service functions without reimplementing
  parser, provider, or summary logic.

## Immediate Next Actions / 立即下一步

Recommended order:

1. Add collaboration checklist and PR habit documentation.
2. Add one non-biomedical pilot skill, likely `computer-science-paper` or
   `review-paper`.
3. Improve warning categories so the Articles smoke test produces more useful
   review guidance.
4. Add better folder-layout detection for root-level PDFs.
5. Only then start designing a local UI or service layer.

建议顺序：

1. 补协作 checklist 和 PR 习惯文档。
2. 添加一个非生物医学 pilot skill，优先考虑 `computer-science-paper` 或
   `review-paper`。
3. 改进 warning 分类，让 Articles smoke test 给出更有用的审阅建议。
4. 改进根目录 PDF 的文件夹布局识别。
5. 之后再开始设计本地 UI 或服务层。
