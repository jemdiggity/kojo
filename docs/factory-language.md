# Factory language

A factory says which model does each stage of a checkpoint and how the stages
flow, including loops with a limit. It lives in `configs/factories/NAME.factory`
and is run per checkpoint, after which the resulting code carries into the next
checkpoint as usual.

```
# luna builds -> opus refactors -> review loop (max 5) -> qa; failed qa goes back to build (max 2)
build    = luna6
refactor = opus55:high
review   = opus55:high
fix      = luna6
qa       = sonnet55

build -> refactor -> review
review -[fail, max 5]-> fix -> review
review -> qa
qa -[fail, max 2]-> build
qa -[pass]-> done
```

## Stages

`NAME = [KIND] MODEL[:EFFORT]`. `MODEL` is a suite alias (`luna6`, `astra6`,
`sonnet55`, `opus55`, ...; run `scripts/scb_suite.sh -h` for the list) or an exact
provider ID. `EFFORT` defaults to `medium` and must suit the model's provider.
`KIND` defaults to the stage name, so a stage called `review` is a review.

| Kind | Does | Prompt |
|---|---|---|
| `build` | Stock SCB prompt for the checkpoint, in the shared builder workspace. | upstream |
| `revise` | Reviews its own inherited code against the specs and fixes it. | `configs/factory-prompts/revise.md` |
| `refactor` | Restructures without changing behavior. | `refactor.md` |
| `fix` | Follows up on the review or qa report that precedes it. | `fix.md` |
| `review` | Reads a disposable copy and reports; ends with a verdict. | `review.md` |
| `qa` | Runs the program against the specs in a disposable copy; ends with a verdict. | `qa.md` |

`build`, `revise`, `refactor` and `fix` change code; their result carries forward
in the persistent builder workspace. `review` and `qa` never change it. Their
answer goes to the next code-changing stage as feedback, and their final
`VERDICT: PASS` or `VERDICT: FAIL` line (appended to the request by the harness;
a missing line counts as a fail) selects the next arrow.

A `build` stage re-entered through a loop receives the stock prompt plus the
preceding report as appended feedback; a first build never does. Every stage runs
in a fresh CLI conversation.

## Flow

`a -> b -> c` chains stages. An arrow may carry options: `-[fail]->`, `-[pass]->`,
`-[max N]->`, or a mix such as `-[fail, max 5]->`. `done` ends the checkpoint.

* From a stage, the **first** arrow (in file order) whose condition holds and whose
  `max` is not spent is taken. `pass`/`fail` conditions need a `review` or `qa` source.
* `max N` counts uses per checkpoint. If nothing is eligible, the checkpoint's
  factory ends with the current code.
* The first stage of the first flow line must be a `build`. Every stage must be
  reachable, a `fix` must follow a `review`/`qa`, and every loop needs a `max`,
  so a factory always terminates. Errors name the file and line.

In the example, `review -[fail, max 5]-> fix` allows at most five fix passes;
a review that still fails afterwards falls through to `review -> qa`.

## Running

```sh
scripts/scb_suite.sh --id try-01 --problems circuit_eval \
  --factory luna-review-astra luna-opus-review-loop luna-opus-qa --parallel all --audit
```

`--factory` replaces `--models` and `--efforts`; each factory is one run per
problem (and per skill set), and `--parallel` treats factories as it treats
models. Or run one directly: `python -m kojo.factory run --run-id ID --factory NAME
--problem circuit_eval`.

Each run records `factory.txt`, the parsed factory and its hash in `manifest.json`,
the worst-case `max_sessions`, and `flow-trace.json` (stage, verdict and next stage
per session). A stage's first visit in a checkpoint writes to
`STAGE/checkpoint_N`; later visits to `STAGE/checkpoint_N-2`, `-3`, and so on.
Every code-changing session is graded after all model calls finish.
