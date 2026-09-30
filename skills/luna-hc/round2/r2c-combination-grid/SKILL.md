---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method, with a combination grid

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. The spec's examples are the simplest cases; the hidden tests combine each new feature with everything that already exists. Work in three passes.

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
- One value parser, one value formatter, one data model shared by all commands; add a parameter, never a copy. A new input format must fill the same structures (names, ranges, expressions) as the old one. The formatter picks the printed form by the declared kind of a signal (scalar versus vector), never by its width alone.
- Command-line values and file contents map the same bad text to different error types; if the runtime parser delegates to the file parser, catch and re-raise the command-line type.
- Any uncaught exception is a bug. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing; no framework or dependency is needed. Invoke `python3 <entry> ...` or `.venv/bin/python <entry> ...`; cache warnings on stderr are noise. Fixtures live under `scratch/`. Double-quote values containing shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every earlier part: one success and one error command.
- Tick an item only after its run passed. Fix and rerun until all are ticked.

## Pass 3b: the combination grid (every new feature)

For each new command, flag, mode, format, or operator, add a grid to the checklist and run every cell from one script, `scratch/grid.sh` (`run() { echo "## $*"; $P "$@"; echo "exit=$?"; }`), so a fix reruns them all:

- x every value syntax the program already accepts (list them from the value parser: unsized, sized, each radix, case variants, special digits), on the command line and in files where allowed;
- x a scalar signal, a declared width-1 vector, and a wide vector, using an asymmetric value such as `0b0011` so reversed bit order is visible;
- x an expression nested two levels deep with a literal constant as one operand;
- x more than one output, in text and in JSON;
- x every input format the program reads: the same design written in each;
- x the new flag on an old command, an old feature through the new format, the new command on an old example's fixture;
- x each error path with the new feature active (bad value, wrong width, unknown name, missing file, bad flag value).

A crash or internal-error exit in any cell is a bug to fix now. Cells that must agree are your oracle where the spec prints no expected output: the same design through two formats, the same value through two commands or through text and JSON, and the new mode without using the new feature versus the old mode, must give identical values. When two cells disagree, one is wrong and the spec decides which. Expect ten to thirty grid runs per part; spend at least a third of your effort in Pass 3.

## Finish

Delete `scratch/`. List the commands you ran; name anything unverified. Never finish with "did not run", and never finish while a spec example crashes.
