# Deployment Script Naming and OpenAI Demo Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the deployment entry points without the word `video` and make the documentation unambiguous that API-key-powered four-arm comparison is optional and separate from the five-minute deployment validation.

**Architecture:** Keep the existing build/deploy implementation and generated artifacts unchanged while moving only the two user-facing shell entry points. Update their contract test and all current operator-facing references atomically; retain `deploy/video/` as an internal manifest namespace because the user requested the linked script names to change, not a broader deployment layout migration.

**Tech Stack:** Bash, Python unittest, Markdown, Docker Compose

---

### Task 1: Make the naming contract fail first

**Files:**
- Modify: `scripts/test_deployment_video.py`

- [ ] **Step 1: Point the contract at the new public names**

Set:

```python
PREPARE_SCRIPT = ROOT / "scripts/prepare_deployment.sh"
RECORD_SCRIPT = ROOT / "scripts/run_deployment.sh"
```

Add assertions that `scripts/prepare_deployment_video.sh` and
`scripts/run_deployment_video.sh` do not exist.

- [ ] **Step 2: Run the focused test**

Run:

```bash
python3 -m unittest scripts.test_deployment_video
```

Expected: failure because the new script names do not exist yet.

### Task 2: Rename the public deployment entry points

**Files:**
- Move: `scripts/prepare_deployment_video.sh` → `scripts/prepare_deployment.sh`
- Move: `scripts/run_deployment_video.sh` → `scripts/run_deployment.sh`

- [ ] **Step 1: Move both executable files without rewriting their behavior**

Use file moves so executable mode and full history remain attributable.

- [ ] **Step 2: Update cross-script error and completion messages**

Change all user-facing commands inside the scripts to:

```text
scripts/prepare_deployment.sh
scripts/run_deployment.sh
scripts/run_deployment.sh --purchase
```

- [ ] **Step 3: Verify the old names are absent**

Run:

```bash
rg -n 'prepare_deployment_video|run_deployment_video' scripts
```

Expected: no matches.

### Task 3: Separate the zero-key deployment proof from the OpenAI comparison

**Files:**
- Modify: `docs/video-deployment-demo.zh.md`
- Modify: `README.md`

- [ ] **Step 1: Update deployment commands and links**

Document:

```bash
MISARCH_INFRA_DIR=/Users/wang/Desktop/TUB2025sose/misarch-infrastructure-docker \
  ./scripts/prepare_deployment.sh

./scripts/run_deployment.sh --purchase
```

- [ ] **Step 2: Add an explicit API Key decision**

State that the five-minute deployment video must not show API-key entry and
does not call an LLM. Put this optional four-arm block in a separate section:

```bash
[[ -n "$OPENAI_API_KEY" ]] \
  && echo "API Key 已导入" \
  || echo "API Key 未导入"

export OPENAI_BASE_URL=https://yybb.dog
export OPENAI_MODEL=gpt-5.5
./scripts/open_iterm_four_arm_demo.sh
```

If the check reports that the key is missing, stop recording, import it with
`read -s OPENAI_API_KEY`, export it, clear the screen, and start a new uncut
recording. Never show paste/input or print the key in the submitted recording.

- [ ] **Step 3: Clarify the two-video boundary**

Use this mapping:

- deployment validation: build, Compose deployment, health, Agent Card, MCP/A2A checks, optional local purchase; no key;
- optional four-arm comparison: real external LLM calls in four iTerm panes; key required; not part of the deployment proof.

### Task 4: Update implementation-plan references

**Files:**
- Modify: `docs/superpowers/plans/2026-07-28-five-minute-deployment-video.md`

- [ ] **Step 1: Replace only public script and test commands**

Replace `prepare_deployment_video.sh` with `prepare_deployment.sh` and
`run_deployment_video.sh` with `run_deployment.sh`. Keep `deploy/video/`
manifest paths unchanged.

### Task 5: Verify behavior and references

**Files:**
- Verify: `scripts/prepare_deployment.sh`
- Verify: `scripts/run_deployment.sh`
- Verify: `scripts/test_deployment_video.py`
- Verify: `docs/video-deployment-demo.zh.md`

- [ ] **Step 1: Run syntax and contract checks**

Run:

```bash
bash -n scripts/prepare_deployment.sh scripts/run_deployment.sh
python3 -m unittest scripts.test_deployment_video
```

Expected: all checks pass.

- [ ] **Step 2: Run repository tests**

Run:

```bash
go test ./...
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 3: Confirm no stale public names remain**

Run:

```bash
rg -n 'prepare_deployment_video|run_deployment_video' \
  README.md docs/video-deployment-demo.zh.md scripts
```

Expected: no matches.

- [ ] **Step 4: Run the renamed deployment entry point safely**

Run:

```bash
./scripts/run_deployment.sh
```

Expected: `VIDEO DEMO PASS`, with no order or payment mutation.
