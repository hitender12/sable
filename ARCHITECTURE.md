# Sable — Architecture

## Components

```
demo.py                  runnable heal: inject, localize, bisect, patch, verify
sable/
  graph.py               targets, inputs, deterministic build, snapshots
  provenance.py          build + change history
  localizer.py           ranked suspects with evidence
  bisect.py              first-bad-change binary search
  patcher.py             rollback patch proposals
  verifier.py            rebuild-on-a-copy confirmation
  flakiness.py           per-target nondeterminism scores
  sample.py              demo graph (lib / app / tests)
tests/
  test_sable.py          19 tests (unittest, stdlib only)
```

## Design decisions

**Determinism is the foundation.** `BuildGraph.build()` is a pure
function of the input snapshot plus an optional seed. Without that,
"the build failed after change X" would be meaningless. Flakiness is
modeled explicitly as a per-target probability, drawn from a seeded
RNG, so even nondeterministic behavior is reproducible in tests.

**Provenance is a first-class record, not a log scrape.** The recorder
stores structured snapshots (input -> version) per build and an
ordered change log. Localization and bisection both read the recorder;
nothing parses log text. This is the difference between "the log says
app failed" and "the only input that changed since the last good build
and is read by app is lib 1.9 -> 2.0".

**Localization ranks, bisection proves.** The localizer is a heuristic
ranker (reachability + change size + recency + flakiness as an
alternative hypothesis). It is fast and usually right, but it can tie
or misrank when several inputs changed. The bisector is the arbiter:
it replays builds and returns the first change that breaks the build,
which is a fact, not a ranking. The pipeline is designed so the
cheap heuristic narrows the search and the expensive proof settles it.

**Patches are minimal and reversible.** The only patch is a rollback
to the last-good version of one input. That is the smallest change
with a known-good target state, and it makes verification trivially
meaningful: if the rebuild passes, the fault is gone. Broader patch
types (upgrade, reorder) would need a way to prove the *new* state
is good, which a rollback gets for free from history.

**Verification never touches the live graph.** The verifier deep-copies
the graph, applies the patch to the copy, and rebuilds. A rejected
patch therefore has no side effects, and the live graph keeps the
failing state until a verified fix is applied for real.

**Flakiness is defined, not vibes.** A target's flake score is its
failure rate over repeated runs with *identical* inputs. Same inputs,
different outcomes can only be nondeterminism. A target that fails
every run scores 0 on flakiness — it is broken, and the localizer
should look for an input cause, not blame chance.

## Data flow

```
change inputs ──► record_change ──► build ──► record_build
                                                  │
failing build ──► localize ──► ranked suspects
                        ├─► bisect ──► first bad change
                        └─► propose_patch ──► verify (rebuild on copy)
                                                  ├─► fixed: apply for real
                                                  └─► not fixed: reject
```

## Invariants tested

- Good inputs pass; lib 2.0 fails exactly at `app` (tests blocked).
- Localization top suspect is `lib` for a version bump, `app_src` for
  corrupted content, and a `flake` suspect when nothing changed.
- An unrelated config change ranks below the real cause.
- Bisect finds the lib bump among two innocent changes and restores
  live inputs afterwards.
- The verifier accepts the correct rollback and rejects a wrong one.
- No patch is proposed for a flake suspect.
- Flakiness: deterministic targets score 0, a p=0.3 target scores
  strictly between 0 and 1, and an always-failing target scores 0
  (broken, not flaky).
- End-to-end: inject -> localize -> bisect -> patch -> verified fixed.
