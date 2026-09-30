---
name: cli-software
description: Change discipline for extending an existing command-line program part by part from a specification without breaking earlier behaviour. Use for every task that adds commands, flags, formats, or modes to a CLI codebase; it covers reading the existing code, extending shared pieces instead of copying them, and re-running earlier parts after every change.
---
# Extending a CLI without breaking it

Later parts of a spec are graded together with all earlier parts. One regression in a shared function costs more than the whole new feature is worth, and a crash on a new command's main path loses every test of that command. Treat every edit as something to verify by running.

## Before changing anything

1. Read the whole existing program, not only the area you plan to touch. Note the shared pieces: argument parsing and dispatch, the data model, the value parser, the value formatter, the error emitter and its exit table, and the writer for each output format.
2. Grep for every enumeration of commands, flags, operators, error types, and formats: usage strings, dicts, if/elif chains, and the error handler's idea of "which command is running". Write the list down. Each entry must be extended for the new part, especially the error handler, whose command field must name the new subcommand too.
3. Record current behaviour. Run one success and one error invocation from each earlier part and save the outputs under `scratch/before/`. Fixtures and outputs live in the workspace under `scratch/` (system temp directories may be blocked); delete the directory when done. Invoke with `python3 <entry> ...` or `.venv/bin/python <entry> ...` (the entry may not be executable); cache warnings on stderr are noise. Running these is part of the implementation work, not optional testing.

## While changing

- Extend the shared data model instead of adding a parallel one. A new input format must produce the same internal structures (names, ranges, expressions) as the existing one so every later stage works unchanged. Try it with the richest existing features (multi-bit values, nested expressions), not only the simplest example.
- New commands reuse the existing value parser, formatter, and error emitter. If a new command needs a different format, add a parameter; never copy the function. Two formatters drift apart within one part.
- New syntax for command-line values (extra characters, sized forms, case variants) belongs in the runtime value parser. Check whether that parser delegates to the file parser, which will still reject the new syntax and with the wrong error type; catch and re-raise the command-line type.
- Exit codes come from the spec row naming the error type; do not infer them from category prose.
- Defaults from earlier parts stay (default mode, radix, format) unless the spec changes them.
- Never introduce names that shadow builtins or helpers used elsewhere (`format`, `type`, `input`, `id`, `hash`, `filter`); one shadowed name can break every command at once. Never define an exception class with a builtin exception's name.
- Translate foreign exceptions (missing file, JSON decode, int conversion, KeyError on user names) into the spec's types where the origin is known; an internal-error exit is always a bug.
- Deterministic output gets an explicit sort. "Dependency order, ties by name" means emit the smallest-named ready item at each step.

## After changing

1. Rerun the saved invocations and diff against `scratch/before/`. Any difference must be required by the new part's spec; otherwise it is a regression to fix now.
2. Run every example from the new part's spec and compare stdout and `echo $?` with the text byte for byte (key order, prefixes, sorting, blank lines).
3. Trigger every new error type once in JSON mode: exit code, type name, command field.
4. Run mixed cases: the new flag on an old command, an old feature through a new format, a new command on a fixture from an old example.
5. Any traceback or internal-error exit is a bug; fix and rerun.
6. Read your own diff once. Look for enumerations you did not extend, copied functions, and new names that shadow old ones.

## Reading the new part

Before coding, list every command, flag, error row (type, exit code, trigger, input origin), output field, and example. Sentences beginning "From this part onward", "still", "unchanged", "now also", or "only" describe interactions with earlier parts; each is a mixed case to run.

## Finish

Delete `scratch/`. Report which earlier-part checks and which new examples you ran, and name anything left unverified. Never finish with "did not run".
