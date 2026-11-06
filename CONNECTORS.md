# Connector configuration

All connector configurations are administrator-only writes. A configured connector is not evidence that a customer system has been integrated successfully. Inspect the actual run and delivery records.

## File drop

Create a connector with:

```json
{"name":"Supplier specifications","kind":"folder","enabled":true,"interval_seconds":300,"config":{"folder":"supplier-drop"}}
```

The portal displays its exact path, under `<AXIOM_DATA>/inbox/<project-id>/supplier-drop`. Copy source documents there through an approved customer process. Files are deduplicated by hash, extracted asynchronously and require review. The adapter never deletes the originals in the inbox. Symlink files are skipped. Unsupported or oversized files produce a failed run with a count; valid files may already have been accepted.

The web upload is also a working ingestion route. CSV/JSON catalog imports require reviewed source files. A new supplier component code remains a distinct identity.

## HTTPS JSON input

1. Add the exact customer hostname to `AXIOM_CONNECTOR_HOSTS` in the service `.env`. This allowlist is controlled outside the portal. Only explicitly trusted endpoints should be listed.
2. Configure the customer's bearer credential as a named `AXIOM_SECRET_*` variable in `.env`, chmod 600, and restart `packaging-intelligence.service`. Do not put actual secrets in connector JSON, source control, URLs, screenshots or logs.
3. Configure the adapter, for example:

```json
{
  "name":"Customer component feed",
  "kind":"http_json",
  "enabled":true,
  "interval_seconds":300,
  "config":{
    "url":"https://erp.customer.example/api/packaging/components",
    "secret_env":"AXIOM_SECRET_CUSTOMER_ERP",
    "record_type":"components",
    "records_path":"records",
    "mapping":{
      "code":"MaterialCode",
      "name":"Description",
      "supplier":"SupplierName",
      "material":"Resin",
      "capacity_ml":"CapacityMl",
      "neck":"InterfaceCode",
      "weight_g":"WeightGrams",
      "price":"UnitPrice",
      "currency":"Currency",
      "revision":"Revision",
      "state":"Status",
      "price_valid_from":"PriceValidFrom",
      "price_valid_until":"PriceValidUntil"
    }
  }
}
```

The example is a contract template; it is not a real customer endpoint. Source values must already use canonical units and enumerations. `state` is `approved` or `candidate`, currency is INR/USD/EUR/GBP/NGN, and dates are ISO `YYYY-MM-DD`. For different source formats, add an explicit transformation adapter with tests rather than guessing conversions.

With canonical JSON names, use `mapping: {}`. `records_path` selects a dot-separated envelope property such as `records` or OData `value`; omit it for a top-level array. The mapped array is saved as a new source document. Review that JSON, then import it through the catalog action. A successful fetch does not silently change approved catalog records.

Limits: HTTPS only, verified certificates, pinned validated public IP, redirects disabled, no query-string credentials, 5 MB response, 5,000 records. Private/loopback destinations are blocked in the normal runtime. A test-only environment flag permits isolated localhost fixtures; never enable `AXIOM_TEST_HTTP` in a deployed service.

Run failures record safe error messages and use bounded scheduled backoff up to one hour. A manual Run now queues a real attempt. Missing credentials remain a reported failure, never a simulated success.

## Outbound approved changes

```json
{"name":"Customer change receiver","kind":"webhook","enabled":true,"config":{"url":"https://erp.customer.example/api/packaging-changes","secret_env":"AXIOM_SECRET_CUSTOMER_ERP"}}
```

Deliver from a scenario whose approval is current and whose controlled change has been requested. The server sends `axiompack.change.v1` JSON containing the scenario ID/version/fingerprint, baseline and candidate, affected products, financial estimates, qualifications and approver. `Idempotency-Key` is the durable delivery ID and remains stable across retries.

The receiver must persist and honor that key. HTTP 2xx is recorded as delivery acknowledgement only, not as production implementation. There are three automatic attempts, with at least 60 seconds before retry. A failed record can be requeued from the same scenario delivery action. Pausing the connector or invalidating approval blocks subsequent sends.

The final approval check and bounded send are serialized against other database writes on this single host. Network ambiguity can still cause at-least-once delivery; the receiving system's idempotency contract is essential. Approvals cannot roll back an already delivered external change. Customer procedures must handle cancellation or superseding changes after delivery.

## API and machine integration

The current portal uses authenticated, CSRF-protected sessions. HTTPS adapters pull external data and push approved events; there is no unauthenticated ingestion endpoint. Do not use a human password as an external machine integration token. Add a scoped service-account API/OAuth adapter when the customer's integration contract requires inbound push.

## Canonical product JSON

```json
[{"sku":"SH-250-001","name":"Customer shampoo","annual_units":2000000,"plant":"Plant A","formula":"Formula Alpha","bom":[{"component_code":"BOT-104","quantity":1}]}]
```

For CSV, a single BOM line uses `component_code` and `quantity` columns. JSON supports multiple lines. Every component code must exist in the same project. Imports are atomic, revision snapshots are retained, and catalog changes invalidate pending qualifications and approvals.
