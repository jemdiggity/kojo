---
name: cli-software
description: Short rules for implementing or extending a command-line program from a specification: read the spec as a checklist, keep one error emitter and one formatter, and run the spec's examples and error cases through your program before finishing. Use for every task whose prompt is a CLI spec.
---
# CLI from spec: the short rules

1. The spec is the test suite. Before coding, list every command, flag, error row (type, exit code, trigger), output field, and example. Keep the list until each item has been run.
2. Exit codes come from the row that names the error type. Category prose never overrides an explicit number.
3. One error emitter, one exit table. The envelope's command field is the subcommand the user typed whenever one is present, even for bad global flags or option values; the "no command" placeholder is only for invocations without a subcommand token. Never derive it from a hard-coded list of commands.
4. A traceback or internal-error exit is always a bug. Translate foreign exceptions (missing file, bad JSON, failed int conversion, KeyError on a user name) into the spec's types where the input origin is known.
5. Command-line values and file contents have different error types even for the same bad text. If the runtime value parser reuses the file parser, catch and re-raise the command-line type, and extend the runtime grammar with every new value syntax the part allows.
6. One value parser, one value formatter, one data model, shared by all commands and formats. Extend with parameters; never copy.
7. Adding a command or flag means updating every place that enumerates them: usage text, dispatcher, error handler.
8. Do not shadow builtins or helpers (`format`, `type`, `input`, `id`, `hash`), and never name a class like a builtin exception.
9. Run the program. `python3 <entry> args; echo $?` with fixtures in `scratch/` inside the workspace (system temp may be blocked, the entry may not be executable, stderr cache warnings are noise). Running the spec's examples is part of the task, not extra testing; no framework or dependencies.
10. Run every example of the current part and match stdout and exit code byte for byte (key order, prefixes, sorting, blank lines). Trigger every new error type once with `--json` and check type, exit code, command field.
11. After any change to shared code, rerun one success and one error case from every earlier part.
12. Exercise new formats and commands with the richest existing features (multi-bit values, nested expressions), not just the simplest example.
13. Where output must be deterministic, sort explicitly; "dependency order, ties by name" means emit the smallest-named ready item each step.
14. Delete `scratch/` and report which commands you ran. Never finish with "did not run".
