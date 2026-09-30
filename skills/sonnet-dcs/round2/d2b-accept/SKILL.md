---
name: service-spec
description: Use for any task whose prompt is a multi-part spec for a service, API, or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Guides literal reading of the spec and the choices to make where it is silent.
---

# Service from a multi-part spec

## Base rules
- Read every error/condition sentence literally. "Returns X when Y" defines exactly the set Y. Do not widen Y to similar situations, and do not add error branches no sentence licenses.
- When the spec is silent, pick the behavior that keeps earlier parts' worked examples and tests passing unchanged. Earlier behavior is the tie-breaker, not "the more coherent design".
- A guess that changes an earlier part's output is wrong by default. Do not document a guess as the decision; change the guess.

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

## Literal for error conditions, liberal for what to accept
The first base rule is about error sentences: the set of conditions that produce an error is exactly what the spec names. For inputs, the direction flips: accept liberally where the spec gives no rejection example.
- If a rule says a thing "must expose A and B" and no example shows a rejection for having only one, treat it as A and/or B. A description of what a valid thing usually looks like is not a validation rule.
- Reject only inputs the spec explicitly shows being rejected, with the outcome it shows. Silence means accept and proceed.
- Before writing any validation branch, find the sentence or example that shows the rejection. None found: no branch.

## Verify before finishing a part
For each read a new write depends on, including reads defined in earlier parts, curl the three states (unknown identity; known identity with nothing set; after first write). Confirm: only state (a) is not-found; state (b) is a success body; every numeric field is a JSON number in all three. A not-found in state (b) is a bug: fix the read and re-curl. For each new write, send a body that satisfies only part of a "must expose A and B" description and confirm it is accepted unless the spec shows that rejection. Throwaway commands only; no test files, no notes files.
