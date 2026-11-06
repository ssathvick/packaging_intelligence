# Security policy and boundaries

## Reporting

Do not put credentials, customer documents or exploit details into public issues. Use GitHub's private vulnerability reporting if enabled on this repository; otherwise contact the repository owner privately through a channel you already trust. There is no promised response-time SLA. If a credential is exposed, revoke/rotate it and review access; deleting a Git commit is not sufficient.

## Implemented controls

- One-time owner bootstrap; no default password. PBKDF2 password hashes, expiring server-side sessions, session revocation and login throttling.
- HttpOnly/SameSite cookies; secure-cookie/HSTS mode for HTTPS; CSRF tokens and exact origin checks; trusted host validation and restrictive browser headers.
- Per-project viewer/editor/reviewer access and administrator-only management operations.
- Upload extension/header/size checks, Office expansion/macro restrictions, UUID source names, hashes and parser subprocess resource limits.
- Allowlisted HTTPS connectors, validated public destinations, TLS verification, no redirects, bounded responses and secret references rather than inline credentials.
- Reviewed-source retrieval, validated citation identifiers and an LLM with no write/approval tools.
- Versioned approvals, invalidation, durable delivery identities, audit hash chain and verified backup/restore.

## Important limits

Resource limits are not a malware scanner or parser security sandbox. Local audit hashing is not immutable storage against a database administrator. Administrators have cross-project access. A reviewer can also be an author; independent approver separation is not enforced. SSO/MFA, immutable external audit export and a general machine identity/OAuth API are not included.

SQLite/files are not encrypted by the application. Protect the host, disks, backups, environment and model endpoint. The system is a single-host release candidate, not a tenant-isolated SaaS platform. Model outputs can be wrong even with valid citations. Human reviewers remain responsible for engineering and business decisions.

## Public deployment responsibilities

Complete independent security review, update dependencies and OS parsers, terminate HTTPS correctly, restrict network ingress, configure monitoring/rate limits, agree data retention and verify offsite recovery. Never enable `AXIOM_TEST_HTTP=1` outside isolated tests. Never publish `.env`, database files, source uploads, setup tokens, connector credentials, personal voice samples or recordings.

The regression suite covers selected security behavior; it is not a penetration test. See [production readiness](docs/PRODUCTION_READINESS.md) for acceptance gates.
