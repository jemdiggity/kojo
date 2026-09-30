---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method, with guarded edits

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. Most points lost in later parts are old behaviour that an edit to shared code silently changed, or a main path left crashing. Work in three passes.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row naming the type; category prose never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "still", "unchanged", or "from this part onward".
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line, separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Grep every enumeration of commands, flags, operators, error types, and formats (usage, dispatch, the error emitter's idea of the current command, tables) and extend each one.
- One error emitter with one exit-code table; the command field is the subcommand typed, even when a global flag or option value was bad.
- One value parser, one value formatter, one data model shared by all commands; add a parameter, never a copy. A new input format must fill the same structures (names, ranges, expressions) as the old one.
- Command-line values and file contents map the same bad text to different error types; if the runtime parser delegates to the file parser, catch and re-raise the command-line type.
- Any uncaught exception is a bug. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known. Let the catch-all print the traceback to stderr when `CLI_DEBUG=1` is set, so you can see where a failure comes from.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Editing shared code: copy, inventory, extend, re-test

Shared code is the tokenizer, literal and value parser, expression parser, evaluator, formatter, argument loop, dispatcher, error emitter, and data model. Before the first edit to any of them:

1. Copy the entry file to `scratch/last_good`. Update the copy each time every spec example passes.
2. Write in the checklist `ACCEPTS today`: one line per input shape the function accepts (each literal form: unsized, sized, each radix, case variants, separators; each operand kind: name, literal constant, nested call, index, slice, concatenation; each declaration form; each command-line value form). Then `REJECTS today`: what it rejects on purpose, with error type and exit code (tokens forbidden in files, wrong widths, unknown names, bad flag values). Read earlier parts of the spec if the code does not make this obvious.
3. Extend, never replace. Add a branch, a parameter, or a regex alternative; never rewrite the tokenizer, the grammar, or the evaluator wholesale, however tempting a cleaner design looks. When a formerly forbidden token becomes legal in one place (a new mode, the command line, a new format), the old place must still reject it with the old error type; treating it as an ordinary identifier turns a parse error into a different error class.
4. After the edit, run one command per `ACCEPTS` line (same output as before) and one per `REJECTS` line (same type and exit code). Wherever an operand may be a name it may usually also be a literal constant: run that at top level and nested, in every mode.

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing; no framework or dependency is needed. Invoke `python3 <entry> ...` or `.venv/bin/python <entry> ...`; cache warnings on stderr are noise. Fixtures live under `scratch/`. Double-quote values containing shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, nested expressions, several outputs), not only the simplest example.
- Every earlier part: one success and one error command.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Never finish broken

If the same failure survives three fix attempts, stop patching: restore `scratch/last_good`, reread the failing item, and take a smaller step (one branch, one command, rerun). A program missing one option still scores; one whose main path crashes scores nothing, and neither does "incomplete".

## Finish

Delete `scratch/`. List the commands you ran; name anything unverified. Never finish with "did not run".
