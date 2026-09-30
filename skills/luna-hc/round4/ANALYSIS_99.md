# What actually failed in the ~99% circuit_eval runs (luna6:low)

Runs analysed (final = checkpoint_8 submission, official tests re-run): r3b 99.4 (10 failing at cp8), r3e 99.4 (10),
r2d 99.6 (6), r2c 99.3 (10), r2e 99.1 (9) = 45 failing test instances, 18 distinct root causes.
Every failure, once introduced, was carried forward unchanged to cp8. Evidence: `.tmp/analysis/<run>/`.

## Distinct failures (id: what, runs, class)
- F1 Absorption only recognised inline, not through a named wire (`t=AND(a,b); y=OR(a,t)`) - all 5 runs, 10 instances. Spec: "Absorption laws are applied where applicable". Each skill said to test a violating input "through an intermediate named signal"; none did. (algorithmic + untested)
- F2 `--fanin-limit` ignored unless `area` pipeline / `--passes fanin` - r3b, r2e. Spec lists fanin as a numbered postcondition and shows an example on the default pipeline. (ambiguous pass table, wrong reading)
- F3 Fanin decomposed then re-flattened by own unconditional canonicaliser - r2d. (self-inflicted, untested)
- F4 3-valued MUX with X select all-X instead of per-bit - r2c (4). Builder ran the spec example, saw mismatch, ended "stopping here with that issue unresolved".
- F5 2-valued REDUCE_AND compared with 1-bit result mask - r3b, r2d. Never fed an all-ones vector.
- F6 hex/decimal command-line values wrong/crash in `--mode 3val` - r3b, r2e (new mode x existing value syntax; r3b's attempt died on shell quoting).
- F7 `--version --json` printed plain text after cp3 dispatcher rewrite - r3e. The regress/ suite showed the diff in four sessions and each time it was dismissed.
- F8 `--allow-extra` broke at cp4 - r3e; suite never got a case after cp1.
- F9 BENCH reader began accepting literal operands at cp8 - r3e; induced by the skill's "fix the reader when the spec allows" round-trip rule (cp5 spec forbids literals).
- F10 BENCH loader counts OUTPUT names as wires (`wires_count` 3 vs 1) - r3e, r2c (spec ambiguity).
- F11 Cone emits level order instead of "ties by name, smallest ready first" - r3e (had the rule in its skill, ignored), r2e.
- F12 Second formatter for truth-table JSON without 0b/0x prefixes - r3e (3), r2c (1), despite "one formatter" rule.
- F13 XOR duplicate-arg cancellation crash (tuple + int) - r3b. F14 DCE leaves `wire` declaration (own reader rejects output) - r3b, r2c.
- F15 opt output drops unused inputs - r3b. F16 literal `X` in file -> exit 3 not 2 after cp4 tokenizer change - r2d.
- F17 BENCH export of vector circuit gives WidthMismatch (3) not UnsupportedFeature (1) - r2c. F18 `unhashable list` crash on nested same-op expressions - r2e (3).

## Could the skill's own instructions have caught it? (26 run/failure pairs)
not followed 18, not covered 6, followed-but-insufficient 2, skill rule itself wrong 1 (F9).
Cp8 sessions were short: r2d 10 commands/175 s, r2c 7/162 s, r2e 8/155 s (skill unread in r2e cp2/3/5/6/8 and r3b cp8); r3b spent ~35 of 50 commands on one rename option with a one-gate fixture.

## Task-specific vs transferable
~60% (27/45): "a numbered output guarantee or spec example was never run on an input that could violate it" - the skills already said so; nothing enforced it.
~15% regressions (F7, F8, F16, F12): a permanent suite only helps if extended each checkpoint and its diff is a hard stop.
~15% genuine spec ambiguity (F10, F11, F4, F2 reading, F6 in r2e).  1 skill-induced (F9).

## Levers that could still help
1. Make the postcondition run a required artifact (scratch/post.sh + violating fixtures; paste output in final message).
2. Say "substitute each wire's definition before matching" for absorption/CSE/duplicate checks.
3. Reductions/comparisons: one input giving 1 and one giving 0.
4. Non-empty regress diff = hard stop; every fixed bug and every checklist row becomes a suite line.
5. Enumerate value syntaxes x modes.
6. Qualify "fix the reader": only if the CURRENT spec of that format allows the construct; forbidden-earlier stays forbidden.
Residue likely irreducible by a skill: spec-ambiguity reads (~9 instances) and sessions that never open SKILL.md.

## Corrections to round3/ANALYSIS.md
r2d's fanin mechanism (decomposed then undone by its own rewrite, not "not selected"); r3e's suite did show the `--version --json` regression (dismissed).
