# Release verification

Portable distribution 1.2.1 was checked on 6 November 2026 using Ubuntu 22.04 / WSL2 and Python 3.10.

## Verified

- A new virtual environment installed successfully from `requirements.lock.txt`; `pip check` found no broken requirements.
- **54 regression tests passed** on the packaged source. This includes project authorization, upload/extraction, review/import, calculation and approval gates, invalidation, benefits, connectors, backup/restore, CPG consolidation, management, citations, configurable hostname redirects and future-dated synthetic quote generation.
- The original installation's 59 tests included six machine-specific lifecycle/desktop portal tests. Those unrelated integrations are excluded here; one portable sample-date regression was added: 59 − 6 + 1 = 54.
- Shell scripts passed Bash syntax checking.
- Isolated real HTTP/worker smoke passed, including source review and verified backup/restore with restored sessions revoked.

## How to reproduce

```bash
bash scripts/setup.sh
bash scripts/check.sh
.venv/bin/python scripts/smoke.py
```

The smoke command creates a temporary database and launches a real HTTP server/worker on a temporary loopback port. It checks bootstrap, protected access, static assets, document subprocess extraction/review and verified backup/restore. It does not read `.env`, contact an ERP or require Ollama, and removes its temporary data after stopping the process.

## Scope and limitations

One upstream Starlette TestClient/httpx deprecation warning is present; it did not fail the tests. Future dependency upgrades should address it after compatibility testing.

The systemd files are deployment templates: the `/opt` service installation, public TLS ingress and unattended reboot behavior must be tested on the destination host. They are not installed on the existing live machine by this packaging task. A template verifier cannot resolve their executable path before deployment.

Local smoke and regression tests do not establish performance capacity, parser sandbox security, model factual accuracy, multi-host reliability, customer acceptance or production readiness. No new penetration test was performed. The original live installation was not changed by these packaging checks.

GitHub-hosted CI has not run. The workflow is provided as an inactive template in `deploy/github-actions-ci.yml`; enabling it requires a maintainer with permission to create workflows. All passing results above were obtained locally from the packaged source.
