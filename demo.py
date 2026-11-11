"""Demo: a bad dependency version breaks the build, and Sable finds it,
bisects it, patches it, and verifies the fix.

Run with:  python demo.py
"""

from sable import (
    Patch,
    bisect_first_bad_change,
    localize,
    make_demo_graph,
    propose_patch,
    score_all,
    verify,
)
from sable.provenance import ProvenanceRecorder


def run_build(recorder, graph, note):
    result = graph.build(seed=0)
    recorder.record_build(result, graph.snapshot())
    print(f"\n[{note}] build {'PASSED' if result.ok else 'FAILED'}")
    for line in result.log:
        print(f"    {line}")
    return result


def main():
    print("Sable demo: self-healing build graph")
    graph = make_demo_graph()
    recorder = ProvenanceRecorder()

    # 1. Baseline: everything good.
    run_build(recorder, graph, "baseline, lib 1.9")

    # 2. Two innocent changes, both fine.
    graph.inputs["compiler"].version = "gcc-13"
    recorder.record_change("compiler", "gcc-12", "gcc-13")
    run_build(recorder, graph, "compiler gcc-12 -> gcc-13 (innocent)")
    graph.inputs["config"].version = "fast-lto"
    recorder.record_change("config", "fast", "fast-lto")
    run_build(recorder, graph, "config fast -> fast-lto (innocent)")

    # 3. The injected fault: lib 1.9 -> 2.0 (breaking API change).
    graph.inputs["lib"].version = "2.0"
    recorder.record_change("lib", "1.9", "2.0")
    run_build(recorder, graph, "lib 1.9 -> 2.0 (INJECTED FAULT)")

    # 4. Localize: which input explains the failure?
    suspects = localize(graph, recorder)
    print("\n[localize] ranked suspects:")
    for s in suspects:
        print(f"    {s.kind} {s.input_name or s.target} score={s.score:.1f}")
        for e in s.evidence:
            print(f"      - {e}")
    top = suspects[0]
    assert top.input_name == "lib", "expected lib as top suspect"

    # 5. Bisect: prove which change first broke the build. Bisect from
    # the baseline build, so the two innocent changes are candidates too.
    baseline = recorder.builds[0]
    culprit = bisect_first_bad_change(graph, recorder, baseline)
    print(
        f"\n[bisect] first bad change: {culprit.input_name} "
        f"{culprit.old_version} -> {culprit.new_version}"
    )
    assert culprit.input_name == "lib"

    # 6. Patch: roll the faulty input back to its last-good version.
    good = recorder.last_good_build()
    patch = propose_patch(top, good)
    print(f"\n[patch] {patch.action} {patch.input_name}: "
          f"{patch.from_version} -> {patch.to_version}")
    print(f"    rationale: {patch.rationale}")

    # 7. Verify: rebuild with the patch. Also show a wrong patch failing.
    verdict = verify(graph, patch)
    print(f"\n[verify] patch applied, rebuild "
          f"{'PASSED -- fix confirmed' if verdict.fixed else 'FAILED'}")
    assert verdict.fixed

    wrong = Patch(
        action="rollback",
        input_name="compiler",
        from_version="gcc-13",
        to_version="gcc-12",
        rationale="wrong patch: roll back an innocent input",
    )
    wrong_verdict = verify(graph, wrong)
    print(f"[verify] wrong patch (roll back compiler instead): rebuild "
          f"{'PASSED' if wrong_verdict.fixed else 'FAILED -- correctly rejected'}")
    assert not wrong_verdict.fixed

    # 8. Flakiness scores across targets. Score a fresh graph at the
    # good baseline: scoring must run from a state where dependencies
    # pass, or downstream targets inherit their failures.
    print("\n[flakiness] per-target scores (100 runs, good baseline):")
    for name, score in score_all(make_demo_graph(), runs=100).items():
        print(
            f"    {name:<8} failure_rate={score['failure_rate']:.2f} "
            f"flake_score={score['flake_score']:.2f} "
            f"nondeterministic={score['nondeterministic']}"
        )

    print("\nDone: fault localized, bisected, patched, and verified.")


if __name__ == "__main__":
    main()
