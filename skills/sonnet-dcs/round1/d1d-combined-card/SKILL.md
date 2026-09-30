---
name: service-spec
description: Use for any task whose prompt is a multi-part spec for a service, API, or CLI built up over successive parts (part 1, part 2, ... each adding or changing behavior). Guides literal reading of the spec and the choices to make where it is silent.
---

# Service from a multi-part spec: the card

Base: read every error/condition sentence literally; "returns X when Y" is exactly the set Y. When the spec is silent, choose the behavior that keeps earlier parts' worked examples passing unchanged. A guess that changes an earlier part's output is wrong by default.

1. Walk the empty state first. For each new workflow trace: (a) identity missing; (b) identity exists, value not set yet; (c) after first write. Not-found is only for the exact condition the spec names, normally (a). State (b) is a success response carrying an explicit typed "nothing yet" value, and any operation that "starts from the current value" proceeds from that sentinel.

2. Sentinels are type-stable. An integer-documented field is a JSON number in every response and accepted input, including "none yet"; if numbering starts at 1, the pre-first value is 0. Lists are `[]`, never null. If you are about to write null for a number, use the integer below the first real value instead. Accept the same sentinel on input that reads emit.

3. Conditional fields are omitted, never null. Add a key to a response dict only under the condition that makes it apply. A field a later part introduces appears only in the responses the spec shows it in; earlier parts' bodies stay byte-identical.

4. Accept liberally where the spec gives no rejection example. If a rule says a thing "must expose A and B" and no example shows a rejection for having only one, treat it as A and/or B. Reject only inputs the spec explicitly shows being rejected; silence means accept and proceed.

Before finishing a part: curl each new read in states (a)/(b)/(c); confirm only (a) is not-found, (b) is a success body, every number is a number, and no key is present-as-null. Re-run the part's worked examples and compare whole bodies. Throwaway commands only; no test files.
