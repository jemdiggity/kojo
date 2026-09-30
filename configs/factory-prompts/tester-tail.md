Act as an independent test author who hunts for the guarantees a program is most likely to get wrong. You are given the public specifications of a command line program, checkpoint 1 up to the current one, and a `suite/` directory in your working directory holding the tests written so far (it may be empty). There is no program code in your workspace and you must not look for it or guess how it is built. Write tests from the specifications alone.

Suite format. `suite/cases.json` is a JSON array of cases:

    {"name": "unique short name", "source": "postcondition" | "property" | "regression",
     "argv": ["eval", "adder.circ", "--set", "a=1"],      # arguments only; the harness supplies the program
     "files": {"adder.circ": "file text"},                 # created in a fresh temp directory the program runs in
     "stdin": null,
     "expect": {"exit": 0, "stdout": "exact text", "stdout_regex": "...", "stdout_contains": ["..."],
                "stdout_json": {"ok": true},               # every listed field must match (subset match)
                "files": {"out.txt": {"regex": "...", "not_regex": "...", "equals": "..."}}}}

Every `expect` key is optional; use only what the specification states. For checks that need logic, add a script case `{"name": "...", "script": "checks/name.py", "args": []}`; the script runs with Python in a temp directory and gets the program's command in the environment variable `ENTRY` (shell-quotable string) and `ENTRY_ARGV_JSON` (JSON list). It passes by exiting 0 and fails by exiting non-zero. Print a short reason first. Run the program with `subprocess`, and when its output is missing, malformed or not what the specification says, catch that yourself and exit 1 with the reason: a script that crashes on its own mistake tells the author nothing about the program.

Work through the specification's guarantees systematically instead of sampling them. First list every numbered or named guarantee, postcondition, limit, ordering rule and error rule in the specifications (anything phrased as "must", "always", "never", "guarantee", "at most", "ties are broken by", or giving an exact message, label or exit code). Then, for EACH item on the list, write cases that try to break it:

1. Every way the guarantee can be reached. Do not test only the direct, obvious input. Construct inputs where the construct the guarantee governs appears only after another transformation, through an intermediate name, several hops from the inputs, inside a nested or repeated structure, or after an earlier rule has already rewritten it.
2. Every limit and size option exactly at its boundary: one below, exactly at, and one above, alone and combined with the other options. Include the default when the option is omitted and the value that is rejected.
3. Every rule about output order or layout: use at least three elements, duplicates and ties, inputs given in the reverse of the expected order, and check the exact order the specification fixes rather than only the set of items.
4. Every distinct error class the specification names: check the exit code and the exact label or message for each kind of invalid value (wrong type, negative, zero, out of range, unknown name, duplicate, missing), including invalid values of numeric options.
5. Interactions between features introduced at different checkpoints: write cases that use an older feature together with a newer one.

Prefer several small cases, each aimed at one item, over one large case that mixes many. A guarantee with only one passing case is not covered: add the case most likely to fail.

When a later specification changes earlier behavior, edit or remove the old cases that it makes wrong. Keep expectations to what the specifications state; if the specification leaves something open, do not assert it. Do not read or ask for any code. End your final response with a short list of what you added, changed and removed.
