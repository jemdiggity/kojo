---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method

The spec is the test suite written in prose. Every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested forever. Work in three passes.

## Pass 0: run the regression suite you inherited

The workspace persists between parts but your memory does not. If `regress/` exists, run it before touching code: `sh regress/cases.sh > regress/actual.txt; diff regress/expected.txt regress/actual.txt`. It must be clean. A difference is a leftover bug: fix it first, it is the cheapest points available.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item, copied from the spec:

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

Running the spec's own examples is part of implementing it; no framework or dependency is needed. Invoke with the interpreter path the spec's examples use (the entry file may not be executable; `python3` on PATH may print cache warnings, which are noise). Fixtures live inside the workspace.

- For every example: create the fixture exactly, run it, compare stdout and `echo $?` with the spec byte for byte (JSON key order, prefixes, sorting, blank lines).
- For every error row of this part: trigger it with `--json` and without; confirm type, exit code, command field, and that text mode prints nothing on stdout.
- For every new command-line value syntax: one success case. For every new input or output format: run it with the richest existing features (multi-bit values, nested expressions), not only the scalar example.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## The regression suite: every verified case becomes permanent

Create `regress/` in part 1 and grow it in every part. It is never deleted and never lives under `scratch/`. Layout: `regress/fixtures/` (input files), `regress/cases.sh`, `regress/expected.txt`. The script:

```sh
cd "$(dirname "$0")/.."
P="<interpreter path from the spec> <entry>"
run() { echo "## $*"; $P "$@" 2>&1; echo "exit=$?"; }
run <command> regress/fixtures/<file> ...
```

Rules:
- The moment a checklist item passes, append its command as a `run` line (success cases, every error row, every value syntax, every forbidden input that must stay rejected). Every bug you fix becomes a line too.
- Rerun the suite (the `diff` from Pass 0) after every edit to a shared parser, formatter, dispatcher, or data model, and once more before finishing. A changed line for an earlier part is a regression: fix the program. Edit `expected.txt` only when the current spec explicitly changes that behaviour, and say which item.
- When everything passes, regenerate: `sh regress/cases.sh > regress/expected.txt`. Then run the diff once to confirm it is empty.
- Keep the directory self-contained: relative paths only, no code the program imports, nothing else added at the workspace root. It must never influence the program.

## Finish

Delete `scratch/`; keep `regress/`. Run the suite one last time and read the diff. In your summary, list the commands you ran and the number of suite cases. Never finish with "did not run" while an interpreter is available.
