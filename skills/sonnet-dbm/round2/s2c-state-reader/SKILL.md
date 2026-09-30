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
hand-edited by the tests. Every way the spec describes a stored record, in prose or in an
example, is an encoding your reader must accept.

- **One reader, every encoding.** Write a single `load_record()` that every consumer calls.
  It detects by shape, not by origin: a string where a structure is expected gets parsed;
  an object with a single wrapper key holding the payload gets unwrapped; a single object
  where a list is expected gets wrapped; a missing optional key gets its default; an
  unknown extra key is ignored. Normalize into one internal form and operate only on that.
  Use the stored original when the spec records one; never require your own private
  bookkeeping to undo what the spec says is undoable from the stored record.
- **One writer, never wider.** A single `store_record()` produces exactly the spec's
  schema: same names, types, nesting. No extra column, no extra key, no different type,
  not "for convenience", not "to be safe". If you need to remember more, derive it from
  what the spec already stores.
- **Verify reader first.** The first verification command of each checkpoint: hand-write
  one stored record literally from the spec's prose (not from your tool's output), place
  it where the tool reads, and run the commands that consume it. Then run your writer and
  diff its output against the spec's shape.
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
