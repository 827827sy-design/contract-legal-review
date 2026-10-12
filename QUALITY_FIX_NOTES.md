# General clause-quality and coordinated-edit fixes

Incremental changes keep metadata.version at 2.1. The fixed editor remains offline, and WorkBuddy remains responsible for semantic review. No server or browser DOCX export is required.

New contract-independent plan quality/execution modules require exact target text, confirmed business conditions, source revision baseline, relationship evidence, and a plan/scope-bound ten-item WorkBuddy semantic receipt. Missing conditions, unresolved relations, conflicting actions, stale receipts and unsupported legal scope block application. Formal clauses and explanatory text are separate. Multi-location plans are previewed, applied, confirmed, undone and restored as complete groups. Applied risks remain subject to re-review.

Python validates declared data and receipts; it does not perform legal reasoning, prove the completeness of the model's relationship graph, or authenticate the reviewer using a digital signature. New contract types do not require type-specific production rules. Additional document structures or legal domains require separately verified resources.

Executed tests: 16 general quality tests, 12 existing/Word-export regression tests, 7 native tracked-revision tests, 8 states across six synthetic contract types, 2 final held-out samples, and 39 real Edge browser checks. Browser-confirmed edits exported to test Word were re-extracted and matched independently replayed full text. Semantic receipts are explicit synthetic golden data, not independent model or lawyer evaluations. Word page rendering was not verified.

The final held-out inputs did not cause production code changes. One initial test omitted a required source quote; the validator correctly blocked it, and the fixture was completed without changing production rules. Real user documents and private reports are not included in this repository.

Read [the quality workflow](references/quality_workflow.md), [risk schema](references/risk_schema.md), and [revision schema](references/revisions_schema.md). Old JSON remains readable, but legacy suggestions must be regenerated and verified for application. Already-generated standalone HTML retains its embedded code and must be re-rendered for these protections.
