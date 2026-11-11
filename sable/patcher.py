"""Patch proposer: turn the top suspect into a concrete, verifiable fix.

The only patch this proposer makes is a rollback: restore the suspect
input to the version it had at the last good build.  That is deliberate
-- a rollback is the smallest change that is guaranteed to return the
build to a known-good input state, and it is exactly what the verifier
can confirm by rebuilding.  Flake suspects get no patch: there is no
input to roll back, and the right response is retry/quarantine, not a
config change.
"""

from __future__ import annotations

from dataclasses import dataclass

from .localizer import Suspect
from .provenance import BuildRecord


@dataclass
class Patch:
    action: str  # currently always "rollback"
    input_name: str
    from_version: str
    to_version: str
    rationale: str


def propose_patch(
    suspect: Suspect, good_build: BuildRecord
) -> Patch | None:
    if suspect.kind != "input":
        return None
    return Patch(
        action="rollback",
        input_name=suspect.input_name,
        from_version=suspect.new_version,
        to_version=suspect.old_version,
        rationale=(
            f"Roll back {suspect.input_name} from "
            f"{suspect.new_version} to {suspect.old_version}, the "
            "version in the last good build."
        ),
    )
