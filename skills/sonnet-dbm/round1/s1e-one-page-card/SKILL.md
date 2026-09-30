---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software card

Hidden tests probe every bullet, and earlier tests are re-run at each checkpoint. Four rules.

**1. Enumerate, then execute.** Before coding, list in `NOTES.md` one line per requirement,
constraint, error bullet, and example in the spec. Implement down the list. Before
finishing, run a real command for every line: examples verbatim, plus one perturbation
each (option order, path location, empty value, quoted vs bare); every error bullet
triggered on purpose (check message, stderr, exit code); every undo path followed by
direct inspection of the state. Unrun lines are unimplemented.

**2. Ambiguous spec: implement the union.** Never pick one reading and never stop to ask
(the run is non-interactive). Accept options anywhere on the line; accept list and object
wrappers; accept string and structured encodings; accept files inside and outside the
expected directory; try the richer value interpretation, then fall back to the literal;
match the semantics of sibling fields with the same role. Where the spec explicitly says
error, error.

**3. Output records echo every identifying field.** Type, target and its container,
subject, from/to values, side-effect names. The spec's example is a floor, not a ceiling;
extra keys are free, missing keys fail. Reverse/undo records identify their target as
fully as forward ones.

**4. Persisted state is an external interface.** Write exactly the spec's schema (no
extra fields). Read liberally: tolerate records you did not write, extra or missing keys,
alternative shapes. Once per checkpoint, hand-craft a record literally from the spec text
and feed it to the tool. Unparseable state prints `Error: ...` and exits non-zero; no
traceback.

Also: usage errors come only from the argument parser; everything else is `Error: reason`
on stderr with a non-zero exit, never a broad catch-all. A missing target is an error, not
an auto-create. Never silently weaken a guaranteed property because a shortcut failed;
take the thorough path or fail.
