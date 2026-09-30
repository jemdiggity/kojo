Act as an independent test author. You are given the public specifications of a command line program, checkpoint 1 up to the current one, and a `suite/` directory in your working directory that holds the tests written for earlier checkpoints (it may be empty). There is no program code in your workspace and you must not look for it, ask for it or guess how it is built. Write tests from the specifications alone. Do not implement the program.

Extend `suite/` so that it checks the current specification and, through the earlier cases, everything before it.

Suite format. `suite/cases.json` is a JSON array of cases:

    {"name": "unique short name", "source": "example" | "postcondition" | "property" | "regression",
     "argv": ["eval", "adder.circ", "--set", "a=1"],      # arguments only; the harness supplies the program
     "files": {"adder.circ": "file text"},                 # created in a fresh temp directory the program runs in
     "stdin": null,
     "expect": {"exit": 0, "stdout": "exact text", "stdout_regex": "...", "stdout_contains": ["..."],
                "stdout_json": {"ok": true},               # every listed field must match (subset match)
                "files": {"out.txt": {"regex": "...", "not_regex": "...", "equals": "..."}}}}

Every `expect` key is optional; use only what the specification states. For checks that need logic (running the program several times, comparing two runs, parsing output), add a script case `{"name": "...", "script": "checks/name.py", "args": []}`. The script runs with Python in a temp directory; the environment variable `ENTRY` holds the program's command as a shell-quotable string and `ENTRY_ARGV_JSON` the same as a JSON list. It passes by exiting 0 and fails by raising or exiting non-zero; print a short reason first, as it is shown to the developer.

Write the following.
1. Every example in the specifications, verbatim, as an `example` case (fixture files from the specification go in `files`). Copy the expected output exactly; when the specification elides part of an output with `...`, use `stdout_json` or `stdout_regex` for the parts it does state.
2. Every numbered postcondition or guarantee, and every rule stated as "must", "always", "never", or "ties are broken by", as `postcondition` cases or scripts. Use adversarial inputs: boundaries, empty and maximal sizes, ties, duplicates, ordering rules, error labelling for each error type, padding and formatting rules. For programs that process circuits, netlists, graphs, expressions or similar structured inputs, include a case in which the construct under test is reached only THROUGH AN INTERMEDIATE NAMED SIGNAL, WIRE OR VARIABLE (several hops away), not directly from the inputs.
3. When a later specification changes or replaces earlier behavior, edit or remove the old cases that it makes wrong. Keep cases for behavior that still stands as `regression` cases so that earlier features keep working.

Keep expectations to what the specifications state. If the specification does not say, do not assert it. Prefer many small, independent cases to few large ones; a wrong test misleads the developer, so re-read the specification wherever you are unsure. Do not read or ask for any code. End your final response with a short list of what you added, changed and removed.
