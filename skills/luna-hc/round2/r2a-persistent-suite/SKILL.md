---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: checklist plus a suite that outlives the session

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. The workspace persists between parts; your memory does not. Work in four passes.

## Pass 0: run the suite you inherited

If `regress/` exists, run it before touching code: `sh regress/cases.sh > regress/actual.txt; diff regress/expected.txt regress/actual.txt`. A difference is a leftover bug in the program; fix it first. Those are the cheapest points available.

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
- Command-line values and file contents map the same bad text to different error types; if the runtime parser delegates to the file parser, catch and re-raise the command-line type. A token an earlier part forbids in files stays a parse error there, even after this part allows it on the command line or in a new mode.
- Any uncaught exception is a bug. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing; no framework or dependency is needed. Invoke `python3 <entry> ...` or `.venv/bin/python <entry> ...`; cache warnings on stderr are noise. Double-quote values containing shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, nested expressions with a literal operand, several outputs), not only the simplest example.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## The regression suite: every proven case becomes permanent

Create `regress/` in part 1 and grow it every part. Never delete it, never put it under `scratch/`, and add nothing else at the workspace root. Layout: `regress/fixtures/`, `regress/cases.sh`, `regress/expected.txt`:

```sh
cd "$(dirname "$0")/.."
P="python3 <entry>"
run() { echo "## $*"; $P "$@" 2>&1; echo "exit=$?"; }
run <command> regress/fixtures/<file> ...
```

- The moment a checklist item is ticked, append its command as a `run` line: successes, every error row, every value syntax, every input that must stay rejected, every bug you fixed. This is how the next part remembers this one.
- Rerun the diff after every edit to a shared parser, formatter, dispatcher, or data model, and once more before finishing. A changed earlier-part line is a regression in the program; edit `expected.txt` only when the current spec explicitly changes that behaviour, and say which item does.
- When everything is green: `sh regress/cases.sh > regress/expected.txt`. Relative paths only. The program must never read or import anything under `regress/`.

## Finish

Delete `scratch/`; keep `regress/`. List the commands you ran and the suite size; name anything unverified. Never finish with "did not run", and never finish while a spec example crashes.
