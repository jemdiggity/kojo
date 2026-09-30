Act as an independent test author focused on guarantees. You are given the public specifications of a command line program, checkpoint 1 up to the current one, and a `suite/` directory in your working directory holding the tests written so far (it may be empty). There is no program code in your workspace and you must not look for it or guess how it is built. Write tests from the specifications alone.

Suite format. `suite/cases.json` is a JSON array of cases:

    {"name": "unique short name", "source": "postcondition" | "property" | "regression",
     "argv": ["eval", "adder.circ", "--set", "a=1"],      # arguments only; the harness supplies the program
     "files": {"adder.circ": "file text"},                 # created in a fresh temp directory the program runs in
     "stdin": null,
     "expect": {"exit": 0, "stdout": "exact text", "stdout_regex": "...", "stdout_contains": ["..."],
                "stdout_json": {"ok": true},               # every listed field must match (subset match)
                "files": {"out.txt": {"regex": "...", "not_regex": "...", "equals": "..."}}}}

Every `expect` key is optional; use only what the specification states. For checks that need logic, add a script case `{"name": "...", "script": "checks/name.py", "args": []}`; the script runs with Python in a temp directory, gets the program's command in the environment variable `ENTRY` (shell-quotable string) and `ENTRY_ARGV_JSON` (JSON list), passes by exiting 0 and fails by raising or exiting non-zero, and should print a short reason first.

Concentrate on the numbered guarantees, postconditions and rules of the specifications (anything phrased as "must", "always", "never", "guarantee", "ties are broken by", ordering, formatting, padding and error-labelling rules). For each one write at least one adversarial case that would catch a plausible mistake, using boundaries, ties, duplicates, empty inputs and the largest allowed sizes. For structured inputs such as circuits, netlists or graphs, include cases in which the construct under test is reached only THROUGH AN INTERMEDIATE NAMED SIGNAL, WIRE OR VARIABLE, several hops away from the inputs.

Also write differential fuzz scripts in `suite/fuzz/NAME.py`. A fuzz script compares two independent implementations of the same specification: the environment variables `ENTRY_A` and `ENTRY_B` hold the two programs' commands (shell-quotable strings; `ENTRY_A_ARGV_JSON` and `ENTRY_B_ARGV_JSON` hold JSON lists). The script generates many small random valid inputs from a fixed seed, runs both programs on each, and exits 0 when their observable results agree on everything the specification defines (compare exit codes and the stdout the specification fixes; ignore what it leaves open, such as error message wording), or prints the smallest disagreeing input and both outputs and exits 1. Keep each script under 20 seconds.

When a later specification changes earlier behavior, edit or remove the old cases that it makes wrong. Keep expectations to what the specifications state. Do not read or ask for any code. End your final response with a short list of what you added, changed and removed.
