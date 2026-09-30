---
name: cli-software
description: Rules for the error and output contract of a command-line program built from a specification: exit codes, error type names, the error envelope's command field, error types by input origin, and single-source formatting. Use for every task that specifies a CLI with error tables and JSON or text output, and verify each rule by running the program.
---
# Error contract discipline for CLIs

Roughly a third of hidden tests exercise failure paths, and each checks four things at once: exit code, error type name, the command field of the error envelope, and that nothing else reached stdout. Build the machinery right once and every error case passes; get it wrong once and every error case of every later part fails.

## Build the machinery first

1. One exception class per spec error type, all inheriting from one base. The class name equals the spec's type string exactly.
2. One table mapping type to exit code, filled from the spec's tables. Take the number from the row that names the type. Category prose ("validation errors exit 3") never overrides an explicit row.
3. One emitter `fail(command, err)` that prints the text form to stderr or the JSON envelope to stdout, then exits with the mapped code. Every non-success exit goes through it.
4. The command argument is the subcommand token the user typed whenever one is present, including when the failure is a bad global flag, a bad option value, or a missing file. Use the "no command" placeholder only when no subcommand token can be identified (no arguments, unknown command). Do not compute it from a hard-coded list of known commands; when you add a command later, that list silently mislabels it. Parse global flags, then find the command token, then validate values, and pass the token to every failure.
5. Wrap the dispatcher in a catch-all that converts any other exception into the internal-error type. During your own runs, treat every appearance of that type as a bug to fix, because no test expects it.

## Map each error to its input origin

The same bad text means different types depending on where it came from. Decide per origin:

- Command-line option values (names, numbers, seeds, radix, assigned values): the spec's usage or value error types.
- File contents: parse types for syntax, validation types for semantics, with file, line, and column filled in when known.
- Cross-object checks (ports of two files, names referenced across sections): the semantic type the spec names for that check.

If a runtime value parser reuses the file literal parser, catch its exception and re-raise the type the spec names for command-line values. Never let a file parse type escape for text typed on the command line. Also re-read what the new part allows in command-line values (new characters, sized forms, case variants) and extend the runtime grammar while leaving the file grammar as the spec states.

## Foreign exceptions

Translate at the boundary where the origin is known: `open()` failure to the missing-file type; JSON decode failure to the JSON parse type; `int()` failure to the usage or value type; KeyError or IndexError on a user-referenced name to the undefined-name or bounds type. Never define a class with the same name as a builtin exception; the builtin then bypasses your handler and falls to the catch-all. Never name a variable after a builtin you call (`format`, `type`, `input`, `id`).

## Success side of the contract

- JSON mode prints exactly one object on stdout and nothing else; text mode prints exactly what the example shows.
- Field names, order, and formatting come from the example for that command. A value's format (prefix, width, sort order) is identical in every command that prints it; use the one shared formatter and extend it with parameters instead of copying it.
- Exit codes that carry a result rather than a failure are not errors: the payload keeps the success flag.
- Where the spec says "sorted", "deterministic", or "dependency order, ties by name", add an explicit sort; for dependency order emit the smallest-named ready item each step.

## Verify by running (required)

Running the spec's examples is part of implementing it; no framework or dependency is needed. Invoke through the interpreter (`python3 <entry> ...`; the file may not be executable) with fixtures kept inside the workspace under `scratch/` (delete it at the end). Cache warnings on stderr are noise.

- For every error row of the current part: trigger it once with `--json` and once without. Check `echo $?`, the type string, the command field, and that text mode leaves stdout empty.
- For every example in the spec: run it and compare output byte for byte.
- For every new command-line value syntax: one success run.
- For each earlier part: one success and one error run. Shared error machinery changes reach them all.
- Fix anything that prints a traceback or the internal-error type before finishing.

## Before coding a new part

List every error row (type, exit code, trigger, input origin) and every example; keep the list until each item has been run. Update the usage text, the dispatcher, the exception classes, and the exit table together. Report which runs you did; never finish with "did not run".
