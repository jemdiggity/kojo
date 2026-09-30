---
name: cli-software
description: Verification-first rules for building or extending a command-line tool from a specification. Run the spec's examples and error cases through your own program after every change, inside the sandbox, before you report done. Use for every task that hands you a CLI spec with commands, flags, exit codes, and output formats.
---
# Run it before you report it

Untested CLI code fails hidden tests in bulk. One crash on a command's main path loses every test of that command; one broken shared function loses every earlier part too. The only defence is executing the program. The task asks for a program that satisfies the spec, so running the spec's examples is part of implementing, not optional extra testing. No framework, no dependencies.

## How to run in this sandbox

- Invoke through the interpreter: `python3 <entry> args` or `.venv/bin/python <entry> args`. `./<entry>` may be refused.
- Create fixture files inside the workspace under `scratch/`. System temp directories may be blocked. Remove `scratch/` before finishing.
- Warnings on stderr about cache files are sandbox noise; ignore them.
- Always check the exit code: `python3 <entry> ...; echo "exit=$?"`.

## The smoke script

Create `scratch/smoke.sh` as soon as the first command works and grow it in every part:

```sh
set -u
E="python3 <entry>"
run() { echo "## $*"; $E "$@"; echo "exit=$?"; }
run <command from a spec example>
run <same command> --json
run <an error case> --json
```

Run it after every edit to shared code (argument parsing, parser, evaluator, formatter, error emitter) and once more right before you finish. Read all of the output. A traceback or an internal-error exit anywhere means stop and fix.

## What must be in the script

1. Every example invocation from the current spec, with its fixture copied exactly. Compare output with the spec character by character: key order, prefixes, sorting, blank lines, trailing newline, exit code.
2. Every error type of the current part triggered once in JSON mode. Check the type string, the exit code from the row naming that type, and the command field, which names the subcommand typed even when a global flag or an option value was bad.
3. Each value syntax the spec allows on the command line, including what this part adds (new characters, sized forms, case variants, separators). Most misses come from a runtime value parser that still enforces the file grammar and raises the file error type.
4. New input or output formats exercised with the richest existing features (multi-bit values, nested expressions, all operators), not only the simplest example.
5. One success and one error command from every earlier part, kept from earlier runs. These are your regression guards; never delete them.
6. One mixed case per new flag: the new flag on an old command, an old feature through a new format.

## Reading the spec so the script is complete

Before coding, list every command, flag, error row (type, exit code, trigger, input origin), output field, and example. Each list item becomes a `run` line. Exit codes come from the row naming the type, not from category prose. Sentences with "still", "unchanged", "only", "exactly", or "from this part onward" describe cases too.

## Coding rules that keep the script green

- One error emitter, one exit-code table, one value parser, one value formatter, one data model. Extend them with parameters; never copy them per command.
- Convert every foreign exception (missing file, JSON decode error, failed int conversion, KeyError on a user-supplied name) into the spec's named type where the input origin is known. An uncaught exception is always wrong.
- Grep for hard-coded command or flag lists (usage text, dispatch, the error handler's notion of the current command) and update all of them when adding a command.
- Never name a variable `format`, `type`, `input`, `id`, `hash`, or after a helper you call, and never define a class with a builtin exception's name.
- Any output that must be deterministic gets an explicit sort; when the spec says "dependency order, ties by name", emit the smallest-named ready item each step.

## Finish

Run the whole script one last time and read it. In your summary, list the commands you ran. If something is unverified, name the exact item. Never write "did not run".
