---
name: service-spec
description: Invoke before reading any code, for any task whose prompt is a multi-part spec for a service, API or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Apply its rules while reading the spec literally and while choosing behavior where the spec is silent.
---

# Service from a multi-part spec

## Invariant
- For an identity that exists, every "current value" read succeeds. Not-found means the identity is missing and nothing else; a list read for a missing identity is still not-found, not an empty success.
- Numbering starts at 1, so "nothing yet" is the integer 0, emitted by reads and accepted by writes.

## Base rules
- Read every error/condition sentence literally. "Returns X when Y" defines exactly the set Y. Do not widen Y to similar situations, and do not add error branches no sentence licenses.
- An outcome the spec says "always" happens under a condition is checked before field validation of the request body.
- When the spec is silent, pick the behavior that keeps earlier parts' worked examples and tests passing unchanged. Earlier behavior is the tie-breaker, not "the more coherent design".
- A guess that changes an earlier part's output is wrong by default. Do not document a guess as the decision; change the guess.
- Literal for error conditions, liberal for what to accept. Accept liberally where the spec gives no rejection example. If a rule says a thing "must expose A and B" and no example shows a rejection for having only one, treat it as A and/or B. Reject only inputs the spec explicitly shows being rejected; silence means accept and proceed.

## Empty-state walk-through (do this before coding each part)
Trace the first use of every new workflow from an empty store, in three steps: (a) identity does not exist; (b) identity exists but the thing being read has not been set yet; (c) after the first write/transition. Do this for each read a new write depends on, including reads defined in earlier parts. Decide what each read returns at each step before writing handlers.
- A read of current state returns not-found only for the exact condition the spec names, normally "the identity itself does not exist".
- When the identity exists but the value has not been set yet, respond with success and an explicit, typed, empty representation of "nothing yet". This is a normal state, not an error. Do not reuse the not-found path for it.
- A not-found in state (b) is a bug in the read: fix the read, do not document it.
- A create/transition path that "starts from the current value" must work on step (b): the current value is the typed empty sentinel, and the operation proceeds from it.

## Type-stable sentinels
- A field the spec documents as an integer is an integer in every response and every accepted input, including the "none yet" case. If numbering starts at 1, the pre-first value is 0. Never null, never absent, never a string.
- Same rule for every type: lists are empty lists, not null; booleans are true/false, not null.
- If you are about to write null for a numeric field, stop and use the integer below the first real value.
- Inputs accept the same sentinel the reads emit, so a client can echo a read straight back into a write. Treat the sentinel in a request exactly as "start from nothing".
- Keep sentinel handling in one helper (e.g. `current_or_zero(...)`) so every endpoint agrees.

## Field-level inheritance = deep merge
- "Inherits from", "defaults to the current", "unspecified fields carry over" mean a recursive merge at the field level: walk the provided object and the inherited object together; explicit keys win, missing keys fall through, and nested objects recurse. Not whole-top-level-attribute substitution.
- Lists and scalars replace wholesale; only objects recurse, unless the spec says otherwise.
- Write it as one small pure function and hand-test it once with a two-level nested example where the input overrides one leaf and omits another at the same level.

## Verify before finishing a part
Curl each read a new write depends on, including reads defined in earlier parts, in the three states (unknown identity; known identity with nothing set; after first write): only state (a) is not-found, state (b) is a success body, every numeric field is a JSON number. A not-found in state (b) is a bug: fix the read and re-curl. Throwaway commands only; no test files, no notes files. Then state in your summary what the current-value read returns for an identity that exists with nothing set yet.
