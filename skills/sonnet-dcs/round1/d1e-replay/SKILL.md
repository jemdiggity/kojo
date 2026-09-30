---
name: service-spec
description: Use for any task whose prompt is a multi-part spec for a service, API, or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Guides literal reading of the spec and the choices to make where it is silent.
---

# Service from a multi-part spec

## Base rules
- Read every error/condition sentence literally. "Returns X when Y" defines exactly the set Y. Do not widen Y to similar situations, and do not add error branches no sentence licenses.
- When the spec is silent, pick the behavior that keeps earlier parts' worked examples and tests passing unchanged. Earlier behavior is the tie-breaker, not "the more coherent design".
- A guess that changes an earlier part's output is wrong by default. Do not document a guess as the decision; change the guess.

## Empty-state walk-through
Before coding a part, trace each new workflow from an empty store: (a) identity missing; (b) identity exists but the value has not been set yet; (c) after the first write. Not-found is only for the exact condition the spec names, normally (a). State (b) is a success response with an explicit typed "nothing yet" value (a number stays a number, a list stays a list, never null), and any operation that "starts from the current value" proceeds from that sentinel.

## Conditional fields: omit, never null
A field that applies only in some situations is left out of the body when it does not apply; do not emit it as null. Add keys to a response dict under the condition that makes them apply. A field introduced by a later part appears only in the responses the spec shows it in; earlier parts' bodies stay byte-identical.

## Replay step (one command loop, before declaring part N done)
With the server running, re-issue every worked example from parts 1..N-1 as well as part N, and compare the whole body against the example in the prompt, keys sorted:

```
curl -s -X METHOD http://localhost:PORT/PATH -H 'content-type: application/json' -d 'EXAMPLE_BODY' \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), sort_keys=True))'
```

Print the prompt's expected body through the same `json.dumps(..., sort_keys=True)` and eyeball the two lines side by side. Any extra key, missing key, key present-as-null, or changed value type is a regression introduced by part N: fix the new code, never the old example. Also re-issue the earlier parts' stated error cases and confirm the status is unchanged.

Do this ad hoc in the shell. Do not save a test suite, script file, or notes file; the loop is throwaway and re-typed each part.
