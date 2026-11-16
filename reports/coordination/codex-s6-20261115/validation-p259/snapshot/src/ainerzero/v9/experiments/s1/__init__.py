"""S1 phase 1: preregistration, data identity, resource gate and run entry.

This package is the pure-CPU half of AinerZero.V9.P9.  It *implements and
measures* the S1 phase-1 entry but does not train: the only compute it performs
is the no-update smoke required by the card, plus deterministic data generation
through the frozen AnimeWorldZero arena generator.

Modules
-------
``spec``            frozen constants: arms, caps, resource limits, timing rules
``resource_gate``   start-up refusal + runtime guard (8 GiB / 4 GiB / 16 GiB /
                    0.25 duty / 1 GiB swap growth)
``data``            dataset plan, feature view, packet validation, digests
``awz_export``      standalone producer run under AnimeWorldZero's interpreter
``arms``            the four arms (MLX CPU) and the A2-identity D candidate
``metrics``         metric definitions and pure-numpy computation scripts
``prereg``          draft / freeze / verify the preregistration document
``smoke``           no-update forward+loss measurements and budget estimation
``worker``          locked, RunStore-registered, budget-guarded run entry
``commands``        the ``ainerzero s1-phase1`` CLI implementation

The layer follows the v9 contract rules: imports of ``mlx`` happen only inside
arms/smoke/worker, never at package import time; the data/metrics/prereg paths
are numpy + standard library so the CPU unit tests never touch a model runtime.
"""

from __future__ import annotations

__all__ = ["SPEC_NAME", "TASK_ID"]

SPEC_NAME = "s1-phase1-v1"
TASK_ID = "ainerzero.V9.P9"
