"""Fail closed on inconsistent source, distribution metadata or release events."""

import argparse
import ast
from email.parser import BytesParser
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

try:
    import tomllib
except ImportError:
    import tomli as tomllib


def constant(path, name):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing {name} in {path}")


def validate_source(root):
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must be major.minor.patch")
    if project["name"] != "moregan" or project["requires-python"] != ">=3.10":
        raise ValueError("Unexpected package name or Python support range")
    versions = [constant(root / "moregan/__init__.py", "__version__"), constant(root / "install.py", "VERSION")]
    frontmatter = (root / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r"^version: (\S+)$", frontmatter, re.MULTILINE)
    versions.append(match.group(1) if match else None)
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = [item for item in lock["package"] if item["name"] == "moregan"]
    if len(packages) != 1 or lock["requires-python"] != project["requires-python"]:
        raise ValueError("Lock metadata does not match the project")
    versions.append(packages[0]["version"])
    if any(item != version for item in versions):
        raise ValueError(f"Version mismatch: project={version}, components={versions}")
    return project


def validate_distributions(folder, project):
    version = project["version"]
    expected = {f"moregan-{version}-py3-none-any.whl", f"moregan-{version}.tar.gz"}
    if {path.name for path in folder.iterdir()} - {".gitignore"} != expected:
        raise ValueError("Expected exactly one wheel and one sdist for this version")
    if any(path.is_symlink() or not path.is_file() for path in folder.iterdir()):
        raise ValueError("Distributions must be regular files")
    with zipfile.ZipFile(folder / f"moregan-{version}-py3-none-any.whl") as wheel:
        metadata_names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Wheel must contain exactly one metadata file")
        wheel_metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
        required = {"moregan/runtime.py", "install.py", "SKILL.md", "README.md", "INSTALL.md",
                    "personas/Generator.md", "assets/moregan.png", "docs/getting-started.md"}
        if not required.issubset(wheel.namelist()):
            raise ValueError("Wheel is missing runtime or skill assets")
        forbidden = (".moregan/runs/", ".moregan/backups/", ".moregan/learning/", ".moregan/benchmarks/runs/")
        if any(name.startswith(forbidden) for name in wheel.namelist()):
            raise ValueError("Wheel contains local run data")
    with tarfile.open(folder / f"moregan-{version}.tar.gz") as sdist:
        required_source = {f"moregan-{version}/{name}" for name in (
            "pyproject.toml", "uv.lock", "scripts/ci/release.py", "scripts/ci/installed_smoke.py",
            ".github/workflows/ci.yml", ".github/workflows/workflow.yml", "tests/test_release.py")}
        if not required_source.issubset(sdist.getnames()):
            raise ValueError("sdist is missing release-test inputs")
        member = sdist.getmember(f"moregan-{version}/PKG-INFO")
        if not member.isfile():
            raise ValueError("sdist metadata must be a regular file")
        with sdist.extractfile(member) as source:
            sdist_metadata = BytesParser().parsebytes(source.read())
    for metadata in (wheel_metadata, sdist_metadata):
        if (metadata["Name"], metadata["Version"], metadata["Requires-Python"]) != (
                project["name"], version, project["requires-python"]):
            raise ValueError("Distribution metadata does not match source")


def validate_event(root, project, event, env):
    tag = f"v{project['version']}"
    if env.get("GITHUB_REF") != f"refs/tags/{tag}":
        raise ValueError("Publishing requires a tag matching the package version, never a branch")
    name = env.get("GITHUB_EVENT_NAME")
    if name == "release":
        release = event.get("release", {})
        if (event.get("action") != "published" or release.get("tag_name") != tag
                or release.get("draft") is not False or release.get("prerelease") is not False):
            raise ValueError("Only a published, stable release with a matching tag may publish")
    elif name == "push":
        if event.get("ref") != f"refs/tags/{tag}" or event.get("deleted") is not False:
            raise ValueError("Only a non-deleted matching version tag may publish")
    elif name != "workflow_dispatch":
        raise ValueError("Unsupported publishing event")
    def git(ref):
        return subprocess.check_output(["git", "rev-parse", "--verify", ref], cwd=root, text=True).strip()
    if git(f"refs/tags/{tag}^{{commit}}") != git("HEAD"):
        raise ValueError("Checked-out commit does not match the release tag")
    notes = root / "docs/release-notes" / f"{project['version']}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ValueError("Release notes are required")
    return tag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--event", type=Path)
    args = parser.parse_args()
    project = validate_source(args.root)
    if args.dist:
        validate_distributions(args.dist, project)
    if args.event:
        tag = validate_event(args.root, project, json.loads(args.event.read_text(encoding="utf-8")), os.environ)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"tag={tag}\n")
    print(f"Release validation passed: moregan {project['version']}")


if __name__ == "__main__":
    main()
