---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: checklist, guarded edits, permanent suite

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. The workspace persists between parts; your memory does not.

## Pass 0: inherited suite

If `regress/` exists, run `sh regress/cases.sh > regress/actual.txt; diff regress/expected.txt regress/actual.txt` before touching code. A difference is a leftover bug in the program: fix it first.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). The exit code comes from the row naming the type, never from category prose.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "still", "unchanged", or "from this part onward"; each is a mixed case with an earlier part to run.
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line, separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Grep every enumeration of commands, flags, operators, error types, and formats (usage, dispatch, the error emitter's idea of the current command, tables) and extend each one.
- Copy the entry file to `scratch/last_good` before the first edit and again whenever every spec example passes.
- Extend shared code (tokenizer, parsers, evaluator, formatter, dispatcher, error emitter, data model); never rewrite it wholesale. A token an earlier part forbids in files stays a parse error there after this part allows it elsewhere. Wherever an operand may be a name it may usually also be a literal constant; keep that working at every nesting depth and in every mode.
- One error emitter with one exit-code table; the command field is the subcommand typed, even when a global flag or option value was bad.
- One value parser, one value formatter, one data model shared by all commands; add a parameter, never a copy. A new input format must fill the same structures (names, ranges, expressions) as the old one. The printed form of a value follows the declared kind of the signal (scalar versus vector), never its width alone.
- Command-line values and file contents map the same bad text to different error types; if the runtime parser delegates to the file parser, catch and re-raise the command-line type.
- Any uncaught exception is a bug. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing; no framework or dependency is needed. Invoke `python3 <entry> ...` or `.venv/bin/python <entry> ...`; cache warnings on stderr are noise. Double-quote values containing shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, an asymmetric value such as `0b0011`, nested expressions with a literal operand, several outputs, JSON) and the mixed cases (new flag on an old command, old feature through the new format).
- Agreement oracles need no expected output: the same design through two formats, or the same value through two commands or through text and JSON, must be identical. Every file the program writes is read back by its own reader and passes; a transform run on its own output changes nothing.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## The regression suite

Create `regress/` in part 1 (`fixtures/`, `cases.sh`, `expected.txt`); never delete it, never put it under `scratch/`, add nothing else at the workspace root.

```sh
cd "$(dirname "$0")/.."
P="python3 <entry>"
run() { echo "## $*"; $P "$@" 2>&1; echo "exit=$?"; }
run <command> regress/fixtures/<file> ...
```

Each ticked item becomes a `run` line (successes, error rows, value syntaxes, inputs that must stay rejected, every bug you fixed). Rerun the diff after every edit to shared code and before finishing; a changed earlier-part line is a regression unless the current spec explicitly changes that behaviour. When all is green: `sh regress/cases.sh > regress/expected.txt`. The program never reads anything under `regress/`.

## Never finish broken

If the same failure survives three fix attempts, restore `scratch/last_good` and take a smaller step. A program missing one option still scores; one whose main path crashes scores nothing, and neither does "incomplete".

## Finish

Delete `scratch/`; keep `regress/`. List the commands you ran; name anything unverified. Never finish with "did not run".
