"""MOne -- the AETHER behavior-engine kernel.

A deterministic Kuramoto phase-synchronization simulation that emits discrete
"spark" events plus a continuous coherence value, used as an NPC behavior driver.
Pure math: no IO, no networking, no LiveKit -- a later task wires it into the
agent worker.

Public surface::

    from avatar.mone import MOneKernel, MOneConfig, Spark, TickResult
"""

from __future__ import annotations

from avatar.mone.config import PHI, REGION_LABELS
from avatar.mone.kernel import MOneConfig, MOneKernel, Spark, TickResult

__all__ = [
    "PHI",
    "REGION_LABELS",
    "MOneConfig",
    "MOneKernel",
    "Spark",
    "TickResult",
]
