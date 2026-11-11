"""Tests for Sable.

Run with:  python -m unittest discover -s tests -v
"""

import unittest

from sable import (
    BuildGraph,
    Input,
    Patch,
    Target,
    bisect_first_bad_change,
    localize,
    make_demo_graph,
    propose_patch,
    score_all,
    score_target,
    verify,
)
from sable.provenance import ProvenanceRecorder


def run_and_record(recorder, graph, seed=0):
    result = graph.build(seed=seed)
    recorder.record_build(result, graph.snapshot())
    return result


def change(recorder, graph, name, new_version):
    old = graph.inputs[name].version
    graph.inputs[name].version = new_version
    recorder.record_change(name, old, new_version)


class TestBuildGraph(unittest.TestCase):
    def test_build_passes_on_good_inputs(self):
        graph = make_demo_graph()
        result = graph.build(seed=0)
        self.assertTrue(result.ok)
        self.assertIsNone(result.failed_target)
        self.assertTrue(all(result.per_target.values()))

    def test_build_fails_at_app_on_lib_2(self):
        graph = make_demo_graph()
        graph.inputs["lib"].version = "2.0"
        result = graph.build(seed=0)
        self.assertFalse(result.ok)
        self.assertEqual(result.failed_target, "app")
        self.assertFalse(result.per_target["app"])
        self.assertFalse(result.per_target["tests"])  # blocked by app

    def test_cycle_detection(self):
        graph = BuildGraph(
            targets=[
                Target(name="a", deps=["b"]),
                Target(name="b", deps=["a"]),
            ],
            inputs=[],
        )
        with self.assertRaises(ValueError):
            graph.build()

    def test_snapshot_round_trip(self):
        graph = make_demo_graph()
        snap = graph.snapshot()
        graph.inputs["lib"].version = "2.0"
        graph.apply_snapshot(snap)
        self.assertEqual(graph.inputs["lib"].version, "1.9")


class TestLocalization(unittest.TestCase):
    def _failing_after(self, changes):
        """Fresh graph + recorder, one good build, then the given
        (input, new_version) changes, then a failing build."""
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        for name, new in changes:
            change(recorder, graph, name, new)
        result = run_and_record(recorder, graph)
        self.assertFalse(result.ok)
        return graph, recorder

    def test_localize_bad_version_bump(self):
        graph, recorder = self._failing_after([("lib", "2.0")])
        suspects = localize(graph, recorder)
        self.assertEqual(suspects[0].kind, "input")
        self.assertEqual(suspects[0].input_name, "lib")
        self.assertEqual(suspects[0].old_version, "1.9")
        self.assertEqual(suspects[0].new_version, "2.0")

    def test_localize_corrupted_content(self):
        graph, recorder = self._failing_after([("app_src", "a2")])
        suspects = localize(graph, recorder)
        self.assertEqual(suspects[0].input_name, "app_src")
        self.assertEqual(suspects[0].target, "tests")

    def test_localize_ignores_unrelated_change(self):
        """A config change no target reads must rank below the real
        cause even though it also changed since the last good build."""
        graph, recorder = self._failing_after(
            [("config", "fast-lto"), ("lib", "2.0")]
        )
        suspects = localize(graph, recorder)
        self.assertEqual(suspects[0].input_name, "lib")
        self.assertEqual(suspects[-1].input_name, "config")

    def test_localize_flake_when_nothing_changed(self):
        """No input changed, but the flaky target failed: the localizer
        must blame flakiness, not invent an input cause."""
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)  # good baseline, tests not flaky
        graph.targets["tests"].flaky = 1.0
        run_and_record(recorder, graph)  # fails, no input changed
        suspects = localize(graph, recorder)
        self.assertEqual(suspects[0].kind, "flake")
        self.assertEqual(suspects[0].target, "tests")

    def test_localize_no_baseline(self):
        graph = make_demo_graph()
        graph.inputs["lib"].version = "2.0"
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        suspects = localize(graph, recorder)
        self.assertEqual(len(suspects), 1)
        self.assertEqual(suspects[0].kind, "unknown")


class TestBisect(unittest.TestCase):
    def test_bisect_finds_first_bad_change(self):
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)  # baseline (builds[0])
        change(recorder, graph, "compiler", "gcc-13")  # innocent
        run_and_record(recorder, graph)
        change(recorder, graph, "config", "fast-lto")  # innocent
        run_and_record(recorder, graph)
        change(recorder, graph, "lib", "2.0")  # the fault
        run_and_record(recorder, graph)
        # Bisect from the baseline, so all three changes are candidates.
        baseline = recorder.builds[0]
        culprit = bisect_first_bad_change(graph, recorder, baseline)
        self.assertIsNotNone(culprit)
        self.assertEqual(culprit.input_name, "lib")
        self.assertEqual((culprit.old_version, culprit.new_version),
                         ("1.9", "2.0"))

    def test_bisect_restores_live_inputs(self):
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        change(recorder, graph, "lib", "2.0")
        run_and_record(recorder, graph)
        bisect_first_bad_change(graph, recorder, recorder.builds[0])
        self.assertEqual(graph.inputs["lib"].version, "2.0")


class TestPatchAndVerify(unittest.TestCase):
    def _failing(self):
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        change(recorder, graph, "lib", "2.0")
        run_and_record(recorder, graph)
        return graph, recorder

    def test_verifier_accepts_correct_patch(self):
        graph, recorder = self._failing()
        suspect = localize(graph, recorder)[0]
        patch = propose_patch(suspect, recorder.last_good_build())
        self.assertEqual(patch.input_name, "lib")
        self.assertEqual(patch.to_version, "1.9")
        verdict = verify(graph, patch)
        self.assertTrue(verdict.fixed)
        self.assertIsNone(verdict.failed_target)

    def test_verifier_rejects_wrong_patch(self):
        """Rolling back an innocent input must NOT fix the build."""
        graph, recorder = self._failing()
        wrong = Patch(
            action="rollback",
            input_name="compiler",
            from_version="gcc-12",
            to_version="gcc-11",
            rationale="wrong patch: roll back an innocent input",
        )
        verdict = verify(graph, wrong)
        self.assertFalse(verdict.fixed)
        self.assertEqual(verdict.failed_target, "app")

    def test_no_patch_for_flake_suspect(self):
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        graph.targets["tests"].flaky = 1.0
        run_and_record(recorder, graph)
        suspects = localize(graph, recorder)
        flake = next(s for s in suspects if s.kind == "flake")
        self.assertIsNone(propose_patch(flake, recorder.last_good_build()))

    def test_end_to_end_heal(self):
        """Inject fault -> localize -> bisect -> patch -> verify fixed."""
        graph = make_demo_graph()
        recorder = ProvenanceRecorder()
        run_and_record(recorder, graph)
        change(recorder, graph, "compiler", "gcc-13")
        run_and_record(recorder, graph)
        change(recorder, graph, "lib", "2.0")
        run_and_record(recorder, graph)
        good = recorder.last_good_build()
        top = localize(graph, recorder)[0]
        self.assertEqual(top.input_name, "lib")
        culprit = bisect_first_bad_change(graph, recorder, recorder.builds[0])
        self.assertEqual(culprit.input_name, "lib")
        patch = propose_patch(top, good)
        self.assertTrue(verify(graph, patch).fixed)


class TestFlakiness(unittest.TestCase):
    def test_deterministic_target_scores_zero(self):
        graph = make_demo_graph()
        score = score_target(graph, "lib", runs=20)
        self.assertEqual(score["flake_score"], 0.0)
        self.assertFalse(score["nondeterministic"])

    def test_flaky_target_scores_above_zero(self):
        graph = make_demo_graph()
        graph.targets["tests"].flaky = 0.3
        score = score_target(graph, "tests", runs=50)
        self.assertTrue(score["nondeterministic"])
        self.assertGreater(score["flake_score"], 0.0)
        self.assertLess(score["flake_score"], 1.0)

    def test_broken_not_flaky(self):
        """A target that fails on every run is broken, not flaky."""
        graph = make_demo_graph()
        graph.inputs["lib"].version = "2.0"
        score = score_target(graph, "app", runs=10)
        self.assertEqual(score["failure_rate"], 1.0)
        self.assertEqual(score["flake_score"], 0.0)
        self.assertFalse(score["nondeterministic"])

    def test_score_all_covers_every_target(self):
        graph = make_demo_graph()
        scores = score_all(graph, runs=10)
        self.assertEqual(set(scores), {"lib", "app", "tests"})


if __name__ == "__main__":
    unittest.main()
