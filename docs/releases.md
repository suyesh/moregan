# Releases And Distribution

## Maintainer Policy

Publication resumed at the maintainer's request on September 27, 2026. Meaningful
features, runtime/installer fixes and distribution changes get a version bump,
release notes, a GitHub release and PyPI publication after verification. Docs-only
or internal changes can be pushed without a release; state that decision explicitly.
This supersedes the earlier pause recorded in historical progress entries.

The first release under this policy is **1.16.0**. It also packages the intervening
1.6.0-1.15.0 work that was not published during the pause. See
[release notes](release-notes/1.16.0.md). The authoritative publication status is
the [Actions run](https://github.com/suyesh/moregan/actions/workflows/workflow.yml),
[GitHub releases](https://github.com/suyesh/moregan/releases) and
[PyPI files](https://pypi.org/project/moregan/#files), not a successful Git push.

## Pipeline

1. A push to `main` or a pull request runs [CI](../.github/workflows/ci.yml).
2. A pushed `v<version>` tag, published GitHub release or manual dispatch on a tag
   starts [workflow.yml](../.github/workflows/workflow.yml). Branch dispatches,
   mismatched metadata, missing notes, drafts and prereleases are rejected.
3. The same CI workflow builds wheel/sdist, validates metadata and README rendering,
   runs all tests on Python 3.10-3.14 for Linux/macOS, and exercises the exact wheel
   in fresh environments outside the checkout. Windows 3.10/3.14 packaging smoke
   is also required, but is not a full Windows-runtime support claim.
4. After all gates pass, the workflow creates the GitHub release for the existing
   tag, with notes and distributions. An existing release is not overwritten.
5. A separate, narrowly permissioned job downloads those tested artifacts and
   publishes them through PyPI Trusted Publishing. It does not rebuild them.

Python 3.10 is the declared minimum. Windows descendant cleanup and escaped POSIX
processes remain limitations. Simulated-provider CI proves packaging and plumbing,
not live-model effectiveness. See [installation](../INSTALL.md).

Configured Trusted Publisher identity remains:

```text
Owner: suyesh
Repository: moregan
Workflow filename: workflow.yml
Environment: pypi
PyPI project: moregan
```

Environment approval rules and PyPI publisher configuration must allow this
workflow/tag. Repository files alone do not establish that external setup.
Only the publisher job gets `id-token: write`; only release creation gets
`contents: write`. PR tests get neither. No long-lived PyPI token is used.

## Release Checklist

- Update package, runtime, installer, skill and lock versions together. Regenerate
  the lock with public PyPI and add `docs/release-notes/<version>.md`.
- Run the test extra, metadata validator, build, strict Twine checks and installed
  smoke. CI repeats these checks on the tagged commit, not merely a prior main run.
- Commit/push, inspect CI, then create and push the matching version tag. Do not
  move an already published tag or overwrite an existing PyPI version.
- Watch the release workflow through completion and confirm the files on PyPI.
  A GitHub release can exist even if environment approval or PyPI publication fails.
- If a gate fails, fix and retest. If a publication request fails, check whether
  files were uploaded before retrying; never claim success from release creation
  alone. Existing-file errors are not suppressed with `skip-existing`.
- Do not uninstall a working environment before an upgrade succeeds. Use a separate
  venv to evaluate a release, preserve project configuration, and deliberately
  refresh installed skill copies after upgrading the CLI. Failed skill updates
  have installer backups; inspect those before attempting manual restoration.

The release workflow uses a shared CI job according to
[GitHub reusable-workflow documentation](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).
Creating a release with `GITHUB_TOKEN` does not trigger a recursive release run;
publication therefore stays in the same workflow. See
[GitHub event rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
and [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/).
