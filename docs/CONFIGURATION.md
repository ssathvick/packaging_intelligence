# Configuration reference

`scripts/run.sh` changes to the repository root and exports values from `.env`. Direct `uvicorn`, backup and management commands do **not** load `.env` automatically. Source it explicitly as shown in operations, or use the systemd `EnvironmentFile`. Environment values are read at process import/start; restart after changes.

| Variable | Portable example/default | Purpose |
|---|---|---|
| `AXIOM_DATA` | `data` (relative to repository root) | SQLite, uploads, inbox and runtime files; use an absolute path for services |
| `AXIOM_ORIGINS` | `http://localhost:8015,http://127.0.0.1:8015` | Exact allowed browser origins including scheme and port; comma-separated, no spaces |
| `AXIOM_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Allowed HTTP hostnames, no scheme or port; do not use `*` for public deployment |
| `AXIOM_SECURE_COOKIES` | `0` | Set `1` for HTTPS; enables secure cookies and HSTS |
| `AXIOM_PUBLIC_URL` | empty | Canonical HTTPS base URL; when set, redirects `www.<canonical-host>` to it |
| `AXIOM_WORKER` | `1` | Start embedded durable job worker; `0` only for tests/special isolated tools |
| `AXIOM_CONNECTOR_HOSTS` | empty | Exact allowed external connector DNS hostnames |
| `AXIOM_SECRET_*` | unset | Locally configured bearer secrets referenced by connector config |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Server-side Ollama endpoint; code fallback without `.env` remains original dedicated port 11435 |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Installed Ollama model identifier |
| `OLLAMA_NUM_CTX` | `8192` | Requested model context tokens |
| `OLLAMA_NUM_PREDICT` | `2048` | Requested maximum generated tokens |
| `AXIOM_TEST_HTTP` | unset / `0` | Test-only localhost connector exception; never set `1` in deployment |

Example public configuration (replace the example hostname, terminate TLS at a reverse proxy or tunnel):

```dotenv
AXIOM_DATA=/var/lib/packaging-intelligence
AXIOM_ORIGINS=https://packaging.example
AXIOM_ALLOWED_HOSTS=packaging.example,www.packaging.example,localhost,127.0.0.1
AXIOM_SECURE_COOKIES=1
AXIOM_PUBLIC_URL=https://packaging.example
AXIOM_WORKER=1
AXIOM_CONNECTOR_HOSTS=erp.customer.example
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:9b
OLLAMA_NUM_CTX=8192
OLLAMA_NUM_PREDICT=2048
```

Protect `.env` with mode 600 or equivalent restricted access. Do not commit it, place secrets in URLs, or expose Ollama/Uvicorn directly to the Internet. Only configure remote Ollama endpoints you trust with approved evidence excerpts.

## Fixed limits and design constraints

- One Uvicorn process and one embedded worker. Do not increase workers or run a second app instance on the same database.
- Upload: 20 MB; accepted extensions PDF/TXT/CSV/JSON/DOCX/XLSX. PDFs: at most 50 pages. Extracted text: two million characters.
- Office archives: at most 5,000 ZIP entries and 100 MB expanded; macro-enabled content is rejected. XLSX extraction: 20,000 rows, first 100 columns.
- Document subprocess: 2 GB address-space limit, 300 seconds CPU, 360 seconds wall time; individual OCR operations also have timeouts.
- Imports: 5,000 records. HTTPS connector response: 5 MB, no redirects, allowed public destinations only.
- Sessions expire after eight hours. Login throttling operates per observed client-IP/email pair; the loopback proxy means it is not a complete edge rate limiter.
- English OCR and lexical FTS search. No embedding/vector index, recursive BOM explosion or automatic unit conversion.

These are implementation limits, not throughput guarantees. Changing them requires testing and operational review.
