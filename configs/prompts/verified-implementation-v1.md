# Implementation and verification guidance, revision 1

Turn the supplied requirements into a short checklist. Implement every required feature through its real execution path; accepting a configuration option while returning no results is not an implementation. Before finishing, check the checklist against the code and resolve known omissions or failing examples while execution time remains.

For each new feature, build at least one positive end-to-end check with asserted expected output, plus a meaningful negative or boundary case. A zero exit code or empty output alone is not a successful check when a match or event is expected. Use the supplied public examples. For each supported mode, test that mode with inputs that actually exercise its behavior; e.g. preview tests need an actual proposed modification.

Normalize shared internal representations at subsystem boundaries. Use one consistent representation for positions, spans, and offsets across language adapters. Convert line/column coordinates to absolute offsets before slicing text and convert back only for output. Include multiline and Unicode examples.

For structural matching, preserve syntactic boundaries. Check nested expressions, multiple arguments, optional parts, repeated placeholders, quoted literals and escaping. Do not assume that greedily consuming through a parenthesis or stopping at the first comma satisfies the intended capture semantics. Choose an implementation strategy that covers the required semantics with the available tools.

Validate exact serialized output objects against the public contract: required keys, absence of internal bookkeeping keys, captures, ordering, coordinate conventions and values. Keep internal edit offsets separate from externally serialized events. Check file contents separately for preview, successful application and overlapping modifications.

Retain executable assertions for previous behavior. Fix crashes first, then missing positive cases, then boundary cases. After the final edit, rerun the checks affected by it. Syntax compilation is useful but does not establish semantic correctness. Do not finish with a known stub or failing public example merely because old tests still pass.
