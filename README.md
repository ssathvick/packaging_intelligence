# Packaging Intelligence

Packaging Intelligence (AxiomPack in the application interface) turns supplier packaging documents into reviewed evidence, component catalogs, cost comparisons and controlled change decisions. It combines a deterministic calculation engine with optional local AI answers through Ollama.

**Status: single-host release candidate, suitable for evaluation and controlled pilots.** It is not certified packaging engineering software, an ERP, or an automatic regulatory approval system. Read the [production acceptance checklist](docs/PRODUCTION_READINESS.md) before using customer data.

## What you can do

- Upload PDF, TXT, CSV, JSON, DOCX and XLSX supplier documents; extract text and English OCR; review proposed fields against original sources.
- Manage suppliers, component revisions, dated prices, finished SKUs and multi-line bills of materials.
- Compare bottles, closures, dispensing assemblies, labels, decoration, cartons, pouches, tubes, films, pallets and inserts using explicit compatibility attributes.
- Ask questions over approved evidence with source references using a local Ollama model.
- Calculate annual gross estimates, recurring costs, first-year net estimates and material mass differences.
- Record evidence-backed qualifications, approve versioned decisions, request controlled changes and acknowledge implementation separately.
- Combine compatible decisions into consolidation plans without double-counting shared baselines or SKUs.
- Record actual benefit periods separately from forecasts, import from file/HTTPS connectors, and deliver approved change events to webhooks.
- Manage project access, archive projects and products, inspect audit history, and back up/restore the data.

## Start on Ubuntu or Windows with WSL2

Python 3.10 is the validated baseline. Use Ubuntu 22.04 or a compatible Linux environment with Python 3.10+. Native Windows is not supported because the document worker uses POSIX resource limits; use WSL2. Other Python/platform combinations require testing.

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv poppler-utils tesseract-ocr tesseract-ocr-eng
git clone https://github.com/ssathvick/packaging_intelligence.git
cd packaging_intelligence
bash scripts/setup.sh
bash scripts/run.sh
```

Open **http://localhost:8015**. In a second terminal, from this repository, read `cat data/setup-token` and use that one-time token to create your owner account. There is no default password. Keep the server terminal open; Ctrl+C stops it.

The application works without a model for document review, catalogs, calculations and approvals. For AI answers, install [Ollama](https://docs.ollama.com/linux), start it locally, then run `ollama pull qwen3.5:9b`. The portable configuration uses Ollama on port **11434**. Model weights and licenses are separate from this repository. See [installation](docs/INSTALLATION.md) for model configuration, hardware planning, WSL and service installation.

## Documentation

| Guide | Contents |
|---|---|
| [Installation](docs/INSTALLATION.md) | Linux/WSL setup, prerequisites, local AI, first login, verification |
| [Configuration](docs/CONFIGURATION.md) | All runtime variables, local versus HTTPS settings, limits |
| [User walkthrough](docs/USER_GUIDE.md) | Upload through review, analysis, qualification, approval and implementation |
| [Architecture](docs/ARCHITECTURE.md) | Modules, data flow, database, worker, trust boundaries |
| [Data and calculations](docs/DATA_MODEL.md) | Catalog fields, units, revisions, financial formulas, plan semantics |
| [API](docs/API.md) | Session/CSRF model, endpoint groups, generated OpenAPI schema |
| [Connectors](CONNECTORS.md) | File drop, HTTPS imports, mappings, webhook delivery and idempotency |
| [Deployment and operations](docs/OPERATIONS.md) | Dedicated service, HTTPS, backup, restore, updates and recovery |
| [Security](SECURITY.md) | Controls, threat boundaries, reporting and deployment responsibilities |
| [Production readiness](docs/PRODUCTION_READINESS.md) | Required acceptance evidence and known gaps |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Startup, extraction, authentication, AI and approval failures |
| [Development](CONTRIBUTING.md) | Tests, isolated data, schema changes and contribution process |
| [Release notes](CHANGELOG.md) | Portable distribution changes and original capabilities |

## Verify your installation

```bash
curl --fail http://localhost:8015/api/health
bash scripts/check.sh
```

Tests use temporary synthetic databases. They do not require Ollama and do not certify model quality, production capacity or customer integration. See [verification notes](docs/VERIFICATION.md) for the checks performed on this release.

## Repository layout

```text
backend/       FastAPI application, rules, database, extraction, local AI, jobs
web/           Browser interface (plain JavaScript and CSS; no Node build step)
ops/           Portable backup/restore and local account-recovery commands
scripts/       Local setup, launch and test helpers
deploy/        Linux systemd application and backup templates
tests/         Isolated synthetic regression tests
docs/          Installation, product, API and operations documentation
openapi.json   Generated API contract; no customer data
```

This repository contains application source and generated synthetic training examples. It excludes live databases, uploaded customer files, `.env`, credentials, model weights, personal voice samples, recordings and private host/tunnel configuration. Unrelated desktop portal controllers from the original machine are not part of this portable application.

## License

[MIT](LICENSE). Dependencies and model weights retain their own licenses. Product and organization names do not imply certification or endorsement.
