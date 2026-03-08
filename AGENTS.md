# AGENTS.md

## Purpose

This file gives Codex the working rules for this repository.

Follow this file before writing or modifying code.

---

## Read these files first

Read the project documents in this order before coding:

1. `doc/pre.md`
2. `doc/architecture.md`
3. `doc/schema.md`
4. `doc/agents.md`
5. `doc/tasks.md`

If there is any conflict between documents, use this priority order:

1. `doc/tasks.md`
2. `doc/schema.md`
3. `doc/architecture.md`
4. `doc/pre.md`
5. `doc/agents.md`

Do not invent requirements outside these files.

---

## Project goal

Build V1 of the Multi-Agent engineering implementation document generation system.

Core workflow:

1. Upload `.docx`
2. Parse requirement document
3. Generate TOC
4. Let user review and revise TOC
5. Freeze confirmed TOC
6. Generate content node by node
7. Run fact grounding, length control, consistency check
8. Generate images in lenient mode
9. Layout into Word using template styles
10. Export final `output.docx`

---

## Non-negotiable product rules

### Input format
- Officially support `.docx` only
- Do not add `.doc` support as a normal path

### TOC rules
- Minimum generation unit is adaptive level 3 or level 4
- Default to level 3 first
- Drill down to level 4 only when needed
- Once user confirms TOC, freeze it as `toc_confirmed`
- Do not allow TOC editing after generation starts
- If TOC must change after confirmation, create a derived task instead of mutating the current task

### Content rules
- Final node text hard minimum: `>= 1800`
- Recommended range: `1800–2200`
- If text is above `2200`, trim it
- Do not use Markdown syntax in generated Word body content

### Fact grounding
- The system must prevent unsupported factual claims
- Critical claims must be grounded in `requirement.json` or clearly classified as general engineering knowledge
- Fact grounding is required before image generation

### Image rules
- V1 uses engineering-practical image validation, not deep image understanding
- Image failure strategy is lenient mode
- If an image still fails after retries, mark it `NEED_MANUAL_CONFIRM`
- Do not block the whole node only because an image failed

### Formatting rules
- Use the styles from `standard_template.docx`
- Do not replace template styles with hardcoded styling
- Use `BiddingTable` for generated tables
- Create tables only when the content is actually structured enough

### Architecture rules
- React is frontend only
- Worker handles background execution
- SQLite stores metadata
- Local filesystem stores artifacts
- Do not collapse everything into a single long-running frontend script

---

## Current implementation scope

Implement V1 in small runnable increments.

Do this first:
- Project skeleton
- SQLite schema and repositories
- Services
- Orchestrator skeleton
- Worker skeleton
- React app skeleton
- Requirement Parser
- TOC Generator
- TOC Review
- TOC freeze flow

Do not implement the full image pipeline first.

Do not optimize concurrency early.

---

## Required first files

Create or complete these files first:

- `backend/models/enums.py`
- `backend/models/schemas.py`
- `backend/repositories/task_repository.py`
- `backend/repositories/toc_repository.py`
- `backend/repositories/node_state_repository.py`
- `backend/repositories/event_log_repository.py`
- `backend/app_service/task_service.py`
- `backend/app_service/toc_service.py`
- `backend/app_service/progress_service.py`
- `backend/orchestrator/orchestrator.py`
- `backend/worker/node_runner.py`
- `ui/src/App.jsx`

If some repository files are grouped differently, keep the intent but preserve clear separation of responsibilities.

---

## Implementation order

Work in this order unless the user explicitly asks for something else:

### Phase A
- enums
- schemas
- database initialization
- repositories
- services

### Phase B
- file upload
- requirement parser
- TOC generation
- TOC review
- TOC versioning
- TOC freeze
- task and node state machine skeleton

### Phase C
- worker loop
- checkpointing
- heartbeat
- event log
- progress calculation

### Phase D
- section writer
- fact grounding
- length control
- consistency check

### Phase E
- table builder
- layout
- word export

### Phase F
- image prompt
- image generation
- image relevance
- manual action UI

---

## Coding rules

### General
- Use Python
- Keep modules small and readable
- Prefer explicit types
- Prefer Pydantic models for structured data
- Prefer enums over loose strings
- Add docstrings where they help maintainability
- Do not create unnecessary abstractions early

### Data layer
- Follow `doc/schema.md`
- Keep metadata in SQLite
- Keep large generated artifacts on disk
- Use stable `node_uid` across TOC versions
- Allow `node_id` to change between versions

### Orchestrator
- State transitions must be explicit
- Illegal state transitions must be blocked
- Every stage must write event logs
- Every stable stage must write checkpoint data

### Worker
- Node execution is serial in V1
- Image generation inside one node may be parallel
- Keep retry logic bounded and explicit
- Update heartbeat during long-running steps

### UI
- UI must never own the core execution logic
- UI reads state from services
- Show total progress and node progress
- Show recent logs
- Show manual intervention states clearly

### Word export
- Use template styles
- Do not insert Markdown
- Keep layout deterministic
- Respect image anchor placement and fallback rules

---

## Testing rules

Add tests for all core behavior.

At minimum, include:
- schema validation tests
- repository tests
- state machine tests
- TOC versioning tests
- checkpoint and resume tests
- one end-to-end smoke test

Do not leave critical flows untested.

---

## How to work on a task

Before writing code:

1. Read the relevant docs
2. Summarize the implementation plan
3. List files to create or modify
4. State assumptions if anything is unclear

While coding:

1. Implement in small steps
2. Keep code runnable
3. Avoid touching unrelated files
4. Preserve existing contracts unless the docs require a change

After coding:

1. Summarize what was implemented
2. List files changed
3. List what is still stubbed or incomplete
4. Explain how to run or test the result

---

## What not to do

- Do not rewrite the architecture without being asked
- Do not add Docker first
- Do not add distributed queues first
- Do not add multi-user complexity first
- Do not add full deep multimodal understanding first
- Do not bypass fact grounding
- Do not mutate confirmed TOC in place
- Do not hardcode final formatting instead of using template styles
- Do not invent schema fields casually
- Do not silently change file names or contracts defined in `doc/schema.md`

---

## If something is unclear

When specs are incomplete:
- prefer the simplest implementation that matches the existing docs
- leave a clear TODO
- report the ambiguity in the final summary

Do not invent major new product behavior.

---

## Definition of done for each increment

An increment is done only if:
- code is created or updated
- it matches the project docs
- basic tests or smoke checks pass
- logs and error handling exist
- the next step is clear

---

## Final reminder

This repository is document-driven.

Treat the files in `doc/` as the source of truth.
Build the smallest correct version first, then extend it.
