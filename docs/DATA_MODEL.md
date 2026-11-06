# Data model and calculation semantics

## Main entities

| Entity | Meaning and relationships |
|---|---|
| Users / sessions | Individual identities, global administrator flag, expiring server-side sessions |
| Projects / members | Data scope, synthetic/archive flags, viewer/editor/reviewer memberships |
| Documents / chunks / fields | Original source hash, processing/review state, extracted page/sheet text and proposed/corrected fields |
| Components | Project-unique code, supplier, revision, type, units, attributes, dated price and evidence link |
| Products / BOM | Project-unique finished SKU, forecast, plant/formula and component consumption quantities |
| Catalog versions | Historical snapshots of catalog edits |
| Scenarios / approval snapshots | Baseline/candidate, scoped assumptions, qualifications, versioned approvals and implementation record |
| Programmes | Planning roll-ups of child scenarios and shared transition costs |
| Benefits | Completed non-overlapping actual periods with source evidence |
| Connectors / runs / deliveries | Configuration by secret reference, execution outcomes and idempotent delivery identity |
| Jobs / audit | Durable work queue and actor/action/hash-chain history |

The exact schema and migrations are in `backend/db.py`; request constraints are in `backend/models.py` and `openapi.json`. Do not edit database rows to bypass workflow rules.

## Catalog contract

Import components before products. CSV/JSON source documents must be reviewed. Imports validate all rows before commit; reviewed imports can explicitly upsert existing records and invalidate dependent pending decisions. Price dates are ISO `YYYY-MM-DD`, currency is INR/USD/EUR/GBP/NGN, and source units must already be canonical.

Core component fields: `code`, `name`, `supplier`, `material`, `component_type`, `uom`, `attributes`, `capacity_ml`, `neck`, `weight_g`, `price`, `currency`, `revision`, `price_valid_from`, `price_valid_until`, `state`. `state` is `approved` or `candidate`; this catalog designation is not scenario qualification. API component writes also specify `evidence_id`; imports link to their reviewed source.

Types: bottle, closure, dispensing, label_stock, decoration, carton, pouch, tube, film, pallet, insert. Units: piece, m2, kg, metre. Bottles/tubes require positive capacity; bottle/tube/closure/dispensing require an explicit neck/interface. Other types carry explicit compatibility attributes. For example a closure requires diameter, liner, mechanism, child resistance and contact class. Consult the model schema for the full required attribute matrix.

`weight_g` represents grams per component consumption unit used in the scenario. Keep price, BOM and mass basis consistent, including for fractional material usage. No implicit unit conversion, tax calculation or exchange-rate conversion is performed. Never compare unlike currencies or units.

Products use `sku`, `name`, `annual_units`, `plant`, `formula` and `bom: [{component_code, quantity}]`. API product updates include the current version and entire BOM. CSV supports a single component line; JSON supports multiple lines. Fractional quantities permit allocated cartons, pallets and material consumption; the system does not infer procurement rounding.

## Deterministic calculations

For annual component quantity Q, baseline unit price B, candidate unit price C, additional cost per unit E and one-time transition T:

```text
gross annual estimate = (B - C) × Q
annual extra cost = E × Q
recurring annual net estimate = gross annual estimate - annual extra cost
first-year net estimate = recurring annual net estimate - T
material difference (tonnes) = (baseline grams - candidate grams) × Q / 1,000,000
```

The engine uses Decimal arithmetic and explicit rounding. Financial outputs remain estimates based on entered evidence, forecast and scope. Material mass difference is not a carbon footprint or sustainability certification. Demand comes from affected active SKUs and BOM consumption; review scenario quantity and scope against those records.

Actual period net uses actual units × (counterfactual baseline price − actual paid price), less actual period extra cost and transition cost. Actuals require completed, non-overlapping periods and reviewed evidence. Historical price evidence and counterfactual assumptions still need customer validation.

## Consolidation

Each physical baseline can occur only once in a plan. Mutually exclusive replacements cannot be combined. Finished SKU volumes are deduplicated, component units remain separate, and shared one-time costs are charged once. Child estimates are already rounded; the plan exposes a rounding reconciliation where applicable. Joint physical validation and customer authorization are separate from the arithmetic roll-up.

## Provenance and invalidation

Documents are deduplicated per project by SHA-256; identical uploads reuse a source identity. A source review preserves proposed values and human corrections. Catalog versions, scenario fingerprints, approval snapshots and audit history explain which evidence supported a decision. Relevant edits invalidate pending approvals. Reopening a dependent source also invalidates affected decisions; approving an unrelated receipt does not by itself revoke every approval.
