# Sable

**Self-healing build graphs.**

Flaky and broken builds burn more engineering time than writing code.
Sable treats a build as a **probabilistic graph with provenance**: every
build and every input change is recorded, so when a build fails the
system can localize the fault causally, bisect the change history,
propose a minimal patch, and verify the fix by rebuilding — before a
human ever looks at the log.

## The novel idea

1. **Provenance-first builds.** The recorder stores the full input
   snapshot of every build and every input change, in order. A failure
   is never investigated from a bare log line; it is investigated by
   diffing the failing snapshot against the last good one.
2. **Causal localization.** The localizer ranks changed inputs by
   whether the failing target (transitively) reads them, how big the
   change was (major version bump > patch bump), and how recent it was.
   A flaky failing target is always listed as an alternative
   explanation, because a nondeterministic failure needs no input
   change at all.
3. **Automatic bisection.** Binary search over the change history,
   replaying the build at each midpoint, finds the *first* change that
   broke the build — even when innocent changes are mixed in.
4. **Patch + verify.** The patcher proposes the smallest safe fix
   (roll the suspect input back to its last-good version) and the
   verifier proves it by rebuilding on a copy of the graph. A wrong
   patch is rejected by the same mechanism: the rebuild still fails.
5. **Flakiness scoring.** Each target is scored by running the build
   many times with fixed inputs. Any outcome variance is flakiness by
   definition; a target that fails every time is *broken*, not flaky.

## Quickstart

```bash
python demo.py                                  # full heal: inject, localize, bisect, patch, verify
python -m unittest discover -s tests -v         # 19 tests
```

Or use it as a library:

```python
from sable import make_demo_graph, localize, propose_patch, verify
from sable.provenance import ProvenanceRecorder

graph = make_demo_graph()
recorder = ProvenanceRecorder()
recorder.record_build(graph.build(seed=0), graph.snapshot())

graph.inputs["lib"].version = "2.0"             # the fault
recorder.record_change("lib", "1.9", "2.0")
recorder.record_build(graph.build(seed=0), graph.snapshot())

top = localize(graph, recorder)[0]              # -> lib
patch = propose_patch(top, recorder.last_good_build())
print(verify(graph, patch).fixed)               # -> True
```

## Demo output (abridged)

```
[lib 1.9 -> 2.0 (INJECTED FAULT)] build FAILED
    app: FAILED (rule)
[localize] ranked suspects:
    input lib score=3.0
      - lib changed 1.9 -> 2.0 since last good build
      - lib is read (transitively) by failing target app
[bisect] first bad change: lib 1.9 -> 2.0
[patch] rollback lib: 2.0 -> 1.9
[verify] patch applied, rebuild PASSED -- fix confirmed
[verify] wrong patch (roll back compiler instead): rebuild FAILED -- correctly rejected
[flakiness] per-target scores (100 runs, good baseline):
    lib      failure_rate=0.00 flake_score=0.00
    app      failure_rate=0.00 flake_score=0.00
    tests    failure_rate=0.11 flake_score=0.11 nondeterministic=True
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short:

- `sable/graph.py` — targets, inputs, deterministic build execution,
  snapshots, topological ordering.
- `sable/provenance.py` — the build/change history the whole system
  reasons over.
- `sable/localizer.py` — ranked suspects with evidence strings.
- `sable/bisect.py` — binary search for the first bad change.
- `sable/patcher.py` — rollback patch proposals.
- `sable/verifier.py` — rebuild-on-a-copy confirmation.
- `sable/flakiness.py` — per-target nondeterminism scores.
- `sable/sample.py` — the demo graph (lib/app/tests).

## Honest status

What genuinely works: the simulated build graph, provenance recording,
localization on version-bump / corrupted-content / flake faults,
bisection across innocent changes, rollback patching, verification
(including rejection of wrong patches), flakiness scoring, the demo,
and the 19 tests (all passing).

What is simplified:

- This is a **simulated** build graph, not an integration with Bazel,
  Gradle, or Make. Real integration would need a build-system adapter
  that captures real input snapshots and replays real builds.
- Builds are in-process Python functions, not subprocesses — there is
  no sandboxing, no parallelism, and no real artifact hashing (the
  "content hash" is a stand-in string).
- The patcher only proposes rollbacks. Real healers would also propose
  version pins, dependency upgrades, and ordering fixes; those need a
  richer patch language and a real verifier.
- Bisection assumes deterministic builds. With genuinely flaky targets
  in the replay path it can misattribute; the localizer's flake suspect
  is the guard against that, but the bisector itself does not yet
  repeat replays to gain confidence.
- Localization ranking among several changed inputs is heuristic
  (reachability, change size, recency). Bisection is the definitive
  step, not the ranking.

## Evaluation plan

1. Adapter for a real build system (Bazel first): capture real input
   snapshots from build events and replay real builds.
2. Benchmark on a corpus of real broken builds: localization top-1
   accuracy, bisection correctness, auto-fix rate, and time-to-fix vs.
   human diagnosis.
3. Add patch types (pin, upgrade, reorder) with a verification budget.
4. Make bisection flake-aware: repeat each midpoint replay and use a
   majority vote before concluding.

## License

MIT — see [LICENSE](LICENSE).
