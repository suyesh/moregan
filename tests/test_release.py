import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

import yaml


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_checks", REPO / "scripts/ci/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("pyproject.toml", "moregan/__init__.py", "install.py", "SKILL.md", "uv.lock"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        self.project = release.validate_source(self.root)
        self.version = self.project["version"]
        self.tag = f"v{self.version}"

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "user.name=Release Test", "-c", "user.email=release@example.invalid",
                                        *args], cwd=self.root, stderr=subprocess.STDOUT, text=True).strip()

    def repository(self):
        notes = self.root / "docs/release-notes" / f"{self.version}.md"
        notes.parent.mkdir(parents=True)
        notes.write_text("Test release\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "Release fixture")
        self.git("tag", "-a", self.tag, "-m", "Release")
        return {"GITHUB_REF": f"refs/tags/{self.tag}", "GITHUB_EVENT_NAME": "workflow_dispatch"}

    def test_source_and_lock_versions_are_consistent(self):
        self.assertEqual(release.validate_source(REPO)["requires-python"], ">=3.10")
        for name, old, new in (("SKILL.md", f"version: {self.version}", "version: 0.0.0"),
                               ("uv.lock", f'version = "{self.version}"', 'version = "0.0.0"'),
                               ("install.py", f'VERSION = "{self.version}"', 'VERSION = "0.0.0"'),
                               ("pyproject.toml", 'requires-python = ">=3.10"', 'requires-python = ">=3.8"')):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text(encoding="utf-8")
                path.write_text(original.replace(old, new), encoding="utf-8")
                with self.assertRaises(ValueError):
                    release.validate_source(self.root)
                path.write_text(original, encoding="utf-8")

    def test_release_events_accept_only_matching_tags(self):
        env = self.repository()
        events = {"workflow_dispatch": {}, "push": {"ref": env["GITHUB_REF"], "deleted": False},
                  "release": {"action": "published", "release": {"tag_name": self.tag, "draft": False,
                                                                   "prerelease": False}}}
        for name, payload in events.items():
            with self.subTest(event=name):
                self.assertEqual(release.validate_event(self.root, self.project, payload,
                                                        dict(env, GITHUB_EVENT_NAME=name)), self.tag)
                for ref in ("refs/heads/main", "refs/tags/v0.0.0", "refs/tags/v1.16.0;echo injected"):
                    with self.assertRaises(ValueError):
                        release.validate_event(self.root, self.project, payload,
                                               dict(env, GITHUB_EVENT_NAME=name, GITHUB_REF=ref))

    def test_rejects_drafts_prereleases_deleted_tags_and_unrecognized_events(self):
        env = self.repository()
        payload = {"action": "published", "release": {"tag_name": self.tag, "draft": False, "prerelease": False}}
        for field, value in (("draft", True), ("prerelease", True), ("tag_name", "v0.0.0")):
            bad = json.loads(json.dumps(payload))
            bad["release"][field] = value
            with self.assertRaises(ValueError):
                release.validate_event(self.root, self.project, bad, dict(env, GITHUB_EVENT_NAME="release"))
        for name, bad in (("push", {"ref": env["GITHUB_REF"], "deleted": True}), ("pull_request", {})):
            with self.assertRaises(ValueError):
                release.validate_event(self.root, self.project, bad, dict(env, GITHUB_EVENT_NAME=name))

    def test_rejects_checkout_drift_and_missing_release_notes(self):
        env = self.repository()
        notes = self.root / "docs/release-notes" / f"{self.version}.md"
        notes.unlink()
        with self.assertRaisesRegex(ValueError, "notes"):
            release.validate_event(self.root, self.project, {}, env)
        self.git("add", ".")
        self.git("commit", "-qm", "New commit")
        with self.assertRaisesRegex(ValueError, "commit"):
            release.validate_event(self.root, self.project, {}, env)

    def distributions(self, version=None, forbidden=False):
        folder = self.root / "dist"
        folder.mkdir(exist_ok=True)
        metadata = f"Name: moregan\nVersion: {version or self.version}\nRequires-Python: >=3.10\n\n".encode()
        with zipfile.ZipFile(folder / f"moregan-{self.version}-py3-none-any.whl", "w") as wheel:
            wheel.writestr(f"moregan-{self.version}.dist-info/METADATA", metadata)
            for name in ("moregan/runtime.py", "install.py", "SKILL.md", "README.md", "INSTALL.md",
                         "personas/Generator.md", "assets/moregan.png", "docs/getting-started.md"):
                wheel.writestr(name, "fixture")
            if forbidden:
                wheel.writestr(".moregan/runs/private/result.json", "private")
        with tarfile.open(folder / f"moregan-{self.version}.tar.gz", "w:gz") as sdist:
            info = tarfile.TarInfo(f"moregan-{self.version}/PKG-INFO")
            info.size = len(metadata)
            sdist.addfile(info, io.BytesIO(metadata))
            for name in ("pyproject.toml", "uv.lock", "scripts/ci/release.py", "scripts/ci/installed_smoke.py",
                         ".github/workflows/ci.yml", ".github/workflows/workflow.yml", "tests/test_release.py"):
                sdist.addfile(tarfile.TarInfo(f"moregan-{self.version}/{name}"), io.BytesIO(b""))
        return folder

    def test_distributions_must_match_source_and_exclude_local_runs(self):
        folder = self.distributions()
        (folder / ".gitignore").write_text("*\n", encoding="utf-8")
        release.validate_distributions(folder, self.project)
        with self.assertRaisesRegex(ValueError, "metadata"):
            release.validate_distributions(self.distributions(version="0.0.0"), self.project)
        with self.assertRaisesRegex(ValueError, "local run"):
            release.validate_distributions(self.distributions(forbidden=True), self.project)
        folder = self.distributions()
        (folder / "unexpected.whl").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            release.validate_distributions(folder, self.project)

    def test_publication_depends_on_shared_ci_and_uses_tested_artifact(self):
        workflow = yaml.safe_load((REPO / ".github/workflows/workflow.yml").read_text())
        jobs = workflow["jobs"]
        self.assertEqual(workflow["on"]["push"], {"tags": ["v*"]})
        self.assertEqual(jobs["quality"]["needs"], "preflight")
        self.assertEqual(jobs["quality"]["uses"], "./.github/workflows/ci.yml")
        self.assertEqual(set(jobs["pypi-publish"]["needs"]), {"preflight", "quality", "github-release"})
        self.assertIn("quality", jobs["github-release"]["needs"])
        self.assertNotIn("if", jobs["pypi-publish"])
        self.assertEqual(jobs["pypi-publish"]["permissions"]["id-token"], "write")
        steps = jobs["pypi-publish"]["steps"]
        self.assertEqual(steps[0]["with"]["name"], "moregan-dist")
        self.assertTrue(steps[0]["uses"].startswith("actions/download-artifact@"))
        self.assertTrue(steps[1]["uses"].startswith("pypa/gh-action-pypi-publish@"))
        self.assertFalse(any("run" in step for step in steps))

    def test_ci_matrix_matches_advertised_platform_scope(self):
        workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
        self.assertIn("workflow_call", workflow["on"])
        jobs = workflow["jobs"]
        self.assertEqual(jobs["test"]["strategy"]["matrix"]["python"], [f"3.{minor}" for minor in range(10, 15)])
        self.assertEqual(jobs["test"]["strategy"]["matrix"]["os"], ["ubuntu-latest", "macos-latest"])
        self.assertEqual(jobs["windows-install"]["runs-on"], "windows-latest")
        for name in ("test", "windows-install"):
            self.assertEqual(jobs[name]["needs"], "build")
            self.assertTrue(any("installed_smoke.py" in step.get("run", "") for step in jobs[name]["steps"]))
            self.assertFalse(jobs[name].get("continue-on-error", False))

    @unittest.skipUnless(os.name == "posix", "Shell bootstrap")
    def test_shell_bootstrap_checks_python_floor_from_another_directory(self):
        import sys
        shutil.copyfile(REPO / "setup.sh", self.root / "setup.sh")
        binary = self.root / "bin"
        binary.mkdir()
        python = binary / "python3"
        python.write_text(
            '#!/bin/sh\nif [ "$2" = "import sys; sys.exit(sys.version_info < (3, 10))" ] '
            '&& [ "$OLD_PYTHON" = "1" ]; then exit 1; fi\n'
            f'exec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
        uv = binary / "uv"
        uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$UV_CALLS"\n', encoding="utf-8")
        python.chmod(0o755)
        uv.chmod(0o755)
        for old in (True, False):
            log = self.root / f"uv-{old}.log"
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                       OLD_PYTHON="1" if old else "0", UV_CALLS=str(log))
            result = subprocess.run(["bash", str(self.root / "setup.sh")], cwd=self.root.parent, env=env,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, int(old), result.stdout + result.stderr)
            if old:
                self.assertFalse(log.exists())
            else:
                self.assertIn(f"MoreGAN {self.version}", result.stdout)
                self.assertEqual(log.read_text().splitlines(), ["sync --python python3", "run python install.py"])


if __name__ == "__main__":
    unittest.main()
