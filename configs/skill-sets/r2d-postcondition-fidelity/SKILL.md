---
name: cli-software
description: Working rules for implementing or extending a command-line program from a written specification (subcommands, flags, exit codes, text and JSON output, error types). Use for every task whose prompt is a CLI spec; it shows how to turn the spec into a checklist, implement it, and prove each item by running the program before finishing.
---
# CLI from spec: the checklist method, with output contracts

The spec is the test suite written in prose: every table row, bullet, and example is checked by a hidden test, and every earlier part stays tested. Commands that write files or transform input are tested on properties of their output; the cheapest checker is the program itself. Work in three passes.

## Pass 1: extract the checklist (before writing code)

Write a numbered list into `scratch/CHECKLIST.md`, one line per item copied from the spec:

1. Each command and flag, with its default and where it is allowed.
2. Each error type: exit code, exact trigger, and where the bad input comes from (command-line value, file contents, semantic check). Take the exit code from the row naming the type; category prose never overrides an explicit number.
3. Each output shape: field names, order, value formatting (prefixes, widths, sorting), text versus JSON, stdout versus file, and the printed form the example uses for each kind of value (scalar, vector, count).
4. Each sentence containing "must", "never", "only", "exactly", "sorted", "still", "unchanged", or "from this part onward". Each numbered postcondition or guarantee on an output is its own item.
5. Each example invocation with its printed output and exit code.
6. Each value syntax accepted on the command line, separately from what files may contain.

Expect 20 to 60 items. Fewer means you skipped part of the spec; reread it.

## Pass 2: implement against the list

- Read all existing code first. Grep every enumeration of commands, flags, operators, error types, and formats (usage, dispatch, the error emitter's idea of the current command, tables) and extend each one.
- One error emitter with one exit-code table; the command field is the subcommand typed, even when a global flag or option value was bad.
- One value parser, one value formatter, one data model shared by all commands; add a parameter, never a copy. A new command prints a value by calling the function the existing command calls; the printed form follows the declared kind of the signal (scalar versus vector), never its width alone.
- Command-line values and file contents map the same bad text to different error types; if the runtime parser delegates to the file parser, catch and re-raise the command-line type.
- Any uncaught exception is a bug. Translate missing files, bad JSON, failed int conversions, KeyError or IndexError on user names into the spec's types where the input origin is known.
- Never name variables or classes after builtins or helpers you call (`format`, `type`, `input`, `id`, `hash`, builtin exception names).

## Commands that write files, transform input, or report counts

Build from the inside out: first a pass-through version (shared loader in, shared writer out, result read back by your own reading command and passing), then one transformation or pass at a time, rerunning that round trip after each. If the same failure survives three attempts, restore the last version that passed and take a smaller step. On the finished command:

- Round trip: every file it writes, in every output format, is read back by the program's own reader and passes. If the output holds a construct the reader rejects (a bare constant operand, an undeclared name, a reference ahead of its definition), fix the reader when the spec allows the construct, otherwise the writer.
- Idempotence: run the transform on its own output; the second output is byte-identical and any report says nothing changed.
- Preservation: when the spec promises behaviour is kept, compare input and output with your own evaluation or comparison command on several input values, not one.
- Postconditions: for each numbered guarantee on the output, write a short grep-style check over the output text (nested same-operator calls, duplicate or constant operands, an operand repeated inside a sibling operand, non-canonical operators, undeclared names) and run it on three inputs built to violate the rule, at least one through an intermediate named signal. Apply rewrites to a fixed point: one pass misses patterns another rule creates.
- Counts and tables: each named count follows the spec's definition of that word for that input format; feed the same design in two formats and compare. Row count as specified, no empty or `null` rows, header exact.

## Pass 3: prove each item by running (mandatory)

Running the spec's examples is part of implementing; no framework or dependency is needed. Invoke `python3 <entry> ...` or `.venv/bin/python <entry> ...`; cache warnings on stderr are noise. Fixtures live under `scratch/`. Double-quote values containing shell-special characters.

- Every example: fixture exactly as given; compare stdout and `echo $?` byte for byte (key order, prefixes, sorting, blank lines).
- Every error row: with `--json` and without; type, exit code, command field, nothing on stdout in text mode.
- Every new value syntax: one success. Every new format, mode, or command: run with the richest existing features (wide values, nested expressions with a literal operand, several outputs), not only the simplest example.
- Every value-printing command: one scalar, one width-1 vector, one wide vector; the forms must match the spec's example for each kind.
- Every earlier part: one success and one error command.
- Tick an item only after its run passed. Fix and rerun until all are ticked. Spend at least a third of your effort here.

## Finish

Delete `scratch/`. List the commands you ran; name anything unverified. Never finish with "did not run" or while a spec example crashes.
