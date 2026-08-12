import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install


class MoreGANInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source_dir = self.root / "source"
        self.home = self.root / "home"
        self.source_dir.mkdir()
        self.home.mkdir()

        (self.source_dir / ".moregan").mkdir()
        (self.source_dir / ".moregan" / "tools.yaml").write_text("version: 1\ncommands: []\n", encoding="utf-8")
        (self.source_dir / ".moregan" / "workers.yaml").write_text("version: 1\nworkers: []\n", encoding="utf-8")
        (self.source_dir / "personas").mkdir()
        (self.source_dir / "moregan").mkdir()
        for file_name in ["SKILL.md", "README.md", "INSTALL.md", "ROADMAP.md", "LICENSE", "install.py"]:
            (self.source_dir / file_name).write_text(file_name, encoding="utf-8")
        (self.source_dir / "assets").mkdir()
        (self.source_dir / "assets" / "moregan.png").write_bytes(b"png")
        (self.source_dir / "moregan" / "__init__.py").write_text("", encoding="utf-8")
        (self.source_dir / "moregan" / "adapters.py").write_text("adapters", encoding="utf-8")
        (self.source_dir / "moregan" / "agent_worker.py").write_text("agent_worker", encoding="utf-8")
        (self.source_dir / "moregan" / "cli.py").write_text("cli", encoding="utf-8")
        (self.source_dir / "moregan" / "context.py").write_text("context", encoding="utf-8")
        (self.source_dir / "moregan" / "init.py").write_text("init", encoding="utf-8")
        (self.source_dir / "moregan" / "runtime.py").write_text("runtime", encoding="utf-8")
        (self.source_dir / "moregan" / "schemas.py").write_text("schemas", encoding="utf-8")
        (self.source_dir / "moregan" / "state.py").write_text("state", encoding="utf-8")
        (self.source_dir / "moregan" / "tools.py").write_text("tools", encoding="utf-8")
        (self.source_dir / "moregan" / "workers.py").write_text("workers", encoding="utf-8")
        (self.source_dir / "moregan" / "replay.py").write_text("replay", encoding="utf-8")
        for persona_name in install.CLAUDE_PERSONAS:
            (self.source_dir / "personas" / persona_name).write_text(persona_name, encoding="utf-8")

        (self.home / ".claude" / "skills").mkdir(parents=True)
        (self.home / ".claude" / "agents").mkdir(parents=True)
        (self.home / ".codex" / "skills").mkdir(parents=True)

        self.installer = install.MoreGANInstaller(source_dir=self.source_dir, home=self.home)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_doctor_removes_duplicate_directories_and_dedupes_registry(self):
        canonical = self.home / ".claude" / "skills" / install.SKILL_NAME
        duplicate = self.home / ".claude" / "skills" / f"{install.SKILL_NAME}.backup.20260513"
        canonical.mkdir(parents=True)
        duplicate.mkdir(parents=True)
        for name in install.CLAUDE_REQUIRED_FILES:
            path = canonical / name
            if name in {".moregan", "personas", "moregan", "assets"}:
                path.mkdir()
            else:
                path.write_text(name, encoding="utf-8")

        registry_file = self.home / ".claude" / "skills.json"
        registry_file.write_text(
            json.dumps(
                {
                    "skills": [
                        {"name": install.SKILL_NAME, "path": "one"},
                        {"name": install.SKILL_NAME, "path": "two"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        self.installer.install_targets = ["claude"]
        self.assertTrue(self.installer.doctor(apply_fixes=True))
        self.assertFalse(duplicate.exists())

        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        entries = [entry for entry in registry["skills"] if entry["name"] == install.SKILL_NAME]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], str(self.installer.claude_path["global_skills"]))

    def test_install_copies_maintenance_assets_and_manifest(self):
        (self.source_dir / ".git").mkdir()
        self.installer.install_targets = ["claude"]

        self.assertTrue(self.installer.install_files())

        skill_dir = self.installer.claude_path["global_skills"]
        self.assertTrue((skill_dir / "install.py").exists())
        self.assertTrue((skill_dir / "INSTALL.md").exists())
        self.assertTrue((skill_dir / "ROADMAP.md").exists())
        self.assertTrue((skill_dir / "LICENSE").exists())
        self.assertTrue((skill_dir / "assets" / "moregan.png").exists())
        self.assertTrue((skill_dir / "moregan" / "adapters.py").exists())
        self.assertTrue((skill_dir / "moregan" / "agent_worker.py").exists())
        self.assertTrue((skill_dir / "moregan" / "cli.py").exists())
        self.assertTrue((skill_dir / "moregan" / "context.py").exists())
        self.assertTrue((skill_dir / "moregan" / "init.py").exists())
        self.assertTrue((skill_dir / "moregan" / "schemas.py").exists())
        self.assertTrue((skill_dir / "moregan" / "state.py").exists())
        self.assertTrue((skill_dir / "moregan" / "tools.py").exists())
        self.assertTrue((skill_dir / "moregan" / "workers.py").exists())
        self.assertTrue((skill_dir / "moregan" / "replay.py").exists())
        self.assertTrue((skill_dir / ".moregan" / "tools.yaml").exists())
        self.assertTrue((skill_dir / ".moregan" / "workers.yaml").exists())
        self.assertTrue((skill_dir / "personas" / "Planner.md").exists())
        self.assertTrue((skill_dir / "personas" / "CodeReviewer.md").exists())
        self.assertTrue((skill_dir / "personas" / "ProductionReadinessReviewer.md").exists())
        self.assertTrue((skill_dir / "personas" / "MRReadinessAnalyzer.md").exists())
        self.assertTrue((skill_dir / "personas" / "LearningCurator.md").exists())
        self.assertTrue((self.installer.claude_path["global_agents"] / "moregan-code-reviewer.md").exists())
        self.assertTrue(
            (self.installer.claude_path["global_agents"] / "moregan-production-readiness-reviewer.md").exists()
        )
        self.assertTrue((self.installer.claude_path["global_agents"] / "moregan-mr-readiness-analyzer.md").exists())
        self.assertTrue((self.installer.claude_path["global_agents"] / "moregan-learning-curator.md").exists())

        manifest = json.loads((skill_dir / install.INSTALL_MANIFEST_PATH).read_text(encoding="utf-8"))
        self.assertEqual(manifest["target"], "claude")
        self.assertEqual(Path(manifest["source_checkout"]).resolve(), self.source_dir.resolve())
        self.assertIn("repository_url", manifest)

    def test_codex_install_copies_installer_and_new_personas(self):
        (self.source_dir / ".git").mkdir()
        self.installer.install_targets = ["codex"]

        self.assertTrue(self.installer.install_files())

        skill_dir = self.installer.codex_path["global_skills"]
        self.assertTrue((skill_dir / "install.py").exists())
        self.assertTrue((skill_dir / "LICENSE").exists())
        self.assertTrue((skill_dir / "assets" / "moregan.png").exists())
        self.assertTrue((skill_dir / "moregan" / "adapters.py").exists())
        self.assertTrue((skill_dir / "moregan" / "agent_worker.py").exists())
        self.assertTrue((skill_dir / "moregan" / "context.py").exists())
        self.assertTrue((skill_dir / "moregan" / "init.py").exists())
        self.assertTrue((skill_dir / "moregan" / "runtime.py").exists())
        self.assertTrue((skill_dir / "moregan" / "schemas.py").exists())
        self.assertTrue((skill_dir / "moregan" / "state.py").exists())
        self.assertTrue((skill_dir / "moregan" / "tools.py").exists())
        self.assertTrue((skill_dir / "moregan" / "workers.py").exists())
        self.assertTrue((skill_dir / "moregan" / "replay.py").exists())
        self.assertTrue((skill_dir / "personas" / "CodeReviewer.md").exists())
        self.assertTrue((skill_dir / "personas" / "ProductionReadinessReviewer.md").exists())
        self.assertTrue((skill_dir / "personas" / "MRReadinessAnalyzer.md").exists())
        self.assertTrue((skill_dir / "personas" / "LearningCurator.md").exists())

        manifest = json.loads((skill_dir / install.INSTALL_MANIFEST_PATH).read_text(encoding="utf-8"))
        self.assertEqual(manifest["target"], "codex")

    def test_create_backup_uses_hidden_backup_root_not_skills_sibling(self):
        skill_dir = self.installer.claude_path["global_skills"]
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("skill", encoding="utf-8")

        backup_path = self.installer.create_backup(skill_dir)

        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())
        self.assertEqual(
            backup_path.parent.resolve(),
            (self.home / ".claude" / "backups" / install.SKILL_NAME).resolve(),
        )
        self.assertNotEqual(backup_path.parent, skill_dir.parent)

    def test_install_moves_sibling_backups_out_of_skills_directory(self):
        sibling_backup = self.home / ".claude" / "skills" / f"{install.SKILL_NAME}.backup.20260513"
        sibling_backup.mkdir(parents=True)
        (sibling_backup / "SKILL.md").write_text("backup", encoding="utf-8")

        (self.source_dir / ".git").mkdir()
        self.installer.install_targets = ["claude"]
        self.assertTrue(self.installer.install_files())

        backup_root = self.home / ".claude" / "backups" / install.SKILL_NAME
        moved_backups = list(backup_root.glob(f"{install.SKILL_NAME}.backup.20260513*"))
        self.assertTrue(moved_backups)
        self.assertFalse(sibling_backup.exists())

    def test_doctor_check_mode_reports_without_fixing(self):
        duplicate = self.home / ".codex" / "skills" / f"{install.SKILL_NAME}.backup.20260513"
        duplicate.mkdir(parents=True)

        self.installer.install_targets = ["codex"]
        self.assertFalse(self.installer.doctor(apply_fixes=False))
        self.assertTrue(duplicate.exists())

    def test_repository_url_normalizes_github_ssh_remote(self):
        (self.source_dir / ".git").mkdir()

        def fake_output(command):
            if command == ["git", "config", "--get", "remote.origin.url"]:
                return "git@github.com:suyesh/moregan.git\n"
            raise AssertionError(command)

        self.installer._git_output = fake_output
        self.assertEqual(self.installer._get_repository_url(), "https://github.com/suyesh/moregan")

    def test_default_repository_url_points_to_canonical_repo(self):
        self.assertEqual(install.DEFAULT_REPOSITORY_URL, "https://github.com/suyesh/moregan")

    def test_pyproject_packages_moregan_for_pypi_install(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('name = "moregan"', pyproject)
        self.assertNotIn("moregan-installer", pyproject)
        self.assertNotIn("package = false", pyproject)
        self.assertIn('moregan = "moregan.cli:main"', pyproject)
        self.assertIn('"install.py" = "install.py"', pyproject)
        self.assertIn('"SKILL.md" = "SKILL.md"', pyproject)
        self.assertIn('"assets" = "assets"', pyproject)
        self.assertIn('"personas" = "personas"', pyproject)
        self.assertIn('".moregan/tools.yaml" = ".moregan/tools.yaml"', pyproject)
        self.assertIn('".moregan/workers.yaml" = ".moregan/workers.yaml"', pyproject)

    def test_package_version_constants_match(self):
        repo_root = Path(__file__).resolve().parents[1]
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        init_py = (repo_root / "moregan" / "__init__.py").read_text(encoding="utf-8")

        self.assertIn(f'version = "{install.VERSION}"', pyproject)
        self.assertIn(f'__version__ = "{install.VERSION}"', init_py)

    def test_pypi_trusted_publishing_workflow_exists_with_expected_filename(self):
        repo_root = Path(__file__).resolve().parents[1]
        workflow = repo_root / ".github" / "workflows" / "workflow.yml"

        self.assertTrue(workflow.exists())
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("id-token: write", text)
        self.assertIn("pypa/gh-action-pypi-publish@release/v1", text)
        self.assertIn("environment:", text)
        self.assertIn("name: pypi", text)
        self.assertIn("https://pypi.org/p/moregan", text)

    def test_update_uses_downloaded_archive_source(self):
        installed_codex_skill = self.installer.codex_path["global_skills"]
        installed_codex_skill.mkdir(parents=True)
        (installed_codex_skill / "SKILL.md").write_text("installed", encoding="utf-8")
        self.installer.install_targets = ["codex"]

        download_dir = self.root / "downloaded"
        download_dir.mkdir()
        for file_name in ["SKILL.md", "README.md", "INSTALL.md", "ROADMAP.md", "LICENSE", "install.py"]:
            (download_dir / file_name).write_text(file_name, encoding="utf-8")
        (download_dir / "assets").mkdir()
        (download_dir / "assets" / "moregan.png").write_bytes(b"png")
        (download_dir / ".moregan").mkdir()
        (download_dir / ".moregan" / "tools.yaml").write_text("version: 1\ncommands: []\n", encoding="utf-8")
        (download_dir / ".moregan" / "workers.yaml").write_text("version: 1\nworkers: []\n", encoding="utf-8")
        (download_dir / "personas").mkdir()
        (download_dir / "moregan").mkdir()
        (download_dir / "moregan" / "__init__.py").write_text("", encoding="utf-8")
        (download_dir / "moregan" / "adapters.py").write_text("adapters", encoding="utf-8")
        (download_dir / "moregan" / "agent_worker.py").write_text("agent_worker", encoding="utf-8")
        (download_dir / "moregan" / "cli.py").write_text("cli", encoding="utf-8")
        (download_dir / "moregan" / "init.py").write_text("init", encoding="utf-8")
        (download_dir / "moregan" / "runtime.py").write_text("runtime", encoding="utf-8")
        (download_dir / "moregan" / "schemas.py").write_text("schemas", encoding="utf-8")
        (download_dir / "moregan" / "state.py").write_text("state", encoding="utf-8")
        (download_dir / "moregan" / "tools.py").write_text("tools", encoding="utf-8")
        (download_dir / "moregan" / "workers.py").write_text("workers", encoding="utf-8")
        (download_dir / "moregan" / "replay.py").write_text("replay", encoding="utf-8")
        for persona_name in install.CLAUDE_PERSONAS:
            (download_dir / "personas" / persona_name).write_text(persona_name, encoding="utf-8")

        with patch.object(self.installer, "_download_update_source", autospec=True) as download_source:
            download_source.return_value = download_dir
            self.assertTrue(self.installer.update_installation(force=False))

        self.assertTrue((self.installer.codex_path["global_skills"] / "SKILL.md").exists())
        download_source.assert_called_once()

    def test_update_does_not_create_visible_duplicate_skill_directories(self):
        skill_dir = self.installer.claude_path["global_skills"]
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("existing", encoding="utf-8")
        (skill_dir / "README.md").write_text("existing", encoding="utf-8")
        (skill_dir / "INSTALL.md").write_text("existing", encoding="utf-8")
        (skill_dir / "ROADMAP.md").write_text("existing", encoding="utf-8")
        (skill_dir / "LICENSE").write_text("existing", encoding="utf-8")
        (skill_dir / "install.py").write_text("existing", encoding="utf-8")
        (skill_dir / "assets").mkdir()
        (skill_dir / ".moregan").mkdir()
        (skill_dir / "personas").mkdir()
        (skill_dir / "moregan").mkdir()
        self.installer.install_targets = ["claude"]

        download_dir = self.root / "downloaded-update"
        download_dir.mkdir()
        for file_name in ["SKILL.md", "README.md", "INSTALL.md", "ROADMAP.md", "LICENSE", "install.py"]:
            (download_dir / file_name).write_text(file_name, encoding="utf-8")
        (download_dir / "assets").mkdir()
        (download_dir / "assets" / "moregan.png").write_bytes(b"png")
        (download_dir / ".moregan").mkdir()
        (download_dir / ".moregan" / "tools.yaml").write_text("version: 1\ncommands: []\n", encoding="utf-8")
        (download_dir / ".moregan" / "workers.yaml").write_text("version: 1\nworkers: []\n", encoding="utf-8")
        (download_dir / "personas").mkdir()
        (download_dir / "moregan").mkdir()
        (download_dir / "moregan" / "__init__.py").write_text("", encoding="utf-8")
        (download_dir / "moregan" / "adapters.py").write_text("adapters", encoding="utf-8")
        (download_dir / "moregan" / "agent_worker.py").write_text("agent_worker", encoding="utf-8")
        (download_dir / "moregan" / "cli.py").write_text("cli", encoding="utf-8")
        (download_dir / "moregan" / "init.py").write_text("init", encoding="utf-8")
        (download_dir / "moregan" / "runtime.py").write_text("runtime", encoding="utf-8")
        (download_dir / "moregan" / "schemas.py").write_text("schemas", encoding="utf-8")
        (download_dir / "moregan" / "state.py").write_text("state", encoding="utf-8")
        (download_dir / "moregan" / "tools.py").write_text("tools", encoding="utf-8")
        (download_dir / "moregan" / "workers.py").write_text("workers", encoding="utf-8")
        (download_dir / "moregan" / "replay.py").write_text("replay", encoding="utf-8")
        for persona_name in install.CLAUDE_PERSONAS:
            (download_dir / "personas" / persona_name).write_text(persona_name, encoding="utf-8")

        with patch.object(self.installer, "_download_update_source", autospec=True) as download_source:
            download_source.return_value = download_dir
            self.assertTrue(self.installer.update_installation(force=False))

        visible_skill_dirs = sorted(path.name for path in skill_dir.parent.glob(f"{install.SKILL_NAME}*") if path.is_dir())
        self.assertEqual(visible_skill_dirs, [install.SKILL_NAME])

        backup_root = self.home / ".claude" / "backups" / install.SKILL_NAME
        self.assertTrue(backup_root.exists())
        self.assertTrue(any(path.is_dir() for path in backup_root.iterdir()))

    def test_download_update_source_uses_https_archive_url(self):
        destination_root = self.root / "archive-download"
        archive_root = f"{install.SKILL_NAME}-main"
        with patch.object(self.installer, "_get_repository_url", autospec=True) as get_repo_url:
            get_repo_url.return_value = "https://github.com/suyesh/moregan"
            with patch("install.urlopen", autospec=True) as mocked_urlopen:
                import io
                import zipfile

                payload = io.BytesIO()
                with zipfile.ZipFile(payload, "w") as archive:
                    archive.writestr(f"{archive_root}/SKILL.md", "skill")
                    archive.writestr(f"{archive_root}/README.md", "readme")
                mocked_urlopen.return_value.__enter__.return_value.read.return_value = payload.getvalue()

                extracted = self.installer._download_update_source("main", destination_root)

        self.assertEqual(extracted.name, archive_root)
        mocked_urlopen.assert_called_once_with("https://github.com/suyesh/moregan/archive/main.zip")

    def test_skill_defines_mandatory_persona_execution_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        skill_text = (repo_root / "SKILL.md").read_text(encoding="utf-8")
        defaults_text = (repo_root / ".moregan" / "defaults.yaml").read_text(encoding="utf-8")

        self.assertIn("### Mandatory Persona Execution", skill_text)
        for persona_name in [
            "Planner",
            "Architect",
            "Generator",
            "Evaluator",
            "Security Evaluator",
            "Code Reviewer",
            "Production Readiness Reviewer",
            "MR Readiness Analyzer",
            "Learning Curator",
        ]:
            self.assertIn(persona_name, skill_text)

        self.assertIn("Designer is the only conditional persona", skill_text)
        self.assertIn("MR readiness must always be run and its score must always be shown", skill_text)
        self.assertIn("Learning Curator must always run after MR readiness", skill_text)
        self.assertIn("Format the persona execution summary with colored status markers", skill_text)
        self.assertIn("🟢 PASS", skill_text)
        self.assertIn("🟢 Production Readiness Reviewer", skill_text)
        self.assertIn("🔴 MR Readiness Analyzer", skill_text)
        self.assertIn("🟢 Learning Curator", skill_text)
        self.assertIn("mandatory_for_every_feature_task:", defaults_text)
        self.assertIn("production_readiness_reviewer", defaults_text)
        self.assertIn("mr_readiness_analyzer", defaults_text)
        self.assertIn("learning_curator", defaults_text)
        self.assertIn("decision_required_for_every_feature_task: true", defaults_text)
        self.assertIn("include_mr_readiness_result: true", defaults_text)
        self.assertIn("include_learning_curator_result: true", defaults_text)
        self.assertIn("use_colored_status_markers: true", defaults_text)
        self.assertIn('not_ready: "🔴"', defaults_text)

    def test_learning_curator_persona_defines_conservative_learning_contract(self):
        repo_root = Path(__file__).resolve().parents[1]
        persona_text = (repo_root / "personas" / "LearningCurator.md").read_text(encoding="utf-8")
        retrospectives_text = (
            repo_root / ".moregan" / "knowledge" / "retrospectives.yaml"
        ).read_text(encoding="utf-8")

        self.assertIn("sole purpose is to learn from past work", persona_text)
        self.assertIn("Run after the MR Readiness Analyzer", persona_text)
        self.assertIn(".moregan/knowledge/retrospectives.yaml", persona_text)
        self.assertIn("First occurrence", persona_text)
        self.assertIn("Third occurrence", persona_text)
        self.assertIn("Learning Curator Verdict: PASS|FAIL", persona_text)
        self.assertIn("promotion_policy:", retrospectives_text)
        self.assertIn("observations: []", retrospectives_text)


if __name__ == "__main__":
    unittest.main()
