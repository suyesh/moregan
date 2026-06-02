# Development Init

## Local workflow

1. Sync Python dependencies:
   `uv sync --python python3`
2. Run the installer interactively:
   `uv run python install.py`
3. Run maintenance commands directly:
   `uv run python install.py update`
   `uv run python install.py doctor`
4. Run the test suite:
   `uv run python -m unittest discover -s tests`

## Development server

This repository is a Python CLI installer and skill bundle, not a web app. There is no development server to start. Downstream agents should use the local CLI and test commands above.

## Notes

- `update` downloads the configured GitHub repository archive over HTTPS for the requested ref, then reinstalls from the downloaded source.
- `doctor` repairs installed files, deduplicates Claude registry entries, and removes duplicate install directories.
