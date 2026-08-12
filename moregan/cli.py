"""Command line entry point for MoreGAN."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from moregan.adapters import AdapterError, AgentAdapterScaffolder
from moregan.agent_worker import PROVIDER_COMMAND_ENV
from moregan.init import MoreGANInitializer
from moregan.replay import ReplayError, RunReplay
from moregan.runtime import MoreGANRuntime, latest_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MoreGAN executable runtime.")
    parser.add_argument("--root", default=".", help="repository root to operate on")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize MoreGAN config in a repository")
    init_parser.add_argument("--force", action="store_true", help="replace existing MoreGAN config files")
    init_parser.add_argument("--dry-run", action="store_true", help="show what would be written without changing files")
    init_parser.add_argument("--no-gitignore", action="store_true", help="do not add .moregan/runs/ to .gitignore")

    adapters_parser = subparsers.add_parser("adapters", help="scaffold Codex or Claude worker adapter templates")
    adapters_parser.add_argument("provider", choices=sorted(PROVIDER_COMMAND_ENV), help="agent provider to scaffold")
    adapters_parser.add_argument("--activate", action="store_true", help="write provider commands to .moregan/workers.yaml")
    adapters_parser.add_argument("--force", action="store_true", help="replace existing adapter files")
    adapters_parser.add_argument("--dry-run", action="store_true", help="show what would be written without changing files")

    run_parser = subparsers.add_parser("run", help="create a MoreGAN run trace")
    run_parser.add_argument("request", help="engineering request to classify and trace")
    run_parser.add_argument("--no-checks", action="store_true", help="create trace without running deterministic checks")

    subparsers.add_parser("status", help="show the latest MoreGAN run")

    inspect_parser = subparsers.add_parser("inspect", help="print a run report")
    inspect_parser.add_argument("run_id", nargs="?", default="latest", help="run id or 'latest'")
    inspect_parser.add_argument("--json", action="store_true", help="print result.json instead of final_report.md")

    replay_parser = subparsers.add_parser("replay", help="reconstruct a run without re-executing work")
    replay_parser.add_argument("run_id", nargs="?", default="latest", help="run id or 'latest'")
    replay_parser.add_argument("--json", action="store_true", help="print replay data as JSON")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()

    if args.command == "init":
        result = MoreGANInitializer(root).init(
            force=args.force,
            dry_run=args.dry_run,
            update_gitignore=not args.no_gitignore,
        )
        mode = "dry run" if args.dry_run else "initialized"
        print(f"MoreGAN {mode}: {result.root}")
        for action in result.actions:
            print(f"- {action.action}: {action.path} - {action.detail}")
        return 0

    if args.command == "adapters":
        try:
            result = AgentAdapterScaffolder(root).scaffold(
                provider=args.provider,
                force=args.force,
                dry_run=args.dry_run,
                activate=args.activate,
            )
        except AdapterError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        mode = "dry run" if args.dry_run else "scaffolded"
        print(f"MoreGAN {mode} {result.provider} adapters: {result.root}")
        for action in result.actions:
            print(f"- {action.action}: {action.path} - {action.detail}")
        env_name = PROVIDER_COMMAND_ENV[result.provider]
        print(f"Provider command env: {env_name}")
        return 0

    if args.command == "run":
        result = MoreGANRuntime(root).run(args.request, run_checks=not args.no_checks)
        print(f"MoreGAN run {result.status.upper()}: {result.run_id}")
        print(f"Risk: {result.risk.level}")
        print(f"Trace: {result.trace_path}")
        return 0 if result.status == "pass" else 1

    if args.command == "status":
        run_dir = latest_run(root)
        if run_dir is None:
            print("No MoreGAN runs found.")
            return 1
        result_path = run_dir / "result.json"
        if not result_path.exists():
            print(f"Latest run has no result.json: {run_dir}")
            return 1
        result = json.loads(result_path.read_text(encoding="utf-8"))
        print(f"Latest MoreGAN run: {result['run_id']}")
        print(f"Status: {result['status']}")
        print(f"Risk: {result['risk']['level']}")
        if result.get("state"):
            print(f"State: {result['state']['current_state']}")
        print(f"Trace: {run_dir}")
        return 0

    if args.command == "inspect":
        run_dir = _resolve_run_dir(root, args.run_id)
        if run_dir is None:
            print(f"MoreGAN run not found: {args.run_id}", file=sys.stderr)
            return 1
        target = run_dir / ("result.json" if args.json else "final_report.md")
        if not target.exists():
            print(f"Run artifact not found: {target}", file=sys.stderr)
            return 1
        print(target.read_text(encoding="utf-8"), end="")
        return 0

    if args.command == "replay":
        run_dir = _resolve_run_dir(root, args.run_id)
        if run_dir is None:
            print(f"MoreGAN run not found: {args.run_id}", file=sys.stderr)
            return 1
        try:
            replay = RunReplay(run_dir)
            if args.json:
                print(json.dumps(replay.to_dict(), indent=2, sort_keys=True))
            else:
                print(replay.render(), end="")
        except ReplayError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    return 1


def _resolve_run_dir(root: Path, run_id: str) -> Optional[Path]:
    if run_id == "latest":
        return latest_run(root)
    candidate = root / ".moregan" / "runs" / run_id
    return candidate if candidate.is_dir() else None


if __name__ == "__main__":
    raise SystemExit(main())
