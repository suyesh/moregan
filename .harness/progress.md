# Progress Log

## 2026-05-13

- Initialized harness maintenance feature work for installer `update` and `doctor` commands.
- Reviewed `README.md`, installer flow, failure patterns, evolution patterns, and rollback strategy.
- Refactored `install.py` into an explicit command-based CLI with install, uninstall, update, and doctor actions.
- Added updater safety gates for dirty worktrees and non-`main` branches unless forced.
- Added doctor checks for duplicate install directories, missing installation files, orphaned Claude persona files, and duplicate Claude registry entries.
- Narrowed doctor auto-removal to backup/copy-style duplicate directory names to avoid deleting intentional sibling checkouts.
- Added `unittest` coverage for doctor repair behavior and updater guardrails.
- Extended installed skill payloads to include `install.py`, `INSTALL.md`, and `personas/` so Claude/Codex skill invocations can run maintenance commands from the installed skill location.
- Added an install manifest so skill-local `update` can delegate back to the canonical repository checkout.
- Updated skill instructions and docs so `/harness update`, `/harness doctor`, and equivalent Codex requests are treated as maintenance intents instead of feature work.
- Removed maintenance command exposure from `setup.sh` and `setup.bat`; setup now only launches installation.
- Added `questionary`-backed select menus in the Python installer for install target and installed-state actions, with typed fallback only if the dependency is unavailable.
- Removed `update` and `doctor` from the already-installed installer action menu so maintenance stays skill-only.
- Replaced the final install `y/n` confirmation with the same styled selector flow used for other installer choices.
- Verified with `./.venv/bin/python -m unittest discover -s tests`, `./.venv/bin/python install.py --help`, and `python3 -m py_compile install.py tests/test_install.py`.

---
timestamp: "2026-05-20T14:25:20-07:00"
status: SUCCESS
task_nickname: review-personas
summary: "Added Code Reviewer and local-git-only MR Readiness Analyzer personas to hooliGAN-harness."
git_hash: "4c8e473"
updates:
  - file: "personas/CodeReviewer.md"
    action: "Added changed-code review persona with PASS/FAIL verdict format."
  - file: "personas/MRReadinessAnalyzer.md"
    action: "Added local-git-only MR readiness analyzer with no GitLab MCP or glab usage."
  - file: "personas/references/mr-readiness-scoring-rubrics.md"
    action: "Added local git scoring rubric for commit story, scope, self-review, and validation evidence."
  - file: "install.py"
    action: "Registered new personas for Claude agent installation and Codex bundled installation; also copied install.py for Codex."
  - file: "tests/test_install.py"
    action: "Added coverage for new persona installation behavior."
verification_evidence: "./.venv/bin/python -m unittest discover -s tests passed 10 tests; ./.venv/bin/python -m py_compile install.py tests/test_install.py passed; ./.venv/bin/python install.py --help showed no MR readiness backend option."
next_step: "Ask for approval before committing or pushing these changes."
notes: "MR readiness is intentionally local-git-only per user direction; installer no longer prompts for backend selection."
---

---
timestamp: "2026-05-20T14:26:53-07:00"
status: SUCCESS
task_nickname: review-personas
summary: "Tightened the Code Reviewer persona to a strict senior/staff-level production review gate."
git_hash: "4c8e473"
updates:
  - file: "personas/CodeReviewer.md"
    action: "Expanded review standards across correctness, design, security, reliability, performance, tests, JavaScript/TypeScript/React, Java/Spring, Python/FastAPI, SQL/database, and infrastructure."
verification_evidence: "./.venv/bin/python -m unittest discover -s tests passed 10 tests."
next_step: "Ask for approval before committing or pushing these changes."
notes: "The reviewer now defaults to skepticism, fails on critical or important issues, and requires concrete file/line findings with impact and fixes."
---

---
timestamp: "2026-05-28T09:34:43-07:00"
status: SUCCESS
task_nickname: mandatory-personas
summary: "Required all non-Designer harness personas for every feature task and required final MR readiness output."
git_hash: "3d96c3d"
updates:
  - file: "SKILL.md"
    action: "Added a mandatory persona execution contract, conditional Designer decision rules, and final MR readiness reporting requirement."
  - file: ".harness/defaults.yaml"
    action: "Encoded mandatory non-Designer persona execution, conditional Designer execution, and final output settings."
  - file: "README.md"
    action: "Updated workflow documentation to show mandatory non-Designer personas, conditional Designer routing, and MR readiness output."
  - file: "INSTALL.md"
    action: "Updated usage summary to reflect mandatory Architect, conditional Designer, and final MR readiness result."
  - file: "tests/test_install.py"
    action: "Added regression coverage for the mandatory persona contract."
  - file: ".harness/mandatory-personas.yaml"
    action: "Marked all acceptance criteria done."
verification_evidence: "python3 -m unittest discover -s tests passed 11 tests; python3 -m py_compile install.py tests/test_install.py passed; git diff --check passed."
persona_execution:
  planner: PASS
  architect: PASS
  designer: "not needed - documentation/config/test workflow change with no frontend or UX surface"
  generator: PASS
  evaluator: PASS
  security_evaluator: PASS
  code_reviewer: PASS
  mr_readiness_analyzer: "20/100 - capped because work is on main with uncommitted local changes"
next_step: "Move changes to a feature branch and commit before opening an MR."
notes: "This task intentionally made Architect mandatory for every feature task. Designer remains conditional and must always have a recorded decision."
---

---
timestamp: "2026-05-28T09:39:15-07:00"
status: SUCCESS
task_nickname: mandatory-personas
summary: "Added colored status markers to final persona execution output."
git_hash: "3d96c3d"
updates:
  - file: "SKILL.md"
    action: "Added a colorful persona execution summary template with green, gray, yellow, and red status markers."
  - file: ".harness/defaults.yaml"
    action: "Added final output settings for colored status markers and MR readiness color bands."
  - file: "README.md"
    action: "Added a colorful persona execution example."
  - file: "tests/test_install.py"
    action: "Extended regression coverage to assert the colorful output contract."
  - file: ".harness/mandatory-personas.yaml"
    action: "Added and completed colorful output acceptance criteria."
verification_evidence: "python3 -m unittest discover -s tests passed 11 tests; python3 -m py_compile install.py tests/test_install.py passed; git diff --check passed."
persona_execution:
  planner: "🟢 PASS"
  architect: "🟢 PASS"
  designer: "⚪ Not needed - documentation/config/test workflow change with no frontend or UX surface"
  generator: "🟢 PASS"
  evaluator: "🟢 PASS"
  security_evaluator: "🟢 PASS"
  code_reviewer: "🟢 PASS"
  mr_readiness_analyzer: "🔴 20/100 - Not ready because work is on main with uncommitted local changes"
next_step: "Move changes to a feature branch and commit before opening an MR."
notes: "The color markers are Markdown-friendly and do not depend on renderer-specific HTML styling."
---

---
timestamp: "2026-05-28T09:46:21-07:00"
status: SUCCESS
task_nickname: production-readiness
summary: "Added Production Readiness Reviewer as a mandatory post-code-review gate."
git_hash: "3d96c3d"
updates:
  - file: "personas/ProductionReadinessReviewer.md"
    action: "Added a production safety persona focused on deployability, rollback, observability, configuration, data safety, performance risk, and operational failure modes."
  - file: "install.py"
    action: "Registered the new persona for Claude agent installation and Codex bundled installation."
  - file: "SKILL.md"
    action: "Inserted Production Readiness Reviewer after Code Reviewer and before MR Readiness Analyzer in the mandatory workflow."
  - file: ".harness/defaults.yaml"
    action: "Added production_readiness_reviewer to mandatory persona execution settings."
  - file: "README.md"
    action: "Documented the ninth persona, workflow position, install tree, and final colorful output example."
  - file: "INSTALL.md"
    action: "Documented the Claude agent file and production readiness evaluation step."
  - file: "tests/test_install.py"
    action: "Added installation and mandatory-contract assertions for Production Readiness Reviewer."
  - file: ".harness/production-readiness-reviewer.yaml"
    action: "Marked all acceptance criteria done."
verification_evidence: "python3 -m unittest discover -s tests passed 11 tests; python3 -m py_compile install.py tests/test_install.py passed; git diff --check passed."
persona_execution:
  planner: "🟢 PASS"
  architect: "🟢 PASS"
  designer: "⚪ Not needed - documentation/config/test workflow change with no frontend or UX surface"
  generator: "🟢 PASS"
  evaluator: "🟢 PASS"
  security_evaluator: "🟢 PASS"
  code_reviewer: "🟢 PASS"
  production_readiness_reviewer: "🟢 PASS"
  mr_readiness_analyzer: "🔴 20/100 - Not ready because work is on main with uncommitted local changes"
next_step: "Move changes to a feature branch and commit before opening an MR."
notes: "Production Readiness Reviewer is intentionally mandatory because production safety concerns can exist in docs, installer, config, and test changes, not only runtime application code."
---
