"""Provider command wrapper for MoreGAN agent workers."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from moregan.schemas import (
    EvidenceReference, Finding, StageResult, StageResultValidationError, WORKER_STAGES,
    output_tail, parse_stage_json, validate_stage_result,
)


PROVIDER_COMMAND_ENV = {
    "codex": "MOREGAN_CODEX_COMMAND",
    "claude": "MOREGAN_CLAUDE_COMMAND",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a MoreGAN agent provider command.")
    parser.add_argument("--provider", choices=sorted(PROVIDER_COMMAND_ENV), required=True)
    parser.add_argument("--stage", choices=sorted(WORKER_STAGES), required=True)
    parser.add_argument("--prompt", required=True, help="prompt template path")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--timeout", type=int, default=300)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    runner = AgentWorkerRunner(
        provider=args.provider,
        stage=args.stage,
        prompt_path=Path(args.prompt),
        root=Path(args.root).resolve(),
        timeout_seconds=args.timeout,
    )
    result = runner.run()
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


class AgentWorkerRunner:
    """Runs a configured provider CLI and returns StageResult JSON."""

    def __init__(self, provider: str, stage: str, prompt_path: Path, root: Path, timeout_seconds: int):
        self.provider = provider
        self.stage = stage
        self.prompt_path = prompt_path
        self.root = root
        self.timeout_seconds = timeout_seconds
        self.attempt = 1

    def run(self) -> StageResult:
        started = time.perf_counter()
        started_at = self._timestamp()
        try:
            attempt = int(os.environ.get("MOREGAN_ATTEMPT", "1"))
            if attempt < 1:
                raise ValueError("attempt must be positive")
            self.attempt = attempt
            if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
                raise ValueError("timeout must be a positive integer")
        except ValueError as exc:
            return self._failure(started, f"Invalid worker execution context: {exc}",
                                 "Use a positive MOREGAN_ATTEMPT and timeout.")
        env_name = PROVIDER_COMMAND_ENV[self.provider]
        raw_command = os.environ.get(env_name, "").strip()
        if not raw_command:
            return self._skip(
                started,
                summary=f"{env_name} is not set; {self.provider} worker template was not executed.",
            )

        try:
            command = self._parse_command(raw_command)
        except ValueError as exc:
            return self._failure(
                started,
                description=f"{env_name} is invalid: {exc}",
                remediation=f"Set {env_name} to a shell command string or JSON list.",
            )

        try:
            prompt = self._build_prompt()
        except (OSError, UnicodeError) as exc:
            return self._failure(started, f"Could not read provider prompt: {exc}",
                                 "Check the prompt path, permissions, and text encoding.")
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                input=prompt,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return self._failure(
                started,
                description=f"{self.provider} {self.stage} command timed out after {self.timeout_seconds}s.",
                remediation="Increase timeout_seconds or fix the provider command.",
                stdout_tail=exc.stdout or "",
                stderr_tail=exc.stderr or "",
            )
        except (OSError, ValueError) as exc:
            return self._failure(
                started, f"{self.provider} {self.stage} command could not run: {exc}",
                "Check the provider executable, arguments, permissions, and output encoding.",
            )

        if completed.returncode != 0:
            return self._failure(
                started,
                description=f"{self.provider} {self.stage} command exited with {completed.returncode}.",
                remediation="Fix the provider command or the adapter prompt.",
                stdout_tail=completed.stdout,
                stderr_tail=completed.stderr,
            )

        try:
            payload = parse_stage_json(completed.stdout)
        except StageResultValidationError as exc:
            return self._failure(
                started,
                description=f"{self.provider} {self.stage} command did not return StageResult JSON: {exc}",
                remediation="Adjust the adapter prompt or provider command so stdout contains one JSON object.",
                stdout_tail=completed.stdout,
                stderr_tail=completed.stderr,
            )

        return self._stage_result_from_payload(payload, started, started_at)

    def _build_prompt(self) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        context = {
            "run_id": os.environ.get("MOREGAN_RUN_ID", ""),
            "stage": self.stage,
            "request": os.environ.get("MOREGAN_REQUEST", ""),
            "risk_level": os.environ.get("MOREGAN_RISK_LEVEL", ""),
            "route": os.environ.get("MOREGAN_ROUTE", "[]"),
            "no_write": os.environ.get("MOREGAN_NO_WRITE", "1"),
            "attempt": os.environ.get("MOREGAN_ATTEMPT", "1"),
            "remediation_context": os.environ.get("MOREGAN_REMEDIATION_CONTEXT", "{}"),
            "context_pack": os.environ.get("MOREGAN_CONTEXT_PACK", ""),
            "context_tokens": os.environ.get("MOREGAN_CONTEXT_TOKENS", "0"),
        }
        return (
            f"{template}\n\n"
            "## Runtime Context\n\n"
            f"- run_id: {context['run_id']}\n"
            f"- stage: {context['stage']}\n"
            f"- request: {context['request']}\n"
            f"- risk_level: {context['risk_level']}\n"
            f"- route: {context['route']}\n"
            f"- MOREGAN_NO_WRITE: {context['no_write']}\n\n"
            f"- attempt: {context['attempt']}\n"
            f"- remediation_context: {context['remediation_context']}\n\n"
            f"- context_pack: {context['context_pack']}\n"
            f"- context_tokens_estimate: {context['context_tokens']}\n\n"
            "Read the context pack path when present instead of requesting oversized inline history.\n\n"
            "Return exactly one JSON object on stdout and no markdown fences.\n"
        )

    def _stage_result_from_payload(self, payload: object, started: float, started_at: str) -> StageResult:
        try:
            result = validate_stage_result(
                payload, self.stage, attempt=self.attempt, started_at=started_at,
                completed_at=self._timestamp(), duration_ms=self._duration_ms(started),
            )
        except StageResultValidationError as exc:
            return self._failure(
                started, f"{self.provider} returned invalid StageResult: {exc}",
                "Return a valid StageResult object with correctly typed fields and concrete findings.",
            )
        result.evidence.append(
            EvidenceReference(
                kind="agent_provider",
                name=f"{self.provider}_{self.stage}",
                summary=f"Normalized {self.provider} provider output through moregan.agent_worker.",
                path=str(self.prompt_path),
            )
        )
        return result

    def _skip(self, started: float, summary: str) -> StageResult:
        return StageResult(
            stage=self.stage,
            verdict="skip",
            confidence=1.0,
            evidence=[
                EvidenceReference(
                    kind="agent_provider",
                    name=f"{self.provider}_command",
                    summary=summary,
                    path=str(self.prompt_path),
                )
            ],
            attempt=self.attempt,
            started_at=self._timestamp(),
            completed_at=self._timestamp(),
            duration_ms=self._duration_ms(started),
        )

    def _failure(
        self,
        started: float,
        description: str,
        remediation: str,
        stdout_tail: str = "",
        stderr_tail: str = "",
    ) -> StageResult:
        evidence = [
            EvidenceReference(
                kind="agent_provider",
                name=f"{self.provider}_command",
                summary=f"{self.provider} provider command failed or returned invalid output.",
                path=str(self.prompt_path),
            )
        ]
        stdout_tail, stderr_tail = output_tail(stdout_tail), output_tail(stderr_tail)
        if stdout_tail:
            evidence.append(
                EvidenceReference(
                    kind="stdout_tail",
                    name=f"{self.provider}_{self.stage}_stdout",
                    summary=stdout_tail.strip()[-1000:],
                )
            )
        if stderr_tail:
            evidence.append(
                EvidenceReference(
                    kind="stderr_tail",
                    name=f"{self.provider}_{self.stage}_stderr",
                    summary=stderr_tail.strip()[-1000:],
                )
            )
        return StageResult(
            stage=self.stage,
            verdict="fail",
            confidence=1.0,
            findings=[
                Finding(
                    severity="high",
                    category="agent_provider_failed",
                    description=description,
                    remediation=remediation,
                )
            ],
            evidence=evidence,
            attempt=self.attempt,
            started_at=self._timestamp(),
            completed_at=self._timestamp(),
            duration_ms=self._duration_ms(started),
        )

    def _parse_command(self, raw_command: str) -> List[str]:
        if raw_command.startswith("["):
            try:
                parsed = ast.literal_eval(raw_command)
            except (SyntaxError, ValueError) as exc:
                raise ValueError("JSON/list command could not be parsed") from exc
            if not isinstance(parsed, list):
                raise ValueError("JSON/list command must be a list")
            command = parsed
        else:
            command = shlex.split(raw_command)
        if (not command or any(not isinstance(item, str) or "\x00" in item for item in command)
                or not command[0].strip()):
            raise ValueError("command needs a nonempty executable and string arguments")
        return command

    def _timestamp(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
