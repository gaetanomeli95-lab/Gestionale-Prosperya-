# AI Architecture

## Core principle

**Deterministic core first. AI assistance second.** The CRM works fully with
the AI layer disabled. AI never makes authoritative business decisions
(eligibility, fiscal states, deadlines).

## Abstraction

```
domain modules → AiService interface → provider adapters (feature-flagged)
```

- Every AI capability behind a named feature flag (`AI_FEATURES_ENABLED`, per-feature flags later).
- Provider-agnostic: pluggable backends (local model, external API) configured per deployment.
- The interface returns *proposals with provenance*, not mutations.

## Human-in-the-loop (mandatory)

```
Document → AI extraction → proposed fields + confidence + source refs
         → user review → apply
```

Never: `Document → AI → database overwritten`. AI suggestions carry the
source excerpt/document they were derived from wherever possible.

## Candidate use cases (priority order)

1. Customer/practice summary from the activity timeline.
2. Document field extraction with review (e.g. visura, bando PDF).
3. Missing-data assistant (works with the warnings engine).
4. Semantic search over authorised CRM data.
5. Funding-programme analysis with cited sources.
6. Likely-duplicate suggestion (feeds the dedupe review, never auto-merges).

## Privacy rules

- No customer/confidential data to external providers without an explicitly
  approved deployment configuration and legal/privacy arrangements.
- Default: safe. An unset provider means AI features are off.
- AI outputs are logged with provenance; confidential document contents are
  not logged.
- Eligibility and scoring engines remain deterministic and explainable —
  AI may draft inputs, humans confirm.
