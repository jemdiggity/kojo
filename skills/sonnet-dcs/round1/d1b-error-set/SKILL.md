---
name: service-spec
description: Use for any task whose prompt is a multi-part spec for a service, API, or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Guides literal reading of the spec and the choices to make where it is silent.
---

# Service from a multi-part spec

## Base rules
- Read every error/condition sentence literally. "Returns X when Y" defines exactly the set Y. Do not widen Y to similar situations, and do not add error branches no sentence licenses.
- When the spec is silent, pick the behavior that keeps earlier parts' worked examples and tests passing unchanged. Earlier behavior is the tie-breaker, not "the more coherent design".
- A guess that changes an earlier part's output is wrong by default. Do not document a guess as the decision; change the guess.

## Conditional fields: omit, never null
- A field that only applies in some situations is left out of the body when it does not apply. Do not emit it as null.
- When a later part adds a field, add it only to the responses the spec shows it in. Responses from earlier parts stay byte-for-byte what their examples show.
- Build response dicts by adding keys under a condition, not by declaring every key up front and filling some with None.
- Serialize with a helper that drops None-valued keys only where the spec is silent; where the spec shows an explicit null, keep it.

## Error-set discipline per endpoint
- Each endpoint emits only the error outcomes the spec lists for that endpoint. Before adding an error branch, find the sentence that licenses it. None found: no branch.
- Helper computations attached to a main operation (diffs, previews, summaries, derived or informational fields) degrade, never surface. If the helper fails, omit or empty that piece and still return the main success outcome. A helper failure never turns a listed success into an unlisted error.
- Preconditions the spec says "always" produce a given outcome are checked first. Order of checks in every handler: path/identity existence -> "always" preconditions -> body/field validation -> business rules. A request that hits an "always" precondition gets that outcome even if the body is malformed.
- Per-endpoint checks decide, not shared middleware. A global validation layer must not emit an error for an endpoint whose section does not list it.
- Do not add "defensive" conflict or state-guard errors the spec does not name. Silence about a state means proceed, not reject.

## Verify before finishing a part
For each new endpoint, list the error outcomes its section names and grep your handler for every raise/return of an error: each must map to one listed outcome. Then curl the part's worked examples and compare whole bodies, checking for any key that is present-as-null. Throwaway commands only; no test files.
