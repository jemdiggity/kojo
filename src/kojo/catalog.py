"""Read pinned public SCB metadata; never inspect solutions or grading tests."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path(__file__).resolve().parents[2]
REPO = BASE / "intermediate/vendor/scb-problems"


def data_root():
    """Where run output lives: $KOJO_DATA_DIR, else the main checkout, so it outlives any worktree."""
    override = os.environ.get("KOJO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    try:
        common = subprocess.check_output(
            ["git", "-C", str(BASE), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True, stderr=subprocess.DEVNULL).strip()
        if common.endswith("/.git"):
            return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        pass
    return BASE


DATA_ROOT = data_root()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config():
    return json.loads((BASE / "configs/gauntlet.json").read_text())


def metadata(name, repo=REPO):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("Invalid problem identifier")
    directory = repo / name
    text = (directory / "config.yaml").read_text()
    entry = re.search(r"^entry_file:\s*([\w.-]+)\s*$", text, re.M)
    if not entry:
        raise ValueError(f"Unsupported entry file: {name}")
    checkpoints = sorted(
        int(p.stem.split("_")[-1]) for p in directory.glob("checkpoint_*.md")
    )
    if checkpoints != list(range(1, len(checkpoints) + 1)):
        raise ValueError(f"Non-contiguous checkpoints: {name}")
    # Public files are the only assets used by the selected pinned catalog subset.
    if "static_assets:" in text and name != "file_backup":
        raise ValueError(f"Asset adapter required for {name}")
    return {
        "name": name,
        "entry_file": entry[1],
        "checkpoints": checkpoints,
        "assets": ["files"] if name == "file_backup" else [],
        "config_sha256": digest(directory / "config.yaml"),
        "spec_sha256": {
            str(n): digest(directory / f"checkpoint_{n}.md") for n in checkpoints
        },
    }


def shingles(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return {tuple(words[i : i + 5]) for i in range(max(0, len(words) - 4))}


def split_manifest(cfg, repo=REPO):
    groups = {split: cfg[split] for split in ["training", "validation", "test"]}
    flat = [n for names in groups.values() for n in names]
    if len(flat) != len(set(flat)):
        raise ValueError("Problem overlap across splits")
    problems = {name: metadata(name, repo) for name in flat}
    docs = [
        (split, name, n, shingles((repo / name / f"checkpoint_{n}.md").read_text()))
        for split, names in groups.items()
        for name in names
        for n in problems[name]["checkpoints"]
    ]
    pairs = []
    for i, (split, name, n, words) in enumerate(docs):
        for other, other_name, k, other_words in docs[i + 1 :]:
            if split == other:
                continue
            union = words | other_words
            similarity = len(words & other_words) / len(union) if union else 1.0
            pairs.append((similarity, f"{name}/{n}", f"{other_name}/{k}"))
            if similarity >= cfg["near_duplicate_threshold"]:
                raise ValueError(
                    f"Near-duplicate cross-split specs: {name}/{n}, {other_name}/{k}"
                )
    return {
        "problem_commit": cfg["problem_commit"],
        "splits": groups,
        "problems": problems,
        "checkpoint_counts": {
            s: sum(len(problems[n]["checkpoints"]) for n in names)
            for s, names in groups.items()
        },
        "duplicate_audit": {
            "method": "lowercase word 5-shingle Jaccard, comments removed",
            "threshold": cfg["near_duplicate_threshold"],
            "highest_cross_split_pairs": [
                list(pair) for pair in sorted(pairs, reverse=True)[:10]
            ],
        },
        "grouping_rationale": "Whole problem chains remain together. Configuration planning/migration problems share the test split. Search/query/ETL tasks share CLI conventions but have different languages, inputs and operations. code_search is development-only because its prior outcomes were inspected.",
    }


def check_repositories(cfg):
    for directory, commit in [
        (REPO, cfg["problem_commit"]),
        (BASE / "intermediate/vendor/slop-code-bench", cfg["runner_commit"]),
    ]:
        actual = subprocess.check_output(
            ["git", "-C", str(directory), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != commit:
            raise RuntimeError(f"Wrong repository revision: {directory.name}")
        dirty = subprocess.check_output(
            ["git", "-C", str(directory), "status", "--porcelain"], text=True
        )
        if dirty.strip():
            raise RuntimeError(f"Dirty repository: {directory.name}")


def protocol_digest(*, include_factory_instructions=True):
    paths = sorted((BASE / "src/kojo").glob("*.py"))
    paths += sorted(p for p in (BASE / "configs").iterdir() if p.is_file())
    paths += sorted((BASE / "skills/prompts").glob("*.md"))
    if include_factory_instructions:
        paths += sorted((BASE / "configs/factory-prompts").glob("*.md"))
    paths += [
        BASE / "scripts/kojo.py",
        BASE / "scripts/scb_entrypoint.py",
        BASE / "pyproject.toml",
        BASE / "uv.lock",
        BASE / ".python-version",
    ]
    paths = [p for p in paths if p.name != "gauntlet-approval.json"]
    return hashlib.sha256(
        json.dumps(
            {str(p.relative_to(BASE)): digest(p) for p in paths}, sort_keys=True
        ).encode()
    ).hexdigest()


def harness_digest():
    """Code/config identity excluding the independently versioned role prompts."""
    return protocol_digest(include_factory_instructions=False)


def factory_instruction_hashes(roles=('build', 'review', 'fix')):
    return {role: digest(BASE/'configs/factory-prompts'/f'{role}.md') for role in roles}
