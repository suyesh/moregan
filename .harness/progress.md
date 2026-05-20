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
