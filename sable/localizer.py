"""Causal fault localization.

Given the latest (failing) build and the last good build, the localizer
asks: which inputs changed since the last good build, and which of those
does the failing target (transitively) read?  Changed inputs that the
failing target reads are ranked first; a major version bump scores
higher than a patch bump; a flaky failing target is always listed as an
alternative explanation, because a nondeterministic failure needs no
input change at all.

The ranking among several changed inputs is heuristic -- that is what
:mod:`sable.bisect` is for.  The localizer narrows the suspect set; the
bisector proves which change is responsible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .graph import BuildGraph
from .provenance import ProvenanceRecorder


@dataclass
class Suspect:
    kind: str  # "input" | "flake" | "unknown"
    input_name: str | None
    target: str | None
    old_version: str | None
    new_version: str | None
    score: float
    evidence: list[str] = field(default_factory=list)


def version_severity(old: str, new: str) -> float:
    """How big a change is this, 0..1?  Major bump > minor > patch;
    a content-hash change (no version numbers) scores in the middle."""

    def nums(version: str):
        return [int(x) for x in re.findall(r"\d+", version)]

    old_nums, new_nums = nums(old), nums(new)
    if not old_nums or not new_nums:
        return 0.5
    if old_nums[0] != new_nums[0]:
        return 1.0
    if len(old_nums) > 1 and len(new_nums) > 1 and old_nums[1] != new_nums[1]:
        return 0.6
    if old_nums != new_nums:
        return 0.3
    return 0.0


def localize(graph: BuildGraph, recorder: ProvenanceRecorder) -> list[Suspect]:
    if not recorder.builds:
        return []
    failing = recorder.builds[-1]
    if failing.ok:
        return []
    good = recorder.last_good_build()
    if good is None:
        return [
            Suspect(
                kind="unknown",
                input_name=None,
                target=failing.failed_target,
                old_version=None,
                new_version=None,
                score=0.0,
                evidence=[
                    "No successful build on record, so there is no "
                    "baseline to compare against."
                ],
            )
        ]

    changed = {
        name: (good.snapshot[name], failing.snapshot[name])
        for name in failing.snapshot
        if good.snapshot.get(name) != failing.snapshot[name]
    }
    reachable = (
        graph.transitive_inputs(failing.failed_target)
        if failing.failed_target
        else set()
    )

    # Recency of each input's latest change (for tie-breaking: among
    # equally suspicious inputs, the most recently changed is the most
    # likely culprit).
    latest_change_seq = {}
    for change in recorder.changes_since(good):
        latest_change_seq[change.input_name] = change.seq

    suspects: list[Suspect] = []
    for name, (old, new) in changed.items():
        score = 0.0
        evidence = [f"{name} changed {old} -> {new} since last good build"]
        if name in reachable:
            score += 2.0
            evidence.append(
                f"{name} is read (transitively) by failing target "
                f"{failing.failed_target}"
            )
        else:
            evidence.append(
                f"{name} is NOT read by failing target "
                f"{failing.failed_target}"
            )
        score += version_severity(old, new)
        suspects.append(
            Suspect(
                kind="input",
                input_name=name,
                target=failing.failed_target,
                old_version=old,
                new_version=new,
                score=score,
                evidence=evidence,
            )
        )

    target = (
        graph.targets.get(failing.failed_target)
        if failing.failed_target
        else None
    )
    if target is not None and target.flaky > 0:
        suspects.append(
            Suspect(
                kind="flake",
                input_name=None,
                target=target.name,
                old_version=None,
                new_version=None,
                score=0.5,
                evidence=[
                    f"{target.name} is flaky (p={target.flaky}); this "
                    "failure may be nondeterministic and need no input "
                    "change at all."
                ],
            )
        )
    if not changed and not any(s.kind == "flake" for s in suspects):
        suspects.append(
            Suspect(
                kind="flake",
                input_name=None,
                target=failing.failed_target,
                old_version=None,
                new_version=None,
                score=1.0,
                evidence=[
                    "No inputs changed since the last good build, so a "
                    "nondeterministic failure is the most likely cause."
                ],
            )
        )

    suspects.sort(
        key=lambda s: (-s.score, -latest_change_seq.get(s.input_name or "", 0))
    )
    return suspects
