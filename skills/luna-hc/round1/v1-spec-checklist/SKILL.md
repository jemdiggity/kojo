---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method

The spec is the test suite written in prose. Every table row, bullet, and example is checked by a hidden test. Work in three passes.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md` (delete `scratch/` at the end). One line per item, copied from the spec:

1. Each command and each flag, with its default and where it is allowed (global or per command).
2. Each error type: exit code, the exact situation that triggers it, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row that names the type; a general sentence such as "parse errors exit 2" never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "deterministic", "still", "unchanged", or "from this part onward".
5. Each example invocation with its printed output and exit code.
6. Each new value syntax accepted on the command line (new characters, sized forms, case variants, separators), separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Find every place that enumerates commands, flags, operators, error types, or formats (usage string, dispatch chain, error emitter, tables). Extend each one. Stale hard-coded lists from an earlier part are the usual reason a new part misbehaves.
- Route every failure through one error emitter that receives the command name and the error, looks the exit code up in one table, and prints the envelope. The command field is the subcommand the user typed whenever one is present, even when a global flag or an option value was bad; the placeholder for "no command" is only for invocations where no subcommand token exists.
- Value parsing and value formatting live in one function each, shared by all commands. A new command never gets its own copy; add a parameter instead.
- Command-line values and file contents can contain the same bad text and still map to different error types. If the runtime value parser delegates to the file parser, catch its error and re-raise the type the spec names for command-line values, and extend the runtime grammar with what the new part allows.
- Any uncaught exception is a bug: it becomes the internal-error exit, which no test expects. Translate missing files, bad JSON, failed int conversions, and KeyError or IndexError on user-supplied names into the spec's named types at the point where you know which input caused them.
- Do not name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names). One shadowed name breaks unrelated commands silently.

## Pass 3: prove each item by running (mandatory)

Running the spec's own examples is part of implementing it. It needs no test framework and no dependencies.

- Invoke through the interpreter: `python3 <entry> ...` or `.venv/bin/python <entry> ...`. The entry file may not be executable. Cache warnings on stderr are sandbox noise.
- Keep fixture files inside the workspace under `scratch/`, never in a system temp directory.
- For every example in the spec: create the fixture exactly, run the command, compare stdout and `echo $?` with the spec byte for byte, including JSON key order, prefixes, sorting, and blank lines.
- For every error row of this part: trigger it once with `--json` and once without; confirm type, exit code, command field, and that text mode prints nothing on stdout.
- For every new command-line value syntax: run one success case using it.
- For every new input or output format: run it with the richest existing features (multi-bit values, nested expressions), not only the scalar example.
- For every earlier part: run one success command and one error command from it. A change to a shared parser, formatter, or dispatcher must not alter earlier output.
- Tick an item in the checklist only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Finish

Delete `scratch/`. In your summary, list the commands you ran and name any item left unverified. Never finish with "did not run" while an interpreter is available.
