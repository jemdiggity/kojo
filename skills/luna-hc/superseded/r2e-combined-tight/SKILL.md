---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method

The spec is the test suite written in prose. Every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested forever. Work in three passes.

## Pass 0: inherited suite

The workspace persists between parts; your memory does not. If `regress/` exists, run `sh regress/cases.sh > regress/actual.txt; diff regress/expected.txt regress/actual.txt` before touching code. A difference is a leftover bug: fix it first.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item, copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row naming the type; category prose never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "deterministic", "still", "unchanged", or "from this part onward".
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line, separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Find every place that enumerates commands, flags, operators, error types, or formats (usage, dispatch, error emitter, tables) and extend each one.
- One error emitter: receives the command name and the error, looks the exit code up in one table, prints the envelope. The command field is the subcommand typed whenever one is present, even when a global flag or option value was bad.
- One value parser and one value formatter shared by all commands; add parameters, never copies. The formatter picks scalar or vector form by the declared kind, never by width alone.
- Command-line values and file contents map the same bad text to different error types. If the runtime parser delegates to the file parser, catch and re-raise the command-line type, and extend the runtime grammar with what the new part allows.
- Extend shared parsers, never rewrite them. When a formerly forbidden token becomes legal in one place, the old place must still reject it with the old error type. Wherever an operand may be a name it may usually be a literal constant too; keep that working at every nesting depth and in every mode.
- Any uncaught exception is a bug (internal-error exit, which no test expects). Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known. Make the catch-all print the traceback to stderr when an environment variable such as `CLI_DEBUG=1` is set, so you can see where a failure comes from.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing. Invoke with the interpreter path the spec's examples use; `python3` on PATH may print cache warnings, which are noise. Fixtures live inside the workspace.

- Every example: fixture exactly as given, compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, nested expressions with a literal operand, more than one output, JSON), not only the scalar example.
- Agreement oracles need no expected output: the same design through two formats, the same value through two commands or text and JSON, must be identical. Every file the program writes must be read back by your own reader and pass; a transform run on its own output must change nothing.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## The regression suite

Create `regress/` in part 1 (`fixtures/`, `cases.sh`, `expected.txt`); never delete it, never put it under `scratch/`, add nothing else at the workspace root.

```sh
cd "$(dirname "$0")/.."
P="<interpreter path from the spec> <entry>"
run() { echo "## $*"; $P "$@" 2>&1; echo "exit=$?"; }
run <command> regress/fixtures/<file> ...
```

Each item that passes becomes a `run` line (successes, error rows, value syntaxes, forbidden inputs that must stay rejected, every bug you fixed). Rerun the diff after every edit to shared code and before finishing; a changed earlier-part line is a regression in the program, unless the current spec explicitly changes that behaviour. When all is green: `sh regress/cases.sh > regress/expected.txt`.

## Never finish broken

Get the simplest spec example passing before adding options, then copy the entry file to `scratch/last_good`. If a later change leaves any spec example failing after three fix attempts, restore `scratch/last_good` and take a smaller step. A program missing an option scores; a program whose main path crashes scores nothing. "Incomplete" is not a finished state.

## Finish

Delete `scratch/`; keep `regress/`. List the commands you ran. Never finish with "did not run".
