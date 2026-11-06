# Troubleshooting

| Symptom | Checks and recovery |
|---|---|
| `python3 -m venv` fails | Install the Ubuntu `python3-venv` package for your interpreter. Use Python 3.10 baseline. |
| Dependency installation fails | Confirm network/index access and Python/platform compatibility. Do not silently unpin versions; retain the error and validate any lockfile change. |
| Port 8015 in use | Stop your other evaluation instance or adjust a separate test invocation, origins and hosts together. Do not kill unrelated services. |
| Browser cannot reach app | Check launcher/service logs and local health; confirm WSL is running. Loopback binding is intentional; use HTTPS ingress for remote clients. |
| Invalid Host header / origin | Match `AXIOM_ALLOWED_HOSTS` and exact `AXIOM_ORIGINS`, restart, then use the intended URL. Do not use wildcard hosts to hide the issue. |
| Login succeeds but session disappears | Check secure-cookie mode and URL. `AXIOM_SECURE_COOKIES=1` requires HTTPS. Clear stale site cookies and log in again after configuration changes. |
| CSRF error | Refresh and sign in again; retain the current session cookie and send the current `X-CSRF-Token` for API writes. |
| Setup token missing | Owner setup may already be complete. Check health. Do not recreate an owner by editing the database; use local account recovery. |
| Too many login attempts | Wait for the 15-minute throttle window; verify the correct account rather than repeatedly retrying. |
| Upload rejected | Check extension, 20 MB cap, PDF header, encryption and Office macro/expanded archive restrictions. |
| Documents remain queued | Check worker is enabled and running; inspect operations/jobs and logs. Use one app process only. |
| Scanned PDF extraction fails | Confirm `pdftoppm`, `tesseract` and English language data are installed, scan quality is adequate, and page/time limits are respected. |
| `No module named resource` | Native Windows is unsupported for the worker; use Ubuntu/WSL2. |
| Import fails | Approve the source first; import components before products; verify mappings, dates, types, units, required attributes and existing component codes. Imports are atomic. |
| AI unavailable | Check Ollama `/api/tags`, installed model name and `OLLAMA_BASE_URL`; portable setup uses 11434, original code fallback is 11435. Restart after edits. |
| AI cites wrong/insufficient facts | Review source passages. Citation ID validation is not factual proof; improve evidence/query and do not approve based solely on model text. |
| Approval blocked | Inspect compatibility/evidence/price dates and all current qualifications. Revisions invalidate prior review; requalify the actual new scope. |
| Stale SKU edit | Reload latest version, reconcile changes and submit the full BOM again. |
| Connector fails | Check external allowlist, secret environment reference, HTTPS certificate, public destination, mapping and response limits. Do not enable the test HTTP bypass. |
| Delivery acknowledged but not implemented | This is expected. Obtain real customer implementation evidence and explicitly acknowledge implementation. |
| Database busy or disk full | Check free space and logs, ensure one process and local storage; do not delete WAL files. Preserve evidence and use verified recovery if needed. |
| Backup fails | Verify destination permissions/capacity and source integrity. An incomplete directory without a manifest is not a valid backup. |

When reporting a bug, include release/commit, OS/Python version, steps, expected/actual behavior and a minimal synthetic example. Redact credentials and personal/customer data. Do not attach `.env`, production databases, unredacted logs or supplier files to public issues.
