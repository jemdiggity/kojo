---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software: accept the union, emit the superset

Read the spec, keep short notes in `NOTES.md`, and verify by running real commands.
Beyond that base, two rules decide most of the hidden-test outcome.

## Rule 1: When the spec is silent or ambiguous, implement the union

Hidden tests were written by someone with one reading in mind, and you cannot ask which.
A documented guess loses whenever it is the other reading. So never pick one:
make every plausible reading work.

Concretely, whenever you notice yourself deciding, do all of the following that apply:

- **Value semantics:** a field could be an expression or a literal? Try the richer
  interpretation first, fall back to the literal on failure. A sibling field with the same
  role tells you the intended semantics; match it.
- **Option placement:** accept options before, between, and after positional arguments.
- **Container shapes:** accept a bare list *and* an object wrapper around it; accept a
  string *and* a structured object where either could encode the same thing; accept
  missing optional keys with sensible defaults.
- **Locations:** accept a file inside the expected directory *and* a path outside it;
  relative and absolute paths; with and without extension where sensible.
- **Case and spelling:** accept case-insensitive keywords and common aliases when the spec
  does not forbid it.
- **Pre-existing state:** read state you did not write (other tools, earlier versions,
  hand-authored files). Parse liberally; tolerate extra keys and alternative encodings.

Do not confuse "accept the union" with "do anything". Where the spec explicitly says an
input is an error, it is an error. Where the spec says nothing, be generous on input.

Write each union decision as one line in `NOTES.md` under `## Ambiguities` so later
checkpoints preserve it.

## Rule 2: Output events echo every identifying field

Any structured output (a JSON event, a log line, a status record, a dry-run plan) must
carry **every** field that identifies what happened, not just the fields shown in the
spec's example:

- operation type / action name
- the target object (table, file, resource, key), including its parent/container
- the subject inside the target (column, field, index, entry) when one exists
- before/after or from/to values for renames, moves, type changes, data rewrites
- the name of anything created or removed as a side effect

The spec's example output is a **floor**, not a ceiling. Tests check for fields being
present and correct; an extra key costs nothing, a missing key fails the test. When you
build the reverse/undo/rollback record for an operation, it must identify its target as
completely as the forward record did.

Before finishing each checkpoint, print one real event of each type your tool can emit
and inspect it: for each, ask "could a reader reconstruct exactly what happened, on what,
from this line alone?" If not, add fields.

## Verify by running

- Run every example command in the spec verbatim, then once more with a perturbation
  (option order, path location, empty/null value, quoted vs bare value).
- Trigger every error bullet on purpose and check message, stream, and exit code.
- Hand-craft an input that a *different* reasonable implementer might produce, and make
  sure it is accepted.

## Do not

- Do not stop to ask about an ambiguity; the run is non-interactive. Implement both.
- Do not reject inputs the spec does not explicitly forbid.
- Do not wrap the command entry point in a broad exception handler that turns runtime
  failures into usage messages. Usage errors come from the argument parser only; all other
  failures print `Error: <reason>` to stderr and exit non-zero, without a traceback.
- Do not silently drop a guaranteed property because a fast path cannot preserve it; use
  the thorough path or fail loudly.
