"""Provenance recorder: every build and every input change, in order.

Causal localization is only possible because we know exactly what the
inputs were at the last good build and what changed since.  The recorder
is the memory of the system.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import BuildResult


@dataclass
class BuildRecord:
    seq: int
    snapshot: dict[str, str]  # input name -> version at build time
    ok: bool
    failed_target: str | None
    per_target: dict[str, bool]


@dataclass
class Change:
    seq: int
    input_name: str
    old_version: str
    new_version: str


@dataclass
class ProvenanceRecorder:
    builds: list[BuildRecord] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    _seq: int = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def record_build(
        self, result: BuildResult, snapshot: dict[str, str]
    ) -> BuildRecord:
        record = BuildRecord(
            seq=self._next_seq(),
            snapshot=dict(snapshot),
            ok=result.ok,
            failed_target=result.failed_target,
            per_target=dict(result.per_target),
        )
        self.builds.append(record)
        return record

    def record_change(
        self, input_name: str, old_version: str, new_version: str
    ) -> Change:
        change = Change(
            seq=self._next_seq(),
            input_name=input_name,
            old_version=old_version,
            new_version=new_version,
        )
        self.changes.append(change)
        return change

    def last_good_build(self) -> BuildRecord | None:
        for record in reversed(self.builds):
            if record.ok:
                return record
        return None

    def changes_since(self, build: BuildRecord) -> list[Change]:
        return [c for c in self.changes if c.seq > build.seq]
