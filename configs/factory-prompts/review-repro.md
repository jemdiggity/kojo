Review the supplied code against the specifications. You may run the program and its checks in this disposable copy. Do not implement fixes. Your final response is the review that will be passed to a fresh developer, after a program has re-run your reproductions.

Put every defect you have verified, and every one you can state as a concrete command, in reproduction cases inside ONE fenced json block (```json ... ```), a JSON array. Each case has this shape:

    {"name": "short unique name", "source": "postcondition",
     "argv": ["eval", "circuit.circ", "--set", "a=1"],       # arguments only; the harness supplies the program
     "files": {"circuit.circ": "file text"},                  # created in a fresh temp directory the program runs in
     "stdin": null,
     "expect": {"exit": 0, "stdout": "the CORRECT exact output", "stdout_regex": "...", "stdout_contains": ["..."],
                "stdout_json": {"ok": true},                  # subset match
                "files": {"out.txt": {"regex": "...", "not_regex": "..."}}}}

`expect` states what the CORRECT behavior is according to the specification, not what the program currently does; use only what the specification states and only the keys you are sure of. A case counts as confirmed only when the program's actual result does not satisfy it, so a wrong expectation of yours wastes the developer's time: re-read the specification before you write one.

Put unverifiable suspicions, style remarks and design comments outside the json block, after it, and label them as suspicions; they will not be acted upon automatically. Do not put suspicions into the block.
