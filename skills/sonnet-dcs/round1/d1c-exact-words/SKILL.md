---
name: service-spec
description: Use for any task whose prompt is a multi-part spec for a service, API, or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Guides literal reading of the spec and the choices to make where it is silent.
---

# Service from a multi-part spec

## Base rules
- Read every error/condition sentence literally. "Returns X when Y" defines exactly the set Y. Do not widen Y to similar situations, and do not add error branches no sentence licenses.
- When the spec is silent, pick the behavior that keeps earlier parts' worked examples and tests passing unchanged. Earlier behavior is the tie-breaker, not "the more coherent design".
- A guess that changes an earlier part's output is wrong by default. Do not document a guess as the decision; change the guess.

## Exact state words
- A rule applies to the state the spec names and only that state. "Items that are open" means the open state, not "open or reviewed" or "anything not yet closed". Do not merge states into a family for convenience or symmetry.
- Model states as an explicit enum. Every rule that touches state lists the exact members it applies to; a rule written as "not X" is a red flag unless the spec says "not X".
- When a later part introduces a new state, revisit each existing rule and ask whether the spec's sentence names the new state. If it does not, the rule does not apply to it.

## Alias every route spelling
- When a later part writes an existing route differently (trailing slash, singular vs plural, hyphen vs underscore, segment order, casing, a prefix added or dropped), serve every spelling with the same handler. Never replace the old spelling.
- Grep the whole prompt for each path and register each variant seen. Cheap to add, expensive to miss.
- Same for parameter names: if a later part spells a query or body key differently, accept both.

## Field-level inheritance = deep merge
- "Inherits from", "defaults to the current", "unspecified fields carry over" mean a recursive merge at the field level: walk the provided object and the inherited object together; explicit keys win, missing keys fall through, and nested objects recurse. Not whole-top-level-attribute substitution.
- Lists and scalars replace wholesale; only objects recurse, unless the spec says otherwise.
- Write it as one small pure function and hand-test it once with a two-level nested example where the input overrides one leaf and omits another at the same level.

## Verify before finishing a part
Curl each route in every spelling the prompt uses; curl a state-dependent rule with an item in each state and confirm only the named state triggers it; curl an inheritance case with a partial nested body and confirm sibling leaves survive. Then re-run the part's worked examples and compare whole bodies. Throwaway commands only; no test files.
