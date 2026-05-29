# Odracir

English | [中文](README.zh-CN.md)

[Changelog](CHANGELOG.md)

Odracir is a personal agentic system for quickly entering, understanding, and implementing work in a new research field. It is designed to help one person collect papers, translate and summarize them, extract structured knowledge, discuss the field with an agent, and gradually turn research understanding into executable plans and code.

The project currently targets the DeepSeek API through an OpenAI-compatible client interface.

## Product Goal

Odracir should become a research companion that can help you:

1. Build a local knowledge base from selected research papers.
2. Translate and summarize papers quickly.
3. Extract important concepts, methods, datasets, equations, experiments, limitations, and implementation clues.
4. Record paper-level information into a JSON index inside each research folder.
5. Chat with an agent that understands the accumulated papers.
6. Plan learning paths, experiments, reproduction steps, and code tasks.
7. Call code tools when implementation work is needed.

The first principle is practical acceleration: Odracir should help you enter a domain faster, not merely produce polished summaries.

## Initial Use Case

A typical research folder may look like this:

```text
research-folder/
  papers/
    paper-a.pdf
    paper-b.pdf
  notes/
  code/
  odracir_index.json
```

You place selected papers in `papers/`. Odracir reads them, produces translations and summaries, extracts structured information, and updates `odracir_index.json` so the folder gradually becomes a local research memory.

## Planned Capabilities

### Paper Intake

- Watch or scan a folder containing selected papers.
- Detect new PDFs or text documents.
- Extract title, authors, abstract, sections, references, and key figures when possible.
- Track whether each paper has already been processed.

### Translation and Summary

- Translate papers or selected sections into Chinese.
- Produce short, medium, and detailed summaries.
- Preserve technical terms and important equations.
- Highlight what is important for understanding and implementation.

### Structured Research Index

Each research folder should contain a JSON index, such as `odracir_index.json`, with structured records for all processed papers.

Possible fields:

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

### Research Conversation Agent

An agent should be able to:

- Answer questions using the papers already processed in the folder.
- Compare papers and explain relationships between ideas.
- Identify open questions and unresolved conflicts.
- Recommend what to read next.
- Help turn paper understanding into experiments or implementation tasks.

### Planning and Code Assistance

Odracir should later support:

- Reproduction planning.
- Environment setup planning.
- Code scaffolding.
- Experiment task decomposition.
- Debugging support.
- Calling local code tools when safe and useful.

## Proposed Agent Roles

The system can start with one agent and later split responsibilities when needed.

Initial single-agent role:

- `research_companion`: reads folder context, talks with the user, uses tools, and produces research or implementation guidance.

Possible future roles:

- `paper_intake_agent`: detects and processes new papers.
- `paper_summary_agent`: translates, summarizes, and extracts structured records.
- `research_memory_agent`: maintains and queries the folder-level JSON index.
- `planning_agent`: creates learning, reproduction, and implementation plans.
- `coding_agent`: helps scaffold code, run checks, and explain implementation details.
- `review_agent`: checks summaries, plans, and code for missing assumptions or weak evidence.

## Project Shape

```text
src/odracir/
  agent.py      # agent loop: model call, tool calls, final answer
  config.py     # DeepSeek provider configuration
  tools.py      # tool registry and example tools
  cli.py        # command-line entry point
tests/
  test_tools.py
```

Planned project shape:

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

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

Then edit `.env` and set `DEEPSEEK_API_KEY`.

## Run

```powershell
odracir "Help me plan a research assistant for reading papers about diffusion models."
```

Or:

```powershell
python -m odracir.cli "Help me summarize the current project goal."
```

## Development Roadmap

1. Keep the first version as a single agent with a small tool registry.
2. Add a folder scanner for research folders.
3. Add PDF text extraction.
4. Design and validate the first `odracir_index.json` schema.
5. Add paper translation and structured summary tools.
6. Add retrieval over the JSON index and paper text.
7. Add a conversation agent that can cite folder evidence.
8. Add planning tools for reading paths, reproduction, and experiments.
9. Add code assistance tools after research memory is stable.
10. Split into multiple agents only when the single-agent prompt becomes too large or conflicted.

## Design Principles

- Local-first: research folders should remain understandable without a remote database.
- Structured memory: important information should be written into JSON, not trapped only in chat history.
- Evidence-aware: answers should point back to papers or notes whenever possible.
- Incremental: build one reliable loop before adding multiple agents.
- Personal: optimize for one person's research speed, taste, and workflow.
