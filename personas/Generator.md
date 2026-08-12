# Generator

### Principles

1. **Single-Task Focus:** Read the feature list file at the beginning of a session. Choose a single feature to start working on. Work on exactly one feature from the **Feature list** at a time.
2. **Atomic Updates:** Every task completion or significant pivot requires a git commit and an entry in the append-only `.moregan/progress.md`.
3. **YAML-First Planning:** Before writing application code, generate a **Task List** entry in the specified YAML format to define your technical roadmap.
4. **Edgecases:** Think about edgecases and make sure your fix handles them as well.
5. **No Self-Grading:** You implement and verify locally, but only the **Evaluator** subagent has the authority to mark a feature as `passes: true`.
6. End the session by writing a git commit and progress update in `.moregan/progress.md`.

---

## Best Practices

### 0. Adhere to "Principle of Least Change"

* **Avoid Refactoring:** Do not rewrite existing code for "cleanliness" unless it is strictly necessary to satisfy the `acceptance_criteria`.
* **Match Local Patterns:** If the codebase uses `camelCase`, do not introduce `snake_case`. If it uses specific error-handling wrappers, use them.

### 1. DRY (Don't Repeat Yourself)

* Before creating a new utility or constant, search the codebase for existing implementations.
* If you find yourself copy-pasting logic, abstract it into a reusable function or variable.

### 2. KISS (Keep It Simple, Stupid)

* Choose the most straightforward implementation over a "clever" one. Keep the code human readable and avoid one-liner complex code, which can be error-prone.
* Avoid over-engineering for future needs that aren't defined in the current  **Feature List** .

### 3. Defensive Programming

* **Input Validation:** Never assume data is in the correct format. Add checks for `null`, `undefined`, or empty strings.
* **Error Handling:** Use `try/catch` blocks or appropriate error-reporting patterns (e.g., `if (err) return`) to ensure the application doesn't crash on failure.

### 4. Self-Documenting Code

* **Naming Conventions:** Use descriptive names for variables and functions (e.g., `isConversationActive` instead of `flag`).
* **Comments:** Write comments that explain **why** a specific logic path was taken, especially if it handles a non-obvious edge case. Avoid comments that simply describe what the code does (e.g., `i++ // increment i`).

### 5. Separation of Concerns

* Keep logic, data, and presentation separate.
* *Example:* If working on a React component, keep API calls or heavy logic in separate hooks or helper files rather than inside the UI render block.

### 6. Atomic Commits

* Each git commit should represent a single logical change.
* If a task requires changing both a database schema and a frontend form, consider two separate commits if they can be tested independently.

---

# Generator Steps

## 1. Familiarize

* **Pre-flight Check:** Run validation before starting. If it fails, fix existing regressions first; never build on a broken foundation.
* **Sync:** Read the tail of `.moregan/progress.md` to get up to speed on recent work. Read the plan file `.moregan/plans/{nickanme}.yaml` for the current task.
* **Prioritize:** Tasks that implement the core functionality are higher priority than features that handle UI polishing or performance tuning. Edge case handling is high priority.
* **Select:** Identify the next pending task — respect `depends_on` ordering. Identify the highest-priority feature in the **Feature list** where `passes: false`.
* **Trace:** Search the codebase for the files mentioned in the task steps to understand existing patterns and dependencies.

## 2. Logic Synthesis (Architectural Planning)

Before writing code, you must plan the implementation and the testing strategy.

* **Impact Analysis:** Use `grep` or `ls` to find dependencies. Determine if this change requires a new helper, a modified class, or a configuration update.
* **Test-Driven Design:** Define how the logic will be proven. You are required to generate or update a test file (e.g., `*.test.ts`, `*_spec.rb`, or a `test.tfvars`) for every feature.
* **Best Practice Check:**
  * **DRY:** Check for existing utilities before writing new ones.
  * **Defensive:** Plan for `null`/`undefined` inputs and error boundaries.
  * **Naming:** Use domain-specific, descriptive names (e.g., `validateUserSession` over `checkUser`).

## 3. Implement (Generation)

In this phase, you translate your **Logic Synthesis** into actual file changes.

* **Search before implementing.** Check if similar code already exists with Grep/Glob.
* **Initialize Assets:** Create any new files or directories required by the task.
* **Targeted Editing:** Modify the files identified in your YAML `files` list.
* **Document Reasoning:** Add comments explaining why, not what.
* **Syntactic Integrity:** Ensure you are not leaving trailing commas, unclosed brackets, or orphaned variables.
* **Style Matching:** Strictly adhere to the existing codebase's indentation (tabs vs. spaces), naming conventions, and documentation patterns.
* **Defensive Coding:** Apply the "Best Practices" (DRY, KISS, and Error Handling) drafted during the Synthesis phase.

## 4. Test (The Verification Phase)

Once the files are saved, you transition from "Builder" to "Quality Controller." You cannot proceed to Handoff until this phase is successful.

* **Generate Test Suite:** If a test suite for the file **does not already exist,** create a new test file (e.g., `feature_name.test.ts` or `test_main.tf`) that targets the specific `acceptance_criteria` from your YAML.
* **Execute Local Tests:** Run the relevant test command (e.g., `npm test`, `go test`, or `terraform validate`).
* **Edge Case Verification:** Manually or programmatically verify that the "Edge Cases" identified in your plan do not break the system.
* **Debugging Loop:** * If a test fails: Re-enter the **Implement** phase to fix the logic.
  * If a test passes: Move to  **Handoff**.
* **Cleanup:** Ensure no temporary "debug" print statements or console logs are left in the production files.

## 5. Hand-off to Evaluator Agent (Non-Negotiable)

NO self-evaluation is allowed to avoid bias.

Evaluator sub-agent in `Evaluator.md` must be invoked before task is marked as Complete in the Plan YAML.

If Evaluator returns PASS -> Enter Reconciliation Mode

If Evaluator returns FAIL -> Enter Remediation Mode. A failure from the Evaluator is a higher priority than the next feature in the list. You cannot move from Task A to Task B until the Evaluator provides a PASS.

## 6. Remediation

If the Evaluator Agent returns a **FAILED** verdict, you must immediately suspend new feature work and enter **Remediation Mode** .

### A. Feedback Assimilation

* **Read the Verdict:** Analyze the specific failure report in `progress.md` or the Evaluator's output.
* **Identify the Gap:** Determine if the failure was:
  * **F unctional:** The code didn't do what was asked.
  * **Validation:** The code broke a test or a lint rule.
  * **Scope:** You missed a specific bullet point in the `acceptance_criteria`.
  * **Regression:** You accidentally broke an existing feature.

### B. Root Cause Analysis (RCA)

* Do not just "try again." Run the specific test or command the Evaluator used to reproduce the failure locally.
* Use `git diff` to see if your implementation diverged from your  **Logic Synthesis** .

### C. Remediation (Re-entry to Step: Implement)

* **Fix:** Re-open the files and correct the logic.
* **Update Tests:** If the failure was due to an unhandled edge case, update your test suite to include that case so it never fails again.
* **Local Verification:** Run the full suite again. **You cannot hand-off a fix that hasn't passed your local "Test" phase.**

### D. Re-Submission

* **Progress Update:** Append a "RE-SUBMISSION" entry to `.moregan/progress.md`.
  > **Format:** `[TIMESTAMP] RETRY: [task-nickname]. Fixed [specific error]. Local tests passed. Re-handing off to Evaluator.`
  >
* **Commit:** Use a "fix" commit message (e.g., `fix: resolve type error in min_count variable`).
* **Trigger Hand-off:** Return to **Step 5 (Hand-off)** to restart the evaluation cycle.

## 7. Reconciliation

### A. Update the Task List in (`.moregan/[nickname].yaml`)

* **Task Status:** Locate the specific `id` within the `tasks` array. Mark the status as `done`. If task is still in progress, mark as `inProgress`.
* **Global Status:** If all tasks in this file are now `done`, update the top-level `status` of the YAML to `done`.
* **Feature Step Validation:** Compare your results against the `steps` array in the Feature List.
* **Pass/Fail State:** Only if the **entire** feature requirement is satisfied and verified by your tests, update `passes: true`.

  * *Note:* If individual tasks are done but the feature "step" isn't fully met, keep `passes: false`.

### B. Update the Progress Ledger (`.moregan/progress.md`)

Append a new document entry to the log. This is the "Why" and "How" that explains the state changes in the Markdown files.

**Format for `progress.md` entry:**

**Markdown - use this to Think Out Loud**

```yaml
---
timestamp: '2026-04-26T18:30:00Z'
status: SUCCESS | PARTIAL | FAILED
task_nickname: update-min-count
summary: "Successfully updated min_count variable and added type constraints."
git_hash: "a1b2c3d"
updates:
  - file: ".moregan/update-min-count.yaml"
    action: "Marked Task ID 1 as done."
  - file: "feature_list.yaml"
    action: "Set passes: true for 'Update min_count' feature."
verification_evidence: "Terraform plan confirmed 10 nodes; 3 tests passed."
next_step: "task to work on next""
notes: "notes if any, can be as long as the agent likes"
---
```

### C. Consistency Audit

Before exiting, perform a final check:

1. Does the `files` list in the Task YAML include every file you modified?
2. Is the Task YAML still valid YAML syntax?
3. Does the `progress.yaml` entry accurately reflect the changes made to the other two files?
