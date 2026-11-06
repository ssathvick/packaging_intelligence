# Installation

## Supported path and prerequisites

The validated runtime is Ubuntu 22.04 with Python 3.10. Windows users should run the Linux instructions inside WSL2. The document worker imports Python's POSIX `resource` module, so native Windows Python is not supported. macOS and other Linux/Python versions have not been validated by this release.

Required: Git, Python with venv/pip, SQLite with FTS5 (provided by the Ubuntu Python build), Poppler (`pdftoppm`), Tesseract with English language data, a modern browser and writable local storage. There is no Node/npm build step.

For a small evaluation, budget approximately 4 GB RAM for the application and OCR workload, plus OS overhead and space for uploads and backups. This is a starting allocation, not a measured capacity guarantee. Optional local AI needs additional RAM/VRAM and model storage; requirements depend on model, quantization and context. CPU inference is possible but may be slow. Validate latency with representative questions before choosing hardware.

## Windows with WSL2

Install Ubuntu using the current [Microsoft WSL instructions](https://learn.microsoft.com/windows/wsl/install), finish its initial user setup, and open an Ubuntu terminal. Clone into the Linux filesystem (for example `~/projects`) rather than a Windows-mounted folder for normal operation. Run all remaining shell commands in Ubuntu, not PowerShell. Browse to `http://localhost:8015` from Windows after starting the app. Sleep, shutdown or stopping WSL makes the application unavailable; use a dedicated Linux host for unattended service needs.

## Linux local evaluation

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv poppler-utils tesseract-ocr tesseract-ocr-eng
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/ssathvick/packaging_intelligence.git
cd packaging_intelligence
bash scripts/setup.sh
```

The setup script creates `.venv`, installs the pinned dependency lock, creates `.env` only if absent, and checks dependency compatibility. It does not install OS packages or Ollama, change system services, or configure a public domain. `.env` is a trusted Bash-compatible configuration file; use simple `NAME=value` entries, quote spaces, and never copy shell code from an untrusted source into it.

Start:

```bash
bash scripts/run.sh
```

In a second terminal, from the same repository:

```bash
curl --fail http://localhost:8015/api/health
cat data/setup-token
```

Visit `http://localhost:8015`. Enter the one-time setup token, your name, email and a password of at least 12 characters. The first account is the administrator. The token is deleted after setup. There is no supplied password and no automatic email verification or email password reset. Keep the token private.

Use a separate account per person. Create users and project memberships through the interface; choose viewer, editor or reviewer according to responsibility. Do not share the owner login. The server binds only to loopback; another machine cannot connect directly. Use the HTTPS deployment instructions for remote access.

## Optional Ollama configuration

Follow the official [Ollama Linux installation guide](https://docs.ollama.com/linux) for installation and GPU setup. Keep its HTTP API bound to loopback. The application does not download models automatically.

Once Ollama is running locally:

```bash
ollama pull qwen3.5:9b
ollama list
curl --fail http://127.0.0.1:11434/api/tags
```

The `.env.example` uses `OLLAMA_BASE_URL=http://127.0.0.1:11434`. If you already use a dedicated Ollama instance on a different port, set that URL in `.env`. Run Ollama inside the same WSL/Linux environment for the simplest networking. Service configuration is described in the [Ollama FAQ](https://docs.ollama.com/faq).

`OLLAMA_MODEL` must match an installed model name. The original workflow used `qwen3.5:9b`; alternative models must support the requested JSON response format and should be evaluated against citation tests and representative evidence. Restart AxiomPack after changing `.env`. Check model status in Settings, then ask a question after approving relevant source documents. Model availability is not included in `/api/health`.

Without Ollama you can still upload, review, import, compare, qualify and approve. AI question answering will report a model/connection error; it is not required for deterministic calculations.

## First acceptance check

1. Confirm health returns `status: ok`, `worker: true` and `setup_required: false` after owner creation.
2. Run `bash scripts/check.sh`; tests use isolated synthetic data and do not require a model.
3. Create a synthetic project and complete the [walkthrough](USER_GUIDE.md).
4. Verify an uploaded document reaches review, open its original and extracted text, and verify source-linked fields.
5. Create and verify a backup; restore it into a separate empty directory following [operations](OPERATIONS.md).
6. If using AI, verify a cited answer against the actual source, not just the presence of a citation.

For persistent Linux service deployment, follow [operations](OPERATIONS.md). Do not run the foreground launcher and systemd service against the same database simultaneously.

## Updates and removal

Stop the app, verify a backup, select a reviewed release/commit, install its lockfile, run tests and restart. Preserve `.env` and `data/`. Schema rollback can require a matching database backup. To stop a local evaluation, press Ctrl+C. Removing the source checkout alone does not uninstall Ollama or systemd units; retain or securely dispose of data and credentials according to your policy.
