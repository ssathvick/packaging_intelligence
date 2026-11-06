# Production acceptance checklist

This distribution is a **single-host release candidate**. Successful tests and a synthetic walkthrough demonstrate implemented behavior, not production certification. A customer/operator should record evidence and an accountable owner for each applicable gate before live use.

| Gate | Required evidence |
|---|---|
| Business acceptance | Customer UAT on representative documents, types, units, prices, workflows and exception cases |
| Engineering responsibility | Approved qualification rules and real reviewed test evidence; correct SKU/plant/formula scope |
| Identity and access | Individual accounts, tested project access matrix, joiner/leaver process; SSO/MFA and approver separation if required |
| Security | Independent assessment including uploads/parsers, connectors, sessions, access and external ingress |
| Capacity | Representative concurrent users, document volumes, OCR latency, queue backlog and model latency tests |
| Availability | Dedicated operational host, unattended restart, monitored dependency health and agreed service/recovery targets |
| Recovery | Encrypted offsite backups, retention/capacity policy, protected configuration secrets and timed restore drill |
| Audit and privacy | Agreed retention/deletion, privileged-access controls and external immutable audit storage if required |
| Integration | Real customer API contract/mappings/authentication, receiver idempotency and end-to-end reconciliation |
| Release control | Reviewed immutable commit/tag, reproducible environment, CI results, migration rehearsal and rollback plan |
| Operational ownership | Alert recipients, incident runbook, maintenance windows and support responsibilities |

Known architectural gaps: no high availability, no multi-host queue/database design, no built-in SSO/MFA, no independent approver enforcement, no administrator-proof audit store, no malware scanner and no bundled offsite/retention/alerting service. Generic HTTP adapters are not vendor-certified SAP/PLM integrations.

Start with synthetic data. Move to a limited live pilot only after the relevant data-security and operational gates are accepted. Do not describe planning approval, webhook delivery, or fictional implementation receipts as actual production implementation or realised savings.
