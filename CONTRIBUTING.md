# Development and contributions

Use Ubuntu/WSL2 with Python 3.10 for the baseline. Follow [installation](docs/INSTALLATION.md), then run `bash scripts/check.sh`. The lock includes the test dependencies. No Node build is required for `web/`.

Tests create temporary databases and synthetic evidence. `scripts/check.sh` deliberately does not source the deployment `.env`. Never run exploratory scripts against a live customer database. Never use production connector credentials in tests. OCR tests require Poppler and Tesseract; AI citation tests use controlled responses, not a downloaded model.

## Changes

1. Create a branch and keep changes focused on a concrete problem.
2. Add meaningful regression coverage for workflow, security, calculation or persistence changes. Preserve human approval boundaries.
3. Run tests and `pip check`; inspect the browser for UI changes.
4. Regenerate `openapi.json` if API models/routes change and update documentation/examples.
5. Describe behavior, validation and limitations in the pull request. Include synthetic reproductions only.

Database changes belong in `backend/db.py` with migration/version handling. Verify existing installations, approval fingerprints/snapshots, rollback needs and backup/restore behavior. Never assume a code rollback reverses schema/data migrations. Do not add a second Uvicorn worker without redesigning queue coordination.

Financial changes must preserve explicit units, currency, Decimal rounding, scope, forecast/actual separation and conflict checks. Model changes must preserve read-only use and citation validation; document that citations do not establish factual entailment.

## Dependency and release maintenance

Review dependency updates rather than blindly regenerating pins. Build a clean environment, test installation, audit dependencies with a current scanner, run the suite, verify a fresh service/synthetic workflow and record commit/environment/results. OS OCR parsers and model runtimes require separate maintenance. CI installation from a clean environment is a required release signal, not proof of production capacity.

Tag reviewed releases; include release notes and migration instructions. Keep secrets, runtime data and generated customer artifacts out of Git history. Contributions are distributed under the repository's MIT license; third-party assets and dependencies retain their licenses.

## Enable GitHub Actions

The tested workflow configuration is supplied as `deploy/github-actions-ci.yml`. It is an **inactive template**, not an enabled Actions workflow: the publishing credential did not have GitHub's `workflow` scope. An authorized maintainer can copy it to `.github/workflows/ci.yml` and commit through GitHub or a credential with workflow permission. It installs Python 3.10 and OCR tools, installs the lockfile, runs isolated regression tests and exercises the real HTTP worker smoke check. Verify its first run before relying on CI as a release gate.
