# Release Status

Checked September 27, 2026 against the
[PyPI project](https://pypi.org/project/moregan/) and its
[JSON metadata](https://pypi.org/pypi/moregan/json):

| Channel | Version | Availability |
|---|---|---|
| GitHub `main` | 1.15.0 | Current source implementation |
| PyPI | 1.5.0 | Wheel and sdist uploaded August 12, 2026 |

These are dated observations, not an automatically synchronized status page.
`pip install --upgrade moregan` uses published distributions; it cannot install
unreleased source changes. See [installation](../INSTALL.md) for the GitHub path.

## What Triggers Publication

[`.github/workflows/workflow.yml`](../.github/workflows/workflow.yml) currently
runs for a published GitHub release or manual workflow dispatch. It does **not**
run merely because a commit was pushed to `main`. The workflow builds and uses
PyPI Trusted Publishing through the GitHub `pypi` environment.

Configured identity:

```text
Owner: suyesh
Repository: moregan
Workflow filename: workflow.yml
Environment: pypi
PyPI project: moregan
```

The repository configuration alone does not prove the PyPI publisher or environment
approvals are correctly set up. No credentials or deployment settings were changed
during this documentation audit.

## Current Policy

Publication remains paused at the maintainer's prior request. No release/tag was
created and no publishing workflow was dispatched for 1.6.0 through 1.15.0 by this
work. Local wheel/sdist builds and GitHub pushes are not PyPI publication.

Before resuming, add supported-version test and installed-package smoke gates to
publication. The current publishing workflow builds/uploads without running the
test suite. Resolve the advertised Python 3.8 incompatibility and clearly state
platform limitations. Keep `workflow.yml` as the Trusted Publishing filename.

Updating the GitHub README does not update the rendered description on an existing
PyPI release. That description is packaged with the distribution; a subsequent
release should carry the corrected documentation.
