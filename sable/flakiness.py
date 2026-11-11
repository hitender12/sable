"""Flakiness scorer: how nondeterministic is each target?

A target is scored by running the build many times with fixed inputs
and different seeds.  Any variance in outcome with identical inputs is
flakiness by definition.  A target that fails every time is *broken*,
not flaky, so its flake score is 0 even though its failure rate is 1.

Scores are only meaningful from a baseline where the target's
dependencies pass -- otherwise downstream targets inherit their
dependencies' failures.
"""

from __future__ import annotations

from .graph import BuildGraph


def score_target(
    graph: BuildGraph, target_name: str, runs: int = 20, base_seed: int = 0
) -> dict:
    outcomes = []
    for i in range(runs):
        result = graph.build(seed=base_seed + i)
        outcomes.append(result.per_target.get(target_name, False))
    failure_rate = 1.0 - sum(outcomes) / len(outcomes)
    nondeterministic = any(outcomes) and not all(outcomes)
    return {
        "target": target_name,
        "runs": runs,
        "failure_rate": round(failure_rate, 3),
        "flake_score": round(failure_rate, 3) if nondeterministic else 0.0,
        "nondeterministic": nondeterministic,
    }


def score_all(
    graph: BuildGraph, runs: int = 20, base_seed: int = 0
) -> dict[str, dict]:
    return {
        name: score_target(graph, name, runs=runs, base_seed=base_seed)
        for name in graph.targets
    }
