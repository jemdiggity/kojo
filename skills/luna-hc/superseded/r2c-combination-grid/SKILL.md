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

- Read all existing code first. Find every place that enumerates commands, flags, operators, error types, or formats (usage string, dispatch chain, error emitter, tables) and extend each one. Stale hard-coded lists are the usual reason a new part misbehaves.
- Route every failure through one error emitter: it receives the command name and the error, looks the exit code up in one table, prints the envelope. The command field is the subcommand the user typed whenever one is present, even when a global flag or an option value was bad.
- One value parser and one value formatter, shared by all commands. A new command never gets its own copy; add a parameter instead.
- Command-line values and file contents can contain the same bad text and still map to different error types. If the runtime value parser delegates to the file parser, catch its error and re-raise the type the spec names for command-line values, and extend the runtime grammar with what the new part allows.
- Any uncaught exception is a bug: it becomes the internal-error exit, which no test expects. Translate missing files, bad JSON, failed int conversions, and KeyError or IndexError on user-supplied names into the spec's named types where you know which input caused them.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Pass 3: prove each item by running (mandatory)

Running the spec's own examples is part of implementing it; no framework or dependency is needed. Invoke with the interpreter path the spec's examples use (the entry file may not be executable; `python3` on PATH may print cache warnings, which are noise). Fixtures live inside the workspace under `scratch/`.

- For every example: create the fixture exactly, run it, compare stdout and `echo $?` with the spec byte for byte (JSON key order, prefixes, sorting, blank lines).
- For every error row of this part: trigger it with `--json` and without; confirm type, exit code, command field, and that text mode prints nothing on stdout.
- For every earlier part: one success command and one error command. A change to a shared parser, formatter, or dispatcher must not alter earlier output.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Pass 3b: the combination grid (every new feature)

The spec's examples are the simplest cases; the hidden tests combine the new feature with everything that already exists. For each new command, flag, mode, format, or operator, write a grid in the checklist and run every cell:

- x every value syntax the program already accepts (list them from the value parser: unsized, sized, each radix, separators, case variants, special digits), on the command line and in files where allowed;
- x a scalar signal, a declared width-1 vector, and a wide vector, using an asymmetric value such as `0b0011` so a reversed bit order is visible;
- x an expression nested two levels deep with a literal constant as one operand;
- x more than one output, in text and in JSON;
- x every input format the program reads: the same design written in each format;
- x each error path with the new feature active (bad value, wrong width, unknown name, missing file, bad flag value).

Read every cell's output. A crash or internal-error exit anywhere is a bug to fix now. Cells that must agree are your oracle even where the spec prints no expected output: the same design through two formats, the same value through two commands or through text and JSON, the same input in the new mode without using the new feature and in the old mode, must give identical values. When two cells disagree, one is wrong; the spec decides which. Expect ten to thirty grid runs per part; put them in one shell script under `scratch/` so a fix reruns them all.

## Finish

Delete `scratch/`. In your summary, list the commands you ran and name any item left unverified. Never finish with "did not run" while an interpreter is available.
