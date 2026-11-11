"""Verifier: prove a patch fixes the build by rebuilding with it.

The patch is applied to a deep copy of the graph, never to the live
graph, and the build is re-run.  A patch is accepted only if the
rebuild passes.  A wrong patch -- rolling back an innocent input --
leaves the real fault in place, so the rebuild still fails and the
patch is rejected.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from .graph import BuildGraph
from .patcher import Patch


@dataclass
class VerificationResult:
    fixed: bool
    failed_target: str | None
    log: list[str]


def verify(graph: BuildGraph, patch: Patch, seed: int = 0) -> VerificationResult:
    candidate = copy.deepcopy(graph)
    if patch.input_name in candidate.inputs:
        candidate.inputs[patch.input_name].version = patch.to_version
    result = candidate.build(seed=seed)
    return VerificationResult(
        fixed=result.ok,
        failed_target=result.failed_target,
        log=result.log,
    )
