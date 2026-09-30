---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software: the regression script

Read the spec, keep short notes in `NOTES.md`, verify by running. The one artifact that
carries value from checkpoint to checkpoint is a **regression script** you keep in the
workspace. Earlier tests are re-run at every later checkpoint, so a bug introduced now
costs several times over; the script is how you catch it in seconds.

This is not TDD. Do not write unit tests, mocks, or a test framework. The script is a
plain shell file of real command invocations with cheap checks.

## The script: `check.sh`

- One executable file at the workspace root. Create it at the first checkpoint; append
  to it at every later one. Never delete old lines.
- Starts by resetting to a clean fixture (fresh temp dir, fresh empty state, a copy of any
  sample files). Every case must be repeatable from scratch.
- One block per case, each a real invocation of your tool followed by a one-line check:
  exit code, a `grep` of stdout/stderr for the expected text or field, or a direct
  inspection of the resulting state.
- Fail loudly: `set -u`, a `fail()` helper that prints the case name, and a summary count
  at the end. Do not `set -e`; you want all cases to run so you see every failure.
- Keep it fast (a few seconds). It runs several times per checkpoint.

Minimal shape:

```sh
#!/bin/sh
set -u; fails=0
fail() { echo "FAIL: $1"; fails=$((fails+1)); }
reset() { rm -rf work; mkdir -p work; }   # fresh fixture

reset
<tool> <example command from spec> >out 2>err; [ $? -eq 0 ] || fail "ex1 exit"
grep -q '<expected text>' out || fail "ex1 output"

reset
<tool> <bad input>            >out 2>err; [ $? -ne 0 ] || fail "err1 should fail"
grep -q '^Error:' err          || fail "err1 message"

echo "failures: $fails"; exit $fails
```

## What goes in (checklist-lite)

At each checkpoint, skim the spec section and add a case for each of:

1. Every **example command** in the spec, verbatim.
2. One **perturbation** per example (option order, path inside vs outside a directory,
   empty/null value, quoted vs bare value).
3. Every **error bullet**: the trigger, asserting non-zero exit and an `Error:` line on
   stderr (never a traceback, never a usage message for a data problem).
4. Every **reverse/undo/cleanup** path: forward, reverse, then inspect the state directly
   and compare to the state before.
5. One **hand-crafted state record** written literally from the spec's description (not
   produced by your tool), then consumed by the tool.

If the spec has N bullets, expect roughly N cases. Two-line cases are fine. Do not
polish them.

## Loop

1. Read the checkpoint's spec section. Add its cases to `check.sh` first (they will fail).
2. Implement.
3. Run `./check.sh`. Fix until `failures: 0`. Old cases failing means a regression; fix
   the regression before anything else.
4. For anything the script cannot cheaply assert, run it by hand once and note it in
   `NOTES.md`.
5. Run `./check.sh` one final time before your last message. Report the count.

## Guardrails

- Ambiguity: do not stop to ask (non-interactive). Implement every plausible reading,
  add a case for each, note the decision in `NOTES.md`.
- Output records: include every identifying field (type, target, subject, from/to); the
  spec example is a floor. Add a `grep` per field.
- Persisted state: write exactly the spec's schema, read anything reasonable.
- No broad exception handler around the entry point; usage errors from the parser only.
- Never silently weaken a guaranteed property because a shortcut failed; take the
  thorough path or error out.
- Refactoring is allowed only after `check.sh` is green, and must end green.
