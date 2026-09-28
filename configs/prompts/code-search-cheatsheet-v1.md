# These are mistakes you made in earlier code_search attempts

This is a task-specific cheat sheet based on observed failures. Treat it as concrete implementation advice. The public specifications still define the contract. Implement only the checkpoints currently supplied; some warnings concern features introduced later in the sequence.

## 1. You forgot the end offset on older match producers

You added fixes that access `match["_end"]`, but your exact/regex branches produced only `_offset`. Every exact/regex rule with a fix then crashed with `KeyError: '_end'`. Pattern-only smoke tests did not catch it.

Create one internal match constructor used by exact, regex, pattern and selector matching. Every record must contain integer absolute start and end offsets, including `_offset` and `_end` if you use those names. Assert `0 <= start <= end <= len(source)` and `source[start:end] == matched_text`. Do not let each branch invent a different record shape. Serialize public fields explicitly; private offsets must never appear in JSON output.

## 2. You confused coordinates with offsets, and repeated the mistake in comments

Python tokenize returns `(line, zero_based_column)` tuples. String slicing needs absolute integer offsets. You fixed this in pattern matching but left Python comment selectors passing tuples into slicing and position conversion.

Use the same conversion helper for every token and selector adapter. Build line-start offsets with line endings preserved, then convert with `line_starts[line - 1] + column`. Convert back to the specification's one-based Unicode positions only at the output boundary. Test a comment and a capture on a later line, including non-ASCII text.

## 3. Your captures consumed either too little or too much

These are cases your earlier heuristics missed:

- `print($X)` must capture `total + 2` from `print(total + 2)`, not just `total`.
- `return $X;` must consume a complete expression up to its syntactic boundary.
- `$FUNC($ARG)` must capture the function name separately, not consume the entire call as `$FUNC` and then look for another opening parenthesis.
- A placeholder representing an argument sequence must handle more than one argument; do not always stop at the first comma.
- `[$X?]` must match both `[]` and `[value]`. Optional means trying a zero-length alternative before the next literal, not only when the entire source ends.
- Repeated names must match equal text and report every occurrence's range.
- JavaScript backtick strings, including multiline ones, must remain intact. Handling only single and double quotes is insufficient.

Match with awareness of the remaining pattern and balanced syntax. A single greedy “atom or call chain” rule cannot handle all of these. Keep nested calls, binary expressions, absent optional values, argument lists and quoted delimiters in your local assertions.

## 4. You accepted selector names that did not actually work

An empty iterator is not a selector implementation. A regex returning only `function example() ` or `if (ready) ` is also wrong: the selector must return the complete specified syntax node, including its body when required.

Maintain a coverage table for the selector kinds in the current spec across supported languages. Do not silently accept a kind and return no matches because its branch is missing. Pay particular attention to comments, break/continue/throw, declarations and bodies, Go structs/interfaces, Java classes/methods, and Rust constructs when those languages are introduced. Recognize strings/comments before looking for braces or keywords. Regex fragments alone do not establish structural correctness. Verify exact node text and start/end positions.

## 5. You tested features separately but not their combinations

When fixes become available, exercise this matrix:

| Rule kind | Match only | Dry-run fix | Apply fix |
|---|---|---|---|
| exact | assert output | assert preview and unchanged file | assert output and changed file |
| regex | assert output | assert preview and unchanged file | assert output and changed file |
| pattern | assert captures | assert expanded template | assert replacement |
| selector | assert full node | assert preview | assert replacement |

Also check an empty replacement, multiple edits, overlapping/nested edits, ties resolved by rule ID, and a multiline replacement. Plan edits using original coordinates; apply accepted edits from right to left. Follow the public contract for which overlapping edit wins.

## 6. You called printed JSON “verification”

Create a small executable self-test inside src. Parse output and assert full expected objects, ordering, absence of private keys, exit codes, and file contents. Include a positive example per feature: zero exit with zero matches is a failure when a match is expected. Generate rules with `json.dumps` instead of fragile shell quoting. Do not put task files in global /tmp or inspect other directories.

## 7. You stopped with known failures and unused time

You previously reported missing selectors or unmatched public examples and then finished well before the execution limit. Do not repeat that. Use your remaining budget to investigate a failing positive example, fix the cause, and rerun the assertions after the final edit. If you cannot complete the contract within the limit, state the exact remaining limitation rather than calling the feature implemented. Do not claim checks you did not execute successfully.
