---
name: cli-software
description: Use for any task whose prompt is a multi-part specification for a CLI tool or program (numbered requirements, commands, options, output formats, error handling, examples), especially when built incrementally across several checkpoints and graded by hidden tests. Load before reading the spec in detail.
---

# CLI software: enumerate, then execute

You are building against a written spec and hidden tests. Most lost points come from
spec bullets that were read but never exercised. Work in this order.

## 1. Read the spec, then write the checklist (before any code)

Create or update `NOTES.md` in the workspace. Under a `## Checklist` heading, write one
line per obligation, in the spec's own words, for **every**:

- requirement / feature bullet
- constraint, validation rule, and "must"/"must not" sentence
- error-handling bullet (each is a separate line: trigger -> expected message/exit code)
- example command in the spec (copy the command verbatim as its own line)
- output field or event shape mentioned anywhere

Do not summarize or merge lines. If the spec has 30 bullets, the checklist has 30+ lines.
Later checkpoints: append the new section's lines; keep old ones (earlier tests are re-run).

## 2. Implement against the checklist

Go down the list. When a line is implemented, mark it `[x]`. When a line reveals an
ambiguity, implement it so that every plausible reading is accepted, note the decision
inline, and move on. Do not stop to ask; the run is non-interactive.

## 3. Execute every line before finishing

Verification is not "run the happy path once". For each checklist line, run at least one
real command that exercises it and observe the actual output:

- **Examples: run verbatim.** Copy the spec's example command exactly (same option order,
  same argument shapes, same file layout) and compare your output to the expected output
  character by character where the spec shows it.
- **Then run one perturbation per example.** Change exactly one thing and confirm it still
  works: options in a different position on the command line, a different working
  directory or path style (relative/absolute, inside/outside a directory), a null/empty/
  missing optional value, a quoted string vs a bare word or number, and an equivalent
  spelling the spec would reasonably accept.
- **Error bullets: trigger each one.** Craft the bad input, run it, and check the message,
  the stream (stderr vs stdout), and the exit code. An error path you never triggered
  counts as unimplemented.
- **Undo/reverse/cleanup paths:** apply, reverse, then inspect the resulting state directly
  (query it, list it, cat it) rather than trusting your own success message.

Record results as a short line under each checklist item (`ok`, or what broke). A line you
cannot run is a red flag; say why in the notes and reconsider the implementation.

## 4. Finish

Before your final message, re-scan the checklist for any unmarked line and any line marked
without a run. Fix those first. Then state, briefly, what you verified and what remains
untested. Never claim coverage you did not execute.

## Habits that cost points (avoid)

- Reading a section header like "Constraints" and treating it as background text. Every
  bullet under it is a test.
- Testing only inputs your own code generated earlier. Hand-craft inputs literally from the
  spec's description too.
- Catching broad exceptions around the command entry point and reporting them as usage
  errors. Usage errors come only from argument parsing; everything else is an explicit
  `Error:` message on stderr with a non-zero exit.
- Silently narrowing a guaranteed property when a shortcut fails. If the cheap path cannot
  preserve the property, use the thorough path or report an error.
- Treating the spec's example output as the full set of fields. Examples are a floor:
  include every identifying field the operation carries.
