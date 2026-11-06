# User guide: supplier documents to approved change

## Roles and workspace

The administrator manages accounts, memberships and connectors and can access all projects. A viewer reads project information, an editor changes working data, and a reviewer can review evidence and record approvals. Reviewer status does not enforce a separate person from the author; agree responsibilities before live use.

Use Projects & demos to create/open projects. Mark generated exercises synthetic. Renaming preserves identity. Archiving a project retains its data/history, makes it read-only, pauses connectors and cancels queued work; restoring does not automatically resume those activities. Product archives retain BOM/history and exclude products from active demand.

The left navigation separates the project workspace, documents/review, SKU and component catalog, evidence answers, opportunities/scenarios, consolidation plans, integrations/operations and audit/settings. The displayed labels may evolve; the following sequence describes the underlying workflow.

## 1. Create a practice project

Choose **Create new synthetic demo**, enter a distinct name and acknowledge creation of a separate project. To continue an earlier exercise, open the existing project instead. The built-in example generates eight sources, three bottle components and twenty finished SKUs once imported. All suppliers, prices, trials and receipts in this example are fiction.

Fresh demo sources use price validity from their creation date through the following 60 days. Already-created projects do not silently renew prices. Expired quotes must be replaced with explicitly reviewed commercial evidence. Historical benefit examples remain labelled fictional.

## 2. Upload and review documents

In Documents & review, upload supported files or wait for the built-in sources to finish processing. Status progresses from queued/processing to review, or failed with a reason. For failures, fix the source or installation issue and retry.

Open the original file alongside extracted text and proposed fields. Verify specification identifiers, revision, units, currency, dates, supplier and compatibility facts. Correct extracted values where needed, record a meaningful review note and approve the source. Historical R4 is superseded by R6; approving the historical document as evidence does not make its specification current.

Document approval means the source has been reviewed. It does not import the catalog, qualify the component, approve a cost decision or implement a production change. Instructions written inside supplier documents are source content, not authority to change system behavior or approve anything.

## 3. Import and check the catalog

In SKU & components, select the reviewed `01-components.csv`, import type `components`, mapping `{}`. Then import reviewed `02-products.csv` as `products`. All rows validate before the transaction commits. Importing products first fails if their component codes do not exist.

Check component revisions, state, dated prices and source links. Inspect each finished SKU's forecast, plant, formula and BOM quantity. Multi-line JSON BOMs support multiple components; the BOM is a flattened consumption list, not a recursive assembly tree. Components are distinct by code, even if their names are similar. Review compatibility attributes before proposing a shared replacement.

Use Edit SKU & BOM to save the entire BOM together. A stale-version response means someone else changed the record: reload and reconcile. Business edits and archive/restore can invalidate pending qualifications/approvals.

## 4. Review evidence answers and opportunities

If Ollama is configured, ask: “What is the current weight of BOT-104 R6 compared with historical R4?” Inspect citations: R6 is 18 g and R4 is 19 g in the synthetic sources. A valid citation identifier does not prove the answer's interpretation. The model has no write or approval tools.

Opportunity discovery screens catalog/BOM data for candidate comparisons. A suggested opportunity is a starting point; verify exact SKU, plant, formula, price basis and demand scope before saving a scenario.

## 5. Build a deterministic scenario

For the built-in example use BOT-104 R6 as baseline and BOT-209 C2 as candidate:

| Input | Synthetic value |
|---|---:|
| Annual component units | 8,000,000 |
| Baseline price | INR 5.20 |
| Candidate price | INR 4.90 |
| Extra operating cost per unit | INR 0.02 |
| One-time transition cost | INR 400,000 |
| Baseline/candidate mass | 18 g / 16 g |

Record scope: SH-250-001/002/003, Plant A, Formula Alpha, current reviewed commercial period, same delivery basis and tax treatment. Results should be INR 2,400,000 gross annual estimate, INR 1,840,000 first-year net, INR 2,240,000 recurring annual net and 16 tonnes material difference. These are estimates, not actual savings or carbon claims.

Review every eligibility blocker. Incompatible interfaces, types, units, currency, evidence or expired prices cannot be resolved by writing an optimistic assumption note.

## 6. Qualify and approve

Attempting approval before qualification should fail. Record all required fit/seal, line trial and formula compatibility qualifications against reviewed evidence and the exact current scenario. For practice use `06-synthetic-trial-evidence.txt`; for live work use real test reports reviewed by qualified personnel.

Once eligibility and current qualifications are complete, a reviewer approves with a note. The engine stores a frozen approval snapshot and a fingerprint of relevant inputs. Changing the relevant catalog/scenario or reopening supporting evidence invalidates pending approval/qualification. Re-review and requalify rather than bypassing the gate.

## 7. Request and acknowledge implementation

Request a controlled change from the current approved decision. Export its JSON evidence pack, or deliver it through an administrator-configured webhook. HTTP delivery success acknowledges receipt only.

After the customer's change is actually implemented, record the reviewed implementation receipt and external change reference. In the synthetic demo use `07-synthetic-implementation-receipt.txt` and a clearly fictional reference. The app does not execute an SAP/PLM transaction by itself. Implemented decisions retain their historical approval financials, with current reevaluation shown separately.

## 8. Record actual benefit evidence

Use completed, non-overlapping periods and reviewed supporting evidence. Enter actual units, counterfactual baseline price, actual price, extra costs and transition costs attributable to that period. The supplied fictional actuals example yields INR 2,800 for 10,000 units. This is independent of the forecast estimate and is not evidence of real commercial savings.

## 9. Consolidation plans

A consolidation plan groups compatible child decisions, deduplicates finished SKUs/volume, prevents overlapping physical baselines and counts shared transition cost once. Keep different component units separate. Review all child approval/qualification states and any conflicts.

`approved_planning` means the roll-up's child planning decisions meet its rules. It is not a separate programme authorization, evidence of combined physical validation, or proof of ERP implementation. Do not add a family plan to a portfolio that already contains its children.

## 10. Audit and handover

Review the audit history, source hashes, versioned snapshots and operations failures. Export evidence for the customer's review procedure. A verified local hash chain detects alteration but cannot provide administrator-proof immutable storage. Finish by recording ownership, open issues, follow-up validation and the distinction between forecast, approved decision, delivered change, implemented change and actual benefit.
