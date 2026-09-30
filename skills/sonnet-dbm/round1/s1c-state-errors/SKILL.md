---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software: state, guarantees, errors

Read the spec, keep short notes in `NOTES.md`, verify by running real commands. On top of
that base, three disciplines cover where hidden tests actually probe: persisted state,
guaranteed properties, and error behaviour.

## 1. Persisted state is an external interface

Anything your tool writes to disk or a database and reads back later (a history table, a
manifest, a lock file, a config record) will be pre-seeded, inspected, and hand-edited by
the tests. Treat it like a wire protocol, not a private cache.

- **Write exactly the schema the spec gives.** Same names, same types, same nesting, no
  extra columns or keys "for convenience". Tests compare against the spec's shape.
- **Read liberally.** Tolerate records you did not write: missing optional keys, extra
  keys, an object wrapper where you expected a list (or vice versa), a string where you
  expected a structure (or vice versa), older or hand-authored encodings. Normalize on
  load into one internal form, then operate on that.
- **Prove it once per checkpoint.** Hand-craft a state record *literally* from the spec's
  description (not from your own tool's output), place it where the tool expects it, and
  run the commands that consume it. Then run the writer and diff the result against the
  spec's shape.
- **Unparseable state is an error, not a crash.** If a record cannot be understood, print
  `Error: <what and where>` to stderr and exit non-zero. Never let a traceback escape.

## 2. No silent degradation

When the spec guarantees a property (a constraint survives, ordering is preserved, an
undo restores the previous definition exactly, a value round-trips), and your fast path
cannot deliver it in some case, do **not** quietly fall through to a weaker result.

- Prefer the heavier existing path that does preserve the property (a full rebuild, a
  copy-and-swap, a re-derivation from the recorded original).
- If no path can preserve it, fail with an explicit `Error:` rather than succeeding
  with less than promised.
- After any reverse/undo operation, inspect the resulting state directly (list the
  definitions, query the metadata) and compare it to the state before the forward
  operation. "It printed success" is not verification.

## 3. Error discipline

- **Usage errors come only from the argument parser.** Invalid or missing arguments,
  unknown options, wrong arity. Nothing else may produce a usage message.
- **Every other failure** (bad input file, missing target, conflicting state, failed
  validation, unexpected data) prints `Error: <specific reason>` on stderr and exits with
  the non-zero code the spec assigns, with no traceback and no partial output on stdout.
- **No broad `except` around the command entry point.** A catch-all that reports every
  exception as a usage error hides data bugs and fails the tests that check the specific
  message. Catch specific exceptions at the point where you can name the cause.
- **Missing target means error, not create.** If an operation refers to something that
  does not exist (a column, a file, an entry), report it. Do not helpfully auto-create it
  unless the spec says so.
- **Validation before mutation.** Check every precondition, then apply. Half-applied
  changes with an error afterwards fail more tests than a clean refusal.
- **Trigger each error bullet in the spec before finishing.** Craft the input, run it,
  check the message text, the stream, and the exit code.

## Checkpoint routine

1. List, in `NOTES.md`, every state shape, guaranteed property, and error bullet this
   checkpoint touches (one line each).
2. Implement.
3. Run every spec example verbatim, then: one hand-crafted state record, one
   reverse/undo followed by direct inspection, and every error bullet on purpose.
4. Re-read the list; anything not exercised by a real run gets a run now.

## Do not

- Do not add extra metadata fields to persisted records "to be safe".
- Do not reject records merely because they are shaped differently from what you emit.
- Do not stop to ask about an ambiguity; the run is non-interactive. Accept every
  plausible reading on input, emit the spec's exact shape on output.
