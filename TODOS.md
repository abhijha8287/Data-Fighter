# TODOs

Captured during `/plan-eng-review` of the Data Firefighter design doc
(2026-08-08). All three items below were deliberately cut from the
hackathon build (Approach A, ~2-day deadline) — see
`~/.gstack/projects/DataFighter/abhishek-unknown-design-20260808-094448.md`
for the full design context.

## 1. Postgres persistence + full incident history

**What:** Durable, queryable incident history across restarts and multiple
concurrent incidents, replacing the hackathon build's SqliteSaver-only
checkpoint persistence.

**Why:** SqliteSaver covers LangGraph's graph-resume state for one demo
run, which is sufficient for the hackathon submission. A real deployment
needs incident history, reporting, and multi-tenant durability that a
checkpointer alone doesn't provide.

**Pros:** Unlocks the original brief's P1 roadmap — audit trail, historical
trend analysis, "has this dataset had incidents before" queries.

**Cons:** Real setup cost (SQLAlchemy models, migrations, connection
pooling) that isn't needed for the hackathon submission itself.

**Context:** The original 30-section brief specified Postgres via
SQLAlchemy from the start; it was cut during `/plan-eng-review` Step 0
(scope challenge) as accidental complexity for a single-demo-run build.
Start from the original brief's `models/` sketch when picking this up.

**Depends on / blocked by:** Nothing — can be added independently once the
hackathon submission ships.

## 2. Implement the 3 non-primary incident types

**What:** Wire "Column Renamed," "Type Changed," and "Freshness Breach" to
real logic (their own `detect_incident`/`generate_fix` behavior) using the
same 11-node LangGraph pattern already built for column deletion, instead
of leaving them as disabled UI selectors.

**Why:** The hackathon build intentionally scoped to one incident type
end-to-end rather than four shallow ones. Real-world data incident response
needs all four categories from the original brief.

**Pros:** Matches the full original vision; likely improves "real-world
applicability" scoring if there's time to extend post-hackathon.

**Cons:** Each type needs its own root-cause reasoning and fix-generation
logic — this is real build time, not a config flag.

**Context:** The graph shape (`detect_incident → fetch_context → ... →
write_back_to_datahub`) is type-agnostic; only `detect_incident` (parsing
the incident signal) and `generate_fix` (the remediation logic) are
type-specific. Start there.

**Depends on / blocked by:** Nothing — independent of the Postgres work.

## 3. Replacement-column detection in generate_fix

**What:** Detect when a deleted column has a semantic replacement (schema
diff + type match + name-similarity filter, LLM tiebreak on ambiguous
candidates) and propose a rename/remap fix instead of straight removal.

**Why:** The hackathon's golden demo scenario (`customer_email` deleted, no
replacement) never exercises this branch, so it was cut rather than shipped
untested. Real column deletions often DO have a replacement column — the
removal-only path is a real gap outside the demo's narrow scenario.

**Pros:** Much more useful for actual incident response, not just the demo
— "restore/rename" is one of the four remediation decisions the original
brief called out as required agent judgment.

**Cons:** Needs a second golden fixture scenario (a deletion WITH a
plausible replacement column) to validate the branch before it can be
trusted — real design + test work, not just re-adding the old code.

**Context:** A full sketch of this logic (exact-type-match AND
Levenshtein-distance-≤2-or-substring filter, LLM tiebreak on multiple
candidates) existed in an earlier revision of the design doc and was
removed during `/plan-eng-review`'s outside-voice pass specifically because
it was unvalidated by the chosen demo scenario — the logic itself wasn't
judged wrong, just untested. Re-derive from that reasoning rather than
starting from scratch.

**Depends on / blocked by:** Should ship alongside item #2 (the other
incident types will need similar "detect what changed and whether it's
recoverable" logic).
