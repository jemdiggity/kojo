"""Summarize frozen official evaluator reports; no inference or grading calls."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parents[1]
ROOT = BASE / "results/scb-code-search"


def prices(usage):
    uncached = usage["input_tokens"] - usage.get("cached_input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    output = usage["output_tokens"]
    return {
        "api_price_equivalent_usd": (uncached * 0.10 + cached * 0.01 + output * 0.50)
        / 1e6,
        "credit_equivalent": (uncached * 2.5 + cached * 0.25 + output * 12.5) / 1e6,
    }


def main():
    rows = []
    previous = {}
    observations = []
    for n in range(1, 6):
        path = ROOT / f"checkpoints/checkpoint_{n}"
        evaluation = json.loads((path / "grading/evaluation.json").read_text())
        assert not evaluation["infrastructure_failure"]
        runpath = path
        run = json.loads((runpath / "run.json").read_text())
        assert run["status"] == "complete"
        samples = json.loads((runpath / "quota.json").read_text())
        if n > 1:
            observations.extend(samples)
        states = {}
        current_pass = current_total = prior_pass = prior_total = 0
        for group, outcomes in evaluation["tests"].items():
            cp = group.split("-")[0]
            for state, names in outcomes.items():
                for name in names:
                    identity = cp + "/" + name
                    states[identity] = state
                    if cp == f"checkpoint_{n}":
                        current_total += 1
                        current_pass += state == "passed"
                    else:
                        prior_total += 1
                        prior_pass += state == "passed"
        counts = evaluation["total_counts"]
        passes = evaluation["pass_counts"]
        row = {
            "checkpoint": n,
            "current_passed": current_pass,
            "current_total": current_total,
            "prior_passed": prior_pass,
            "prior_total": prior_total,
            "all_tests_pass": all(s == "passed" for s in states.values()),
            "core_and_regression_pass": all(
                passes.get(k, 0) == counts.get(k, 0) for k in ["Core", "Regression"]
            ),
            "failed_tests": [k for k, v in states.items() if v == "failed"],
            "regressed_tests": [
                k
                for k, v in states.items()
                if previous.get(k) == "passed" and v == "failed"
            ],
            "recovered_tests": [
                k
                for k, v in states.items()
                if previous.get(k) == "failed" and v == "passed"
            ],
            "usage": run["usage"],
            "elapsed_seconds": run["elapsed_seconds"],
            "grading_seconds": evaluation["duration"],
            **prices(run["usage"]),
        }
        rows.append(row)
        previous = states
    old = json.loads((ROOT / "setup-failure.json").read_text())
    result = {
        "condition": "baseline",
        "model": "gpt-6-luna",
        "reasoning": "low",
        "checkpoint_1_reused": True,
        "rows": rows,
        "weekly_before_continuation": observations[0]["remaining_percent"],
        "weekly_after_continuation": observations[-1]["remaining_percent"],
        "weekly_floor": 78,
        "incremental_api_price_equivalent_usd": sum(
            r["api_price_equivalent_usd"] for r in rows[1:]
        ),
        "sequence_api_price_equivalent_usd": sum(
            r["api_price_equivalent_usd"] for r in rows
        ),
        "sequence_credit_equivalent": sum(r["credit_equivalent"] for r in rows),
        "prior_setup_failure": old["setup_failure"],
        "actual_cash_cost_usd": None,
        "skill_learning_cost": None,
        "break_even_tasks": None,
        "limitations": [
            "one dependent sequence, not independent tasks",
            "no learned skills or GEPA",
            "no repeats",
            "hosted model alias not weight snapshot",
            "orchestration tokens unavailable",
            "API prices are equivalents, not subscription charges",
        ],
    }
    successful = sum(r["all_tests_pass"] for r in rows)
    result["strict_successful_checkpoints"] = successful
    result["equivalent_usd_per_strict_successful_checkpoint"] = (
        result["sequence_api_price_equivalent_usd"] / successful if successful else None
    )
    (ROOT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# SCB code_search — five-checkpoint baseline",
        "",
        "All five checkpoints were attempted without Docker. Checkpoint 1 reuses the earlier Luna submission; checkpoints 2–5 are new fresh-conversation continuations. No hidden-test feedback or repairs were supplied between checkpoints.",
        "",
        "| Checkpoint | Current tests | Prior tests | All pass | Model seconds | Input / cached / output tokens |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for r in rows:
        u = r["usage"]
        prior = f"{r['prior_passed']}/{r['prior_total']}" if r["prior_total"] else "—"
        lines.append(
            f"| {r['checkpoint']} | {r['current_passed']}/{r['current_total']} | {prior} | {'Yes' if r['all_tests_pass'] else 'No'} | {r['elapsed_seconds']:.1f} | {u['input_tokens']} / {u.get('cached_input_tokens', 0)} / {u['output_tokens']} |"
        )
    lines += [
        "",
        f"Strict checkpoint success: **{successful}/5**. These are dependent milestones in one task, not five independent benchmark samples.",
        "",
        f"Four new sessions: **${result['incremental_api_price_equivalent_usd']:.5f}** at published API token rates. All five successful generation sessions: **${result['sequence_api_price_equivalent_usd']:.5f}** equivalent, **{result['sequence_credit_equivalent']:.6f}** Codex credits equivalent. The earlier failed sandbox setup adds ${old['setup_failure']['api_price_equivalent_usd']:.5f} equivalent. Actual marginal subscription cash cost and stronger-assistant orchestration tokens are unavailable.",
        "",
        f"Weekly account allowance: **{result['weekly_before_continuation']}% → {result['weekly_after_continuation']}%** during the continuation sequence; floor **78%**. Counter is rounded and account-wide.",
        "",
        "## Changes across checkpoints",
        "",
    ]
    for r in rows:
        lines.append(
            f"- Checkpoint {r['checkpoint']}: {len(r['failed_tests'])} failed tests; {len(r['regressed_tests'])} previously passing tests regressed; {len(r['recovered_tests'])} previously failing tests recovered."
        )
    lines += [
        "",
        "Exact failed/regressed/recovered test IDs are recorded in `results.json`, with full official reports under `checkpoints/checkpoint_N/grading`.",
        "",
        "This is a baseline harness pilot, not evidence of reusable skill learning. No skill updater, validation selection, paired skill conditions, or repetitions ran; learning cost and break-even are not estimable. The CLI is pinned, but the hosted model alias does not pin model weights. No SCB static-quality score is claimed for the extensionless entry file.",
        "",
        "[Published API rates](https://developers.openai.com/api/docs/models/gpt-6-luna). See `../../docs/reproduction.md` for reproduction and isolation details.",
    ]
    (ROOT / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
