---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method, with a permanent suite

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. The workspace persists between parts; your memory does not. Work in three passes.

## Pass 0: inherited suite

If `regress/` exists, run `sh regress/cases.sh > regress/actual.txt; diff regress/expected.txt regress/actual.txt` before touching code; a difference is a leftover bug, fix it first.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item, the spec's sentence copied verbatim, never paraphrased:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). The exit code comes from the row naming the type, never from category prose.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file.
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "still", "unchanged", or "from this part onward". Each numbered postcondition or guarantee on an output is its own item.
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line, separately from what files may contain.

Expect 20 to 60 items.

## Pass 2: implement against the list

- Read all existing code first. Grep every enumeration of commands, flags, operators, error types, and formats (usage, dispatch, error emitter, tables) and extend each one.
- One error emitter with one exit-code table; the command field is the subcommand typed, even when a global flag or option value was bad.
- One value parser, one formatter, one data model shared by all commands; add a parameter, never a copy. A new command prints a value through the function the old command calls; compare the same value through both commands in every radix. The printed form follows the declared kind of the signal (scalar versus vector), never its width alone.
- Output that must be deterministic gets an explicit sort. "Dependency order, ties by name" means emit the smallest-named ready item at each step.
- Command-line values and file contents map the same bad text to different error types; if one parser delegates to the other, catch and re-raise the right type.
- Any uncaught exception is a bug: translate missing files, bad JSON, bad ints, and KeyError on user names into the spec's types.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `id`, builtin exception names).

## Commands that write files, transform input, or report counts

Build inside out: a pass-through version first (shared loader in, shared writer out, read back by your own reader), then one transformation at a time, rerunning that round trip after each. Then:

- Round trip: every file it writes, in every output format, is read back by the program's own reader and passes; if the reader rejects a construct the spec allows (a bare constant operand, a forward reference), fix the reader, else the writer.
- Idempotence: run the transform on its own output; the second output is byte-identical and any report says nothing changed. Preservation: compare input and output with your own evaluation or comparison command on several input values.
- Postconditions: for each numbered guarantee on the output, grep the output for the forbidden pattern (nested same-operator calls, duplicate or constant operands, non-canonical operators, undeclared names) on three inputs built to violate it, at least one through an intermediate named signal. Apply rewrites to a fixed point.
- Counts and tables: each named count follows the spec's definition of that word; feed the same design in two formats and compare. Row count as specified, no empty or `null` rows, header exact.

## Pass 3: prove each item by running (mandatory)

Invoke `python3 <entry> ...`; cache warnings on stderr are noise. Double-quote values with shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte.
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, nested expressions with a literal operand, several outputs).
- Tick an item only after its run passed.

## The regression suite

Create `regress/` in part 1 (`fixtures/`, `cases.sh`, `expected.txt`); never delete it; nothing else at the workspace root; the program never reads it.

```sh
P="python3 <entry>"
run() { echo "## $*"; $P "$@" 2>&1; echo "exit=$?"; }
run <command> regress/fixtures/<file> ...
```

One `run` line per ticked checklist row: every example, error row, value syntax, operator, kind of value, input that must stay rejected, and every bug fixed. Rerun the diff after every edit to shared code and before finishing. A changed earlier line is a regression unless the current spec changes that behaviour; regenerate `expected.txt` only when the diff shows nothing but added lines.

## Finish

You are not done while any spec example prints something other than the spec's text, any checklist item is unticked, or the suite diff shows a changed line: fix that first. Then delete `scratch/`, keep `regress/`, and list the commands you ran. Never finish with "did not run", "unresolved", or a known mismatch.
