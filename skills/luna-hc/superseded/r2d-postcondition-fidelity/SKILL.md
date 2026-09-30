---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method

The spec is the test suite written in prose. Every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested forever. Work in three passes.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item, copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row naming the type; a general sentence such as "parse errors exit 2" never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file, and the form the example uses for each kind of value (scalar, vector, count).
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "deterministic", "still", "unchanged", or "from this part onward". Each numbered postcondition on an output is its own item.
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line (new characters, sized forms, case variants, separators), separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Find every place that enumerates commands, flags, operators, error types, or formats (usage, dispatch, error emitter, tables) and extend each one. Stale hard-coded lists are the usual reason a new part misbehaves.
- One error emitter: receives the command name and the error, looks the exit code up in one table, prints the envelope. The command field is the subcommand typed whenever one is present, even when a global flag or option value was bad.
- One value parser and one value formatter, shared by all commands; add a parameter, never a copy. The formatter chooses the printed form by the declared kind of the signal as the spec defines it (scalar versus vector), never by width alone; a new command prints a value by calling the same function the existing command calls.
- Command-line values and file contents map the same bad text to different error types. If the runtime parser delegates to the file parser, catch and re-raise the command-line type, and extend the runtime grammar with what the new part allows.
- Any uncaught exception is a bug (internal-error exit, which no test expects). Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Commands that write files or transform their input

Their tests check properties of the output, not one expected string:

- Round trip: feed every file the program writes back into your own reader (the checking command, or whichever command reads that format). It must succeed. If the output holds a construct your parser rejects, such as a bare constant operand, fix the parser, then the writer.
- Idempotence: run the transform on its own output; the second output must be byte-identical and any report must say nothing changed.
- Preservation: when the spec promises behaviour is kept, compare input and output on several input vectors with your own evaluation or comparison command.
- Postcondition scanner: for each numbered postcondition write a short `grep`-style check over the output text (nested same-operator calls, duplicate arguments, constant operands, an operand that also appears inside a sibling operand, non-canonical operators) and run it on three inputs built to violate that rule through an intermediate named signal, not only directly. Apply rewrites to a fixed point: one pass misses patterns that appear after another rule fires.
- Reports, counts, tables: each named count follows the spec's definition of that term for that input format; feed the same design in two formats and compare. Row count as specified, no empty or null rows, header exact.

## Pass 3: prove each item by running (mandatory)

Running the spec's own examples is part of implementing it; no framework or dependency is needed. Invoke with the interpreter path the spec's examples use; `python3` on PATH may print cache warnings, which are noise. Fixtures live inside the workspace under `scratch/`.

- Every example: fixture exactly as given, compare stdout and `echo $?` byte for byte (JSON key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new input or output format: run with the richest existing features (multi-bit values, nested expressions), not only the scalar example.
- For every value-printing command: one scalar, one width-1 vector, one wide vector; forms must match the spec's example for each kind and the existing command's output for the same signal.
- For every earlier part: one success command and one error command. Shared-code changes must not alter earlier output.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Finish

Delete `scratch/`. In your summary, list the commands you ran and name any item left unverified. Never finish with "did not run" while an interpreter is available.
