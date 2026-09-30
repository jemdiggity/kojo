---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method

The spec is the test suite written in prose. Every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested forever. Work in three passes.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md` (delete `scratch/` at the end), one line per item, copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row naming the type; a general sentence such as "parse errors exit 2" never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "deterministic", "still", "unchanged", or "from this part onward".
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line (new characters, sized forms, case variants, separators), separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Find every place that enumerates commands, flags, operators, error types, or formats (usage, dispatch, error emitter, tables) and extend each one. Stale hard-coded lists are the usual reason a new part misbehaves.
- Route every failure through one error emitter: it receives the command name and the error, looks the exit code up in one table, prints the envelope. The command field is the subcommand the user typed whenever one is present, even when a global flag or an option value was bad.
- One value parser and one value formatter, shared by all commands. A new command never gets its own copy; add a parameter instead.
- Command-line values and file contents can contain the same bad text and still map to different error types. If the runtime value parser delegates to the file parser, catch its error and re-raise the type the spec names for command-line values, and extend the runtime grammar with what the new part allows.
- Any uncaught exception is a bug: it becomes the internal-error exit, which no test expects. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Editing shared code: inventory, extend, re-test

Shared code: tokenizer, literal or value parser, expression parser, formatter, argument loop and dispatcher, error emitter, data model. Most points lost in later parts are old behaviour that an edit to one of these silently changed. Before you edit one:

1. Inventory. Add two sections to the checklist. `ACCEPTS today`: read the function and list every input shape it accepts, one line each (each literal form: unsized, sized, each radix, separators, case; each operand kind: name, literal constant, nested call, index, slice, concatenation; each declaration form; each command-line value form). `REJECTS today`: what it rejects on purpose, with error type and exit code (forbidden tokens in files, wrong widths, unknown names, bad flag values).
2. Extend, never replace. Add a branch or a parameter for the new form; do not rewrite the tokenizer or the regex wholesale. When the new part makes a formerly forbidden token legal in one place (a new mode, the command line, a new format), the old place must still reject it with the old error type; "treat it as an identifier" turns a parse error into a different error class.
3. Re-test every line. After the edit, run one command per `ACCEPTS` line (same output as before) and one per `REJECTS` line (same type and exit code). A rejection that became a different type, or a success, is a regression even though no example in this part shows it.
4. Literal operands. Wherever an operand may be a name it usually may be a literal constant. After any parser change run a literal operand at top level and nested inside a call, in every mode.

## Pass 3: prove each item by running (mandatory)

Running the spec's own examples is part of implementing it; no framework or dependency is needed. Invoke with the interpreter path the spec's examples use; `python3` on PATH may print cache warnings, which are noise. Fixtures live inside the workspace under `scratch/`.

- Every example: fixture exactly as given, compare stdout and `echo $?` byte for byte (JSON key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- For every new command-line value syntax: one success case. For every new input or output format: run it with the richest existing features (multi-bit values, nested expressions), not only the scalar example.
- For every earlier part: one success command and one error command, plus the `ACCEPTS`/`REJECTS` re-test of every shared function you touched.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Finish

Delete `scratch/`. In your summary, list the commands you ran and name any item left unverified. Never finish with "did not run" while an interpreter is available.
