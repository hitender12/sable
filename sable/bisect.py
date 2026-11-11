"""Automatic bisection over recent input changes.

Given the last good build and the ordered list of input changes since,
binary-search for the first change that breaks the build, replaying the
build at each midpoint with that prefix of changes applied.  Assumes
deterministic builds (internal replays use a fixed seed); if the build
passes even with all changes applied, the failure is nondeterministic
and bisection returns None.

The graph's live inputs are restored to their pre-bisect state when
bisection finishes.
"""

from __future__ import annotations

from .graph import BuildGraph
from .provenance import BuildRecord, Change, ProvenanceRecorder


def bisect_first_bad_change(
    graph: BuildGraph,
    recorder: ProvenanceRecorder,
    good_build: BuildRecord,
) -> Change | None:
    changes = recorder.changes_since(good_build)
    if not changes:
        return None

    current_snapshot = dict(recorder.builds[-1].snapshot)
    good_snapshot = dict(good_build.snapshot)

    def fails_with(upto: int) -> bool:
        snap = dict(good_snapshot)
        for change in changes[: upto + 1]:
            snap[change.input_name] = change.new_version
        graph.apply_snapshot(snap)
        try:
            return not graph.build(seed=0).ok
        finally:
            graph.apply_snapshot(current_snapshot)

    if not fails_with(len(changes) - 1):
        # Even with every change applied the build passes: the failure
        # is nondeterministic, not caused by any of these changes.
        return None

    lo, hi = 0, len(changes) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if fails_with(mid):
            hi = mid
        else:
            lo = mid + 1
    return changes[lo]
