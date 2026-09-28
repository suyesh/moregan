# MoreGAN Installation

Installing the CLI, installing a skill, and configuring provider workers are
three separate steps. Only the CLI is required to use the runtime.

## Choose A Version

This guide describes **1.16.0**, requiring Python **3.10+**. Use a published
[PyPI release](https://pypi.org/project/moregan/) or install the source below.
Main-branch pushes run CI; version tags also trigger a checked GitHub/PyPI release.
See [release policy](docs/releases.md).

## Current Runtime

The following shell commands use a virtual environment on macOS/Linux:

```bash
git clone https://github.com/suyesh/moregan.git
cd moregan
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
moregan --help
python -c "import moregan; print(moregan.__version__, moregan.__file__)"
```

Keep the environment active when moving to your application repository so
`moregan` resolves to the intended installation. New worker templates record that
interpreter's path. Regenerate them if the environment moves or is replaced;
existing configurations are preserved, not automatically migrated.

For checkout development with uv:

```bash
uv sync --extra test
uv run moregan --help
uv run moregan --root /absolute/path/to/your-project init
```

`--root` is a global option and goes **before** the subcommand. Git enables patch
risk inspection and is required for benchmark fixtures. Project build tools and
provider CLIs/bridges are separate dependencies; MoreGAN does not install them.

CI runs the regression suite and installed-wheel smoke on Linux/macOS with Python
3.10-3.14. Windows smoke coverage is limited to installation, simulated workers,
CLI outcomes and skill assets on 3.10/3.14; the full runtime and descendant-process
containment remain experimental. Windows users can create a venv with
`python -m venv .venv` and activate it with `.\.venv\Scripts\Activate.ps1`.
Python 3.8/3.9 are no longer supported. Newer interpreter versions are not claimed
as tested until added to the matrix.

## Published Package

Inside an active virtual environment, install a release matching this guide:

```bash
python -m pip install --upgrade "moregan>=1.16.0"
```

If the requested release is not yet published, use the source path above or wait
for its publication gates. A newer GitHub README does not update an installed
package automatically.

## Optional Skill Installation

With the desired runtime installed:

```bash
moregan setup --target codex
moregan setup --target claude
# Or select both:
moregan setup --target both
```

Choose the target(s) you use; these are alternatives, not required consecutive
steps. Without `--target`, the installer detects environments and prompts.

`moregan setup` invokes the Python installer directly. It does **not** execute
`./setup.sh`. The shell/batch setup scripts bootstrap uv and invoke that same
installer; they are not necessary for a pip-installed CLI. Both scripts check the
Python minimum and display the runtime version instead of a fixed old banner.

| Target | Installed files |
|---|---|
| Codex | `~/.codex/skills/moregan/` with skill, personas, runtime, docs and defaults |
| Claude | `~/.claude/skills/moregan/`, plus `~/.claude/agents/moregan-*.md` |

The installer also copies configuration/reference material. Files describing
rollback, multi-generator coordination, external integrations or living docs
do not activate runtime features merely by being installed. See
[what is implemented](docs/product-status.md).

## Configure A Project

Follow [Getting Started](docs/getting-started.md) to initialize `.moregan/`, choose
one worker template, configure a provider bridge and review deterministic checks.

Important: `init` writes an empty `workers.yaml`. `adapters --activate` preserves
that file unless replacement is explicitly requested. The guide shows how to
select a template without accidentally replacing customized prompts.

Skills are intended to launch the same runtime. They still need a working Python
environment and provider configuration visible to the agent process. A graphical
app may not inherit exports from a terminal opened later; confirm the provider
variable inside the agent's terminal without printing credentials.

## Updates And Maintenance

| Goal | Command / behavior |
|---|---|
| Upgrade a PyPI-installed CLI | `python -m pip install --upgrade moregan`, limited to published versions |
| Update an editable checkout | Review/pull the desired Git revision and resync its environment |
| Refresh installed skill copies | `moregan setup update --ref main` downloads the GitHub archive and reinstalls targets |
| Check installed skill files | `moregan setup doctor --check` reports missing files and duplicate installations |

Skill updates do not upgrade a separate pip environment. Check the runtime and
skill versions together. `doctor` concerns installation files, not provider
authentication, test coverage, or production readiness. Without `--check`, doctor
can repair installations; review that behavior before using it.

Claude skill maintenance uses `/moregan update` or `/moregan doctor`; in Codex,
ask `Use MoreGAN to update` or `Use MoreGAN to run doctor`.

## Removal

```bash
moregan setup uninstall --target both
python -m pip uninstall moregan
```

The first command removes skill installations; the second removes the Python
package from the active environment. Project `.moregan/` configurations and run
artifacts are separate from package installation. Inspect them before removing
any project data.

For setup problems, see [troubleshooting](docs/getting-started.md#troubleshooting)
or open an [issue](https://github.com/suyesh/moregan/issues).
