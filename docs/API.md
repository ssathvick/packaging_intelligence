# API reference

The checked-in [OpenAPI schema](../openapi.json) is generated from `backend.main.app.openapi()` and documents request/response models. Interactive `/docs`, `/redoc` and live `/openapi.json` endpoints are deliberately disabled. API version is reported in `/api/health`.

## Authentication and CSRF

The API uses individual human accounts and server-side cookie sessions. `/api/auth/setup` creates the initial owner using a local one-time token. `/api/auth/login` sets the `axiom_session` HttpOnly, SameSite=Strict cookie and returns a CSRF token. Obtain current user/CSRF with `/api/auth/me`. Send `X-CSRF-Token` with authenticated state-changing API requests and retain the session cookie. Browser origins and hostnames must match configured allowlists.

Do not embed passwords in frontend source or automation scripts. There is no general service-account/OAuth ingestion API in this release. Use configured HTTPS/file-drop/webhook adapters, or implement a scoped machine identity adapter for an approved integration contract.

## Route groups

| Prefix / endpoint | Purpose |
|---|---|
| `GET /api/health` | Database/worker/bootstrap health; no model/ERP readiness guarantee |
| `/api/auth/*` | Setup, login, logout, current session, password change |
| `/api/users` | Administrator account management; individual disable route revokes access |
| `/api/projects` | Create/list projects; rename, archive and manage memberships |
| `/api/projects/{pid}/overview` | Project summary |
| `/api/projects/{pid}/documents` | Upload/list; per-source details, file, review, reopen and retry |
| `/api/projects/{pid}/catalog` | Catalog retrieval and reviewed CSV/JSON import |
| `/api/projects/{pid}/components` | Component writes and revision history |
| `/api/projects/{pid}/products` | Finished SKU/BOM create/update/archive/history |
| `/api/projects/{pid}/search` | Project evidence search |
| `/api/projects/{pid}/ask` | Read-only model answer over retrieved approved evidence |
| `/api/projects/{pid}/opportunities` | Candidate screening |
| `/api/projects/{pid}/scenarios` | Scenario create/update/detail; qualification, approval, request-change, implement, export, benefits and deliver |
| `/api/projects/{pid}/programmes` | Consolidation plans |
| `/api/projects/{pid}/connectors` | Administrator connector configuration/run |
| `/api/projects/{pid}/operations` | Jobs, runs and delivery outcomes |
| `/api/projects/{pid}/audit` | Audit records and chain verification |
| `/api/system` | Authenticated runtime/model information |
| `/api/sample-project` | Explicit synthetic project generation |

Consult `openapi.json` for exact methods, required fields and request schemas; not every route in a group permits every method. Project authorization applies to sources and records, not only project lists.

## Common responses

`401`: no valid session. `403`: CSRF, origin or role failure. `404`: missing/inaccessible project or record. `409`: conflicting identity, stale state/version or workflow gate. `413`: size cap exceeded. `422`: invalid data or unsupported input. `429`: login or model concurrency limit where applicable. `503`: database operation/model availability problem. Inspect the response `detail`; do not blindly retry mutations that may already have completed.

Document upload is multipart with field `file`. Review is JSON with a `fields` mapping keyed by extracted field IDs and a meaningful `note`. Catalog import specifies `document_id`, `record_type` (`components` or `products`) and `mapping`. Scenario approval requires current evidence-backed qualifications; calling the endpoint cannot bypass those checks.

## Regenerate the contract

From the checkout with its virtual environment available:

```bash
.venv/bin/python -c 'import json; from pathlib import Path; from backend.main import app; Path("openapi.json").write_text(json.dumps(app.openapi(), indent=2)+"\n")'
```

Importing the app does not start the lifespan or worker. Review schema changes alongside code/tests. Avoid adding examples containing real credentials or customer documents.
