"""Provider command wrapper for MoreGAN agent workers."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import stat
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from moregan.processes import (
    MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, MAX_TIMEOUT_SECONDS, SUPERVISOR_ENV, run_bounded, supervised_adapter,
)
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
    parser.add_argument("--timeout", type=int, default=os.environ.get("MOREGAN_WORKER_TIMEOUT_SECONDS", "300"))
    parser.add_argument("--max-output-bytes", type=int, default=os.environ.get("MOREGAN_MAX_OUTPUT_BYTES", str(MAX_OUTPUT_BYTES)))
    parser.add_argument("--max-prompt-bytes", type=int, default=os.environ.get("MOREGAN_MAX_PROMPT_BYTES", str(MAX_INPUT_BYTES)))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    runner = AgentWorkerRunner(
        provider=args.provider,
        stage=args.stage,
        prompt_path=Path(args.prompt),
        root=Path(args.root).resolve(),
        timeout_seconds=args.timeout,
        max_output_bytes=args.max_output_bytes,
        max_prompt_bytes=args.max_prompt_bytes,
    )
    result = runner.run()
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


class AgentWorkerRunner:
    """Runs a configured provider CLI and returns StageResult JSON."""

    def __init__(self, provider: str, stage: str, prompt_path: Path, root: Path, timeout_seconds: int,
                 max_output_bytes: int = MAX_OUTPUT_BYTES, max_prompt_bytes: int = MAX_INPUT_BYTES):
        self.provider = provider
        self.stage = stage
        self.prompt_path = prompt_path
        self.root = root
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_prompt_bytes = max_prompt_bytes
        self.attempt = 1

    def run(self) -> StageResult:
        started = time.perf_counter()
        started_at = self._timestamp()
        try:
            attempt = int(os.environ.get("MOREGAN_ATTEMPT", "1"))
            if attempt < 1:
                raise ValueError("attempt must be positive")
            self.attempt = attempt
            for name, value, maximum in (("timeout", self.timeout_seconds, MAX_TIMEOUT_SECONDS),
                                         ("max_output_bytes", self.max_output_bytes, MAX_OUTPUT_BYTES),
                                         ("max_prompt_bytes", self.max_prompt_bytes, MAX_INPUT_BYTES)):
                if type(value) is not int or not 1 <= value <= maximum:
                    raise ValueError(f"{name} must be an integer between 1 and {maximum}")
        except ValueError as exc:
            return self._failure(started, f"Invalid worker execution context: {exc}",
                                 "Use a positive MOREGAN_ATTEMPT and supported execution limits.")
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
            prompt = self._build_prompt().encode("utf-8")
        except (OSError, ValueError) as exc:
            return self._failure(started, f"Could not read provider prompt: {exc}",
                                 "Check the prompt path, permissions, UTF-8 encoding, and max_prompt_bytes.")
        env = os.environ.copy()
        env.pop(SUPERVISOR_ENV, None)
        try:
            completed = run_bounded(
                command, self.root, env=env, input_bytes=prompt, max_input_bytes=self.max_prompt_bytes,
                timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes,
                strict_stdout=True, inherit_process_group=supervised_adapter(),
            )
        except (OSError, ValueError) as exc:
            return self._failure(
                started, f"{self.provider} {self.stage} command could not run: {exc}",
                "Check the provider executable, arguments, permissions, and output encoding.",
            )

        if completed.error_kind or completed.exit_code != 0:
            result = self._failure(
                started,
                description=f"{self.provider} {self.stage}: {completed.reason or f'command exited with {completed.exit_code}.'}",
                remediation="Check the provider command, execution limits, and process cleanup.",
                stdout_tail=completed.stdout_tail,
                stderr_tail=completed.stderr_tail,
            )
            if completed.error_kind == "cleanup_error":
                result.findings[0].category = "worker_cleanup_failed"
        else:
            try:
                payload = parse_stage_json(completed.stdout_tail)
            except StageResultValidationError as exc:
                result = self._failure(
                    started,
                    description=f"{self.provider} {self.stage} command did not return StageResult JSON: {exc}",
                    remediation="Adjust the adapter prompt or provider command so stdout contains one JSON object.",
                    stdout_tail=completed.stdout_tail, stderr_tail=completed.stderr_tail,
                )
            else:
                result = self._stage_result_from_payload(payload, started, started_at)
        result.evidence.append(EvidenceReference(
            kind="provider_io", name=f"{self.provider}_process",
            summary=f"prompt_bytes={len(prompt)}; stdout_bytes={completed.stdout_bytes}; "
                    f"stderr_bytes={completed.stderr_bytes}; stderr_truncated={completed.stderr_truncated}; "
                    f"error_kind={completed.error_kind or 'none'}; stdout_limit={self.max_output_bytes}; "
                    f"timeout_seconds={self.timeout_seconds}.",
        ))
        return result

    def _build_prompt(self) -> str:
        # Nonblocking open plus fstat rejects FIFOs/devices without waiting for a writer.
        fd = os.open(str(self.prompt_path), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("prompt must be a regular file")
            raw = stream.read(self.max_prompt_bytes + 1)
        if len(raw) > self.max_prompt_bytes:
            raise ValueError(f"prompt template exceeds {self.max_prompt_bytes} bytes")
        template = raw.decode("utf-8")
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
            "phase": os.environ.get("MOREGAN_STAGE_PHASE", "standard"),
        }
        if len(raw) + sum(len(value.encode("utf-8")) for value in context.values()) > self.max_prompt_bytes:
            raise ValueError(f"prompt with runtime context exceeds {self.max_prompt_bytes} bytes")
        prompt = (
            f"{template}\n\n"
            "## Runtime Context\n\n"
            f"- run_id: {context['run_id']}\n"
            f"- stage: {context['stage']}\n"
            f"- phase: {context['phase']}\n"
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
        if len(prompt.encode("utf-8")) > self.max_prompt_bytes:
            raise ValueError(f"prompt with runtime context exceeds {self.max_prompt_bytes} bytes")
        return prompt

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
