---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software: liberal in, exact out

One rule: **accept every plausible reading on input, emit the spec's exact shape on output.**
Read the spec, implement, verify by running real commands. Never stop to ask; the run is
non-interactive.

## Persisted state is a wire protocol

Anything written to disk or a database and read back later will be pre-seeded and
hand-edited by the tests.

- Write exactly the spec's schema: same names, types, nesting. No extra columns or keys,
  not "for convenience", not "to be safe".
- Read liberally: tolerate missing optional keys, extra keys, an object wrapper where you
  expected a list (or the reverse), a string where you expected a structure (or the
  reverse), older encodings. Normalize on load into one internal form.
- Unparseable state is an error with a specific message, never a traceback.

## No silent degradation

When the spec guarantees a property (a constraint survives, order holds, an undo restores
the original exactly, a value round-trips) and the fast path cannot deliver it, do not
fall through to a weaker result. Take the heavier existing path (full rebuild,
copy-and-swap, re-derive from the recorded original). If nothing can preserve it, fail
with an explicit error. After an undo, inspect the resulting state directly and compare
it with the state before.

## Error discipline

- Usage errors come only from the argument parser. Nothing else prints usage.
- Every other failure prints `Error: <specific reason>` to stderr and exits with the code
  the spec assigns; no traceback, no partial stdout.
- No broad `except` around the entry point; catch specific exceptions where you can name
  the cause.
- Missing target means error, not auto-create, unless the spec says otherwise.
- Validate every precondition, then mutate. A clean refusal beats a half-applied change.
- Trigger each error bullet once before finishing: check message, stream, exit code.

## Do not

- Do not add fields to emitted records or stored rows beyond what the spec shows.
- Do not reject records merely because they differ in shape from what you emit.
