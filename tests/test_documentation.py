import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlparse

from moregan.runtime import DeterministicEvidenceRunner
from moregan.schemas import validate_stage_result
from moregan.tools import ToolConfigLoader


REPO = Path(__file__).resolve().parents[1]


def example(path, marker, language):
    text = (REPO / path).read_text(encoding="utf-8")
    match = re.search(r"<!-- " + re.escape(marker) + r" -->\s*```" + language + r"\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise AssertionError(f"Missing documentation example: {path} / {marker}")
    return match.group(1) + "\n"


class DocumentationTests(unittest.TestCase):
    def test_documented_preview_activation_and_probe_for_both_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            probe = folder / "provider probe.py"
            probe.write_text(example("docs/getting-started.md", "provider-probe", "python"), encoding="utf-8")
            for provider in ("codex", "claude"):
                with self.subTest(provider=provider):
                    root = folder / provider
                    root.mkdir()
                    env = dict(os.environ, PYTHONPATH=str(REPO),
                               PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
                    env.pop("MOREGAN_CODEX_COMMAND", None)
                    env.pop("MOREGAN_CLAUDE_COMMAND", None)

                    def cli(*args, expected=0):
                        result = subprocess.run([sys.executable, "-m", "moregan.cli", "--root", str(root), *args],
                                                cwd=root, env=env, capture_output=True, text=True, timeout=20)
                        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                        return result.stdout

                    cli("init")
                    cli("run", "Change button label", "--no-checks", expected=1)
                    preview = json.loads(cli("inspect", "latest", "--json"))
                    self.assertEqual(preview["status"], "incomplete")
                    self.assertFalse(any(item["kind"] == "agent_provider" for stage in preview["stages"]
                                         for item in stage["evidence"]))
                    workers = root / ".moregan/workers.yaml"
                    empty_config = workers.read_text()
                    cli("adapters", provider, "--activate")
                    self.assertEqual(workers.read_text(), empty_config)
                    shutil.copyfile(root / f".moregan/workers.{provider}.yaml", workers)
                    env[f"MOREGAN_{provider.upper()}_COMMAND"] = json.dumps([sys.executable, str(probe)])
                    cli("run", "Change button label", "--no-checks", "--max-remediation-attempts", "0", expected=1)
                    result = json.loads(cli("inspect", "latest", "--json"))
                    self.assertEqual(result["status"], "incomplete")
                    for stage_name in ("generator", "evaluator"):
                        stage = next(stage for stage in result["stages"] if stage["stage"] == stage_name)
                        self.assertEqual(stage["verdict"], "skip")
                        self.assertTrue(any(item["name"] == "stdin_received" for item in stage["evidence"]))
                        self.assertTrue(any(item["kind"] == "provider_io" for item in stage["evidence"]))
                    self.assertIn("stdin_received", cli("replay", "latest"))

    def test_documented_tool_configs_and_stage_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".moregan").mkdir()
            config = root / ".moregan/tools.yaml"
            config.write_text(example("docs/getting-started.md", "required-python-check", "yaml"), encoding="utf-8")
            commands = ToolConfigLoader(root).load()
            self.assertEqual(commands[0].command, ["python3", "-m", "unittest", "discover", "-s", "tests"])
            self.assertTrue(commands[0].required)
            (root / "tests").mkdir()
            (root / "tests/test_example.py").write_text(
                "import unittest\nclass Example(unittest.TestCase):\n"
                "    def test_application(self):\n        self.assertEqual(2 + 2, 4)\n", encoding="utf-8")
            evidence = DeterministicEvidenceRunner(root).run_all()
            self.assertEqual(len(evidence), 1)
            self.assertTrue(evidence[0].passed)
            self.assertIn("Ran 1 test", evidence[0].stderr_tail)
            config.write_text(example("docs/getting-started.md", "required-maven-checks", "yaml"), encoding="utf-8")
            commands = ToolConfigLoader(root).load()
            self.assertEqual([item.command for item in commands], [["./mvnw", "verify"], ["./mvnw", "checkstyle:check"]])
            self.assertTrue(all(item.required for item in commands))
            payload = json.loads(example("docs/worker-contract.md", "stage-result", "json"))
            stage = validate_stage_result(payload, "evaluator", attempt=1, started_at="2026-09-27T00:00:00",
                                          completed_at="2026-09-27T00:00:01", duration_ms=1000)
            self.assertEqual(stage.verdict, "fail")
            self.assertEqual(stage.findings[0].severity, "high")

    def test_repository_links_in_user_guides_resolve(self):
        files = ["README.md", "INSTALL.md", "docs/getting-started.md", "docs/worker-contract.md",
                 "docs/product-status.md", "docs/releases.md"]
        github_prefix = "https://github.com/suyesh/moregan/blob/main/"
        for name in files:
            source = REPO / name
            for link in re.findall(r"\[[^\]]+\]\(([^\s)]+)\)", source.read_text(encoding="utf-8")):
                if link.startswith(github_prefix):
                    target = REPO / unquote(urlparse(link[len(github_prefix):]).path)
                elif urlparse(link).scheme or link.startswith("#"):
                    continue
                else:
                    target = source.parent / unquote(urlparse(link).path)
                with self.subTest(source=name, link=link):
                    self.assertTrue(target.is_file(), str(target))


if __name__ == "__main__":
    unittest.main()
