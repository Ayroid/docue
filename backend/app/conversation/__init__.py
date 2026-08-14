"""The fill conversation. Plan §10 stages ③-⑥, and only those.

Four narrow call sites between a detected schema and a Change Specification:

    ③ context.py    which regions must we ask about at all?
    ④ planner.py    ≤4 questions, each covering a cluster
    ⑤ extractor.py  one free-form answer → values
    ⑥ deriver.py    a few answers → the rest of the document

Stage ⑦, the change planner, is deliberately not here -- it lives in
`app/planning/` because it is not a model call at all. See its docstring.

Every stage in this package holds to the same four properties, and they are
enforced in code rather than requested in a prompt:

1. **The model may only name `region_id`s it was given.** Every output schema
   pins the ids to an enum; anything outside it is dropped and counted, never
   resolved to "the closest match". Contract C5.
2. **A stage never raises.** Each returns a result object with an `ok` flag and
   a documented deterministic fallback, because a Bedrock outage should cost
   the conversation its polish, not its existence (plan §14: degrade, don't
   die).
3. **Values are never invented.** `null` is a legal answer everywhere, and the
   fail-safe is always the visible gap rather than the plausible guess.
4. **Nothing here writes a byte.** These modules produce values keyed by
   region; the compiler is the only thing that touches a file.
"""
