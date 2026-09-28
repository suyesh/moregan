"""Exercise the built wheel in a clean venv and disposable home, outside source."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def run(command, cwd, env, expected=0):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=180)
    if result.returncode != expected:
        raise RuntimeError(f"{command}: expected {expected}, got {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def verify(checkout):
    import importlib.metadata
    import install
    import moregan

    installed = Path(moregan.__file__).resolve()
    if installed.is_relative_to(checkout):
        raise RuntimeError("Smoke test imported source instead of the installed wheel")
    if moregan.__version__ != install.VERSION or moregan.__version__ != importlib.metadata.version("moregan"):
        raise RuntimeError("Installed version metadata mismatch")
    env = dict(os.environ)
    binary = Path(sys.executable).parent / ("moregan.exe" if os.name == "nt" else "moregan")
    run([str(binary), "--help"], Path.cwd(), env)
    run([str(binary), "setup", "--help"], Path.cwd(), env)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        for provider in ("codex", "claude"):
            root = folder / provider
            root.mkdir()
            def cli(*args, expected=0):
                try:
                    return run([str(binary), "--root", str(root), *args], root, env, expected)
                except RuntimeError as exc:
                    reports = sorted((root / ".moregan/runs").glob("*/final_report.md"))
                    detail = reports[-1].read_text(encoding="utf-8")[-16000:] if reports else "No report written"
                    raise RuntimeError(f"{exc}\nSaved smoke report:\n{detail}") from exc
            cli("init")
            cli("run", "Change button label", "--no-checks", expected=1)
            if json.loads(cli("inspect", "latest", "--json"))["status"] != "incomplete":
                raise RuntimeError("Unconfigured run must remain incomplete")
            cli("adapters", provider, "--activate", "--force")
            probe = root / "probe.py"
            probe.write_text(
                "import json, os, sys\n"
                "assert sys.stdin.read()\n"
                "fail = os.environ.get('SMOKE_FAIL') == '1'\n"
                "print(json.dumps({'stage': os.environ['MOREGAN_STAGE'],\n"
                " 'verdict': 'fail' if fail else 'pass', 'confidence': 1.0,\n"
                " 'findings': [], 'evidence': []}))\n", encoding="utf-8")
            env[f"MOREGAN_{provider.upper()}_COMMAND"] = json.dumps([sys.executable, str(probe)])
            (root / ".moregan/tools.yaml").write_text(
                "commands:\n  - name: smoke\n    required: true\n    command: "
                + json.dumps([sys.executable, "-c", "print('smoke check')"]) + "\n", encoding="utf-8")
            for failed in (False, True):
                env["SMOKE_FAIL"] = "1" if failed else "0"
                cli("run", "Change button label", "--max-remediation-attempts", "0", expected=int(failed))
                result = json.loads(cli("inspect", "latest", "--json"))
                expected = "fail" if failed else "pass"
                if result["status"] != expected:
                    raise RuntimeError(f"Expected simulated provider {expected}: {result}")
                cli("status")
                cli("replay", "latest", "--json")
        installer = install.MoreGANInstaller(home=folder / "skill-home")
        installer.install_targets = ["codex", "claude"]
        if not installer.install_files():
            raise RuntimeError("Installed-wheel skill setup failed")
        for host in ("codex", "claude"):
            skill = folder / "skill-home" / f".{host}/skills/moregan"
            for name in ("SKILL.md", "moregan/runtime.py", "personas/Generator.md", "docs/getting-started.md"):
                if not (skill / name).is_file():
                    raise RuntimeError(f"Missing installed skill asset: {skill / name}")
    print(f"Installed {moregan.__version__} smoke passed: CLI, both adapters, outcomes, replay and skill assets")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    if args.verify:
        verify(args.checkout.resolve())
        return
    if args.dist is None:
        parser.error("--dist is required")
    wheels = list(args.dist.resolve().glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one wheel")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
        for key in ("PYTHONPATH", "PYTHONHOME", "MOREGAN_CODEX_COMMAND", "MOREGAN_CLAUDE_COMMAND", "SMOKE_FAIL"):
            env.pop(key, None)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-m", "pip", "install", "--index-url", "https://pypi.org/simple", str(wheels[0])], root, env)
        run([str(python), "-m", "pip", "check"], root, env)
        print(run([str(python), str(Path(__file__).resolve()), "--verify", "--checkout", str(args.checkout.resolve())],
                  root, env))


if __name__ == "__main__":
    main()
