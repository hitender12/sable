"""Build graph: targets, inputs, and the simulated build itself.

A build is deterministic given its inputs, unless a target is marked
flaky.  That determinism is what makes causal localization and bisection
possible: the same input snapshot always produces the same outcome, so a
failure can be attributed to the inputs that changed since the last good
build.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Input:
    """One build input: a dependency version, a source hash, a config
    value, a toolchain version -- anything the build reads."""

    name: str
    version: str
    kind: str = "dependency"  # dependency | source | config | toolchain


@dataclass
class Target:
    """One build target.

    ``rule`` receives the target's inputs (name -> Input) and returns
    True when the target builds.  ``flaky`` is the per-run probability
    of a nondeterministic failure, independent of inputs.
    """

    name: str
    deps: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    rule: Callable[[dict[str, Input]], bool] = lambda inputs: True
    flaky: float = 0.0


@dataclass
class BuildResult:
    ok: bool
    failed_target: str | None  # first target that actually failed
    per_target: dict[str, bool]
    log: list[str]


class BuildGraph:
    def __init__(self, targets: list[Target], inputs: list[Input]):
        self.targets = {t.name: t for t in targets}
        self.inputs = {i.name: i for i in inputs}

    # -- structure ------------------------------------------------------
    def topo_order(self) -> list[str]:
        """Topological order of targets; raises ValueError on a cycle."""
        order: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str):
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"dependency cycle involving {name}")
            visiting.add(name)
            for dep in self.targets[name].deps:
                if dep not in self.targets:
                    raise ValueError(f"unknown dependency {dep!r}")
                visit(dep)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for name in self.targets:
            visit(name)
        return order

    def transitive_inputs(self, target_name: str) -> set[str]:
        """All inputs read by a target or any of its transitive deps."""
        seen: set[str] = set()
        stack = [target_name]
        while stack:
            name = stack.pop()
            target = self.targets[name]
            seen.update(target.inputs)
            stack.extend(d for d in target.deps if d not in seen)
        return seen

    # -- execution ------------------------------------------------------
    def build(self, seed: int | None = None) -> BuildResult:
        rng = random.Random(seed)
        per_target: dict[str, bool] = {}
        failed: str | None = None
        log: list[str] = []
        for name in self.topo_order():
            target = self.targets[name]
            if any(not per_target[d] for d in target.deps):
                per_target[name] = False
                log.append(f"{name}: SKIPPED (dependency failed)")
                continue
            inputs = {n: self.inputs[n] for n in target.inputs}
            if target.flaky > 0 and rng.random() < target.flaky:
                per_target[name] = False
                log.append(f"{name}: FAILED (flaky)")
            elif not target.rule(inputs):
                per_target[name] = False
                log.append(f"{name}: FAILED (rule)")
            else:
                per_target[name] = True
                log.append(f"{name}: ok")
            if not per_target[name] and failed is None:
                failed = name
        return BuildResult(
            ok=failed is None,
            failed_target=failed,
            per_target=per_target,
            log=log,
        )

    # -- snapshots ------------------------------------------------------
    def snapshot(self) -> dict[str, str]:
        return {name: inp.version for name, inp in self.inputs.items()}

    def apply_snapshot(self, snap: dict[str, str]) -> None:
        for name, version in snap.items():
            if name in self.inputs:
                self.inputs[name].version = version
