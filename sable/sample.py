"""The demo build graph used by ``demo.py`` and the tests.

Targets:

- ``lib``   -- a library; builds whenever its dependency is present.
- ``app``   -- depends on ``lib``; breaks when ``lib`` reaches a 2.x
  version (breaking API change), and reads the ``compiler`` input.
- ``tests`` -- depends on ``app``; breaks when the ``app_src`` content
  hash changes, and is flaky (p=0.1) to exercise the flakiness scorer.

Inputs: ``lib`` (version), ``compiler`` (version), ``config`` (a value
no target reads -- an innocent bystander), ``app_src`` (content hash).
"""

from __future__ import annotations

from .graph import BuildGraph, Input, Target


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split(".") if x.isdigit())


def make_demo_graph() -> BuildGraph:
    return BuildGraph(
        targets=[
            Target(name="lib", inputs=["lib"]),
            Target(
                name="app",
                deps=["lib"],
                inputs=["lib", "compiler"],
                rule=lambda inputs: _version_tuple(
                    inputs["lib"].version
                )
                < (2, 0),
            ),
            Target(
                name="tests",
                deps=["app"],
                inputs=["app_src"],
                rule=lambda inputs: inputs["app_src"].version == "a1",
                flaky=0.1,
            ),
        ],
        inputs=[
            Input(name="lib", version="1.9", kind="dependency"),
            Input(name="compiler", version="gcc-12", kind="toolchain"),
            Input(name="config", version="fast", kind="config"),
            Input(name="app_src", version="a1", kind="source"),
        ],
    )
