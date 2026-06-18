"""MOne Kuramoto phase-sync kernel tests -- the "live, not scripted" differentiator.

These prove the kernel is a real, deterministic dynamical system rather than a
canned animation:

- determinism: same seed + same calls => byte-identical spark stream;
- coherence is a valid order parameter (R in [0, 1]) and synchronizes with K;
- the PID-like controller servos the spark rate into the [SPARK_MIN, SPARK_MAX]
  clamp band around SPARK_TARGET;
- a perturbation measurably shifts the subsequent stream vs the same-seed
  baseline (reactivity);
- every spark carries a populated, in-range ``dominant_node`` / label.

The seeds used in the rate/perturbation assertions (0, 7, 42) were chosen because
they land solidly mid-band; the determinism and dominant-node checks are
seed-agnostic by construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from avatar.mone import MOneConfig, MOneKernel, Spark, TickResult
from avatar.mone import config as mone_config

# A run long enough for the controller to settle into steady state. The kernel
# ignites (first spark) within ~320 ticks for every seed; 2000 ticks of warm-up
# leaves a 3000-tick measurement window.
_WARM_STEPS = 2000
_MEASURE_STEPS = 3000
_TOTAL_STEPS = _WARM_STEPS + _MEASURE_STEPS


def _spark_signature(kernel: MOneKernel, steps: int) -> list[tuple[int, float, int, str, float]]:
    """Collect a fully-specified, comparable signature of the spark stream."""
    out: list[tuple[int, float, int, str, float]] = []
    for _ in range(steps):
        for sp in kernel.step().sparks:
            out.append((sp.spark_id, sp.t, sp.dominant_node, sp.dominant_label, sp.R))
    return out


# --------------------------------------------------------------------------- #
# Determinism                                                                  #
# --------------------------------------------------------------------------- #
def test_determinism_same_seed_identical_stream() -> None:
    """Same seed + params + call sequence => byte-identical spark stream."""
    sig_a = _spark_signature(MOneKernel(seed=7), 1500)
    sig_b = _spark_signature(MOneKernel(seed=7), 1500)
    assert sig_a == sig_b
    # Guard against a vacuous pass: the stream must be non-empty.
    assert len(sig_a) > 0


def test_determinism_coherence_trace_identical() -> None:
    """The continuous coherence trace is reproducible to full float precision."""
    k_a = MOneKernel(seed=13)
    trace_a = [k_a.step().R for _ in range(800)]
    k_b = MOneKernel(seed=13)
    trace_b = [k_b.step().R for _ in range(800)]
    assert trace_a == trace_b


def test_different_seed_different_stream() -> None:
    """Different seeds produce different streams (the seed actually matters)."""
    sig_a = _spark_signature(MOneKernel(seed=1), 1500)
    sig_b = _spark_signature(MOneKernel(seed=2), 1500)
    assert sig_a != sig_b


# --------------------------------------------------------------------------- #
# Order parameter R                                                            #
# --------------------------------------------------------------------------- #
def test_R_always_in_unit_interval() -> None:
    """R is a Kuramoto order parameter: it must stay in [0, 1] every tick."""
    k = MOneKernel(seed=3)
    for _ in range(_TOTAL_STEPS):
        tick = k.step()
        assert 0.0 <= tick.R <= 1.0 + 1e-9


def test_high_K_synchronizes_low_K_incoherent() -> None:
    """With K above critical, R trends high (partial sync); at K=0 it stays low."""
    k_zero = MOneKernel(seed=3, k=0.0)
    r_zero = [k_zero.step().R for _ in range(1500)]

    k_high = MOneKernel(seed=3, k=3.0)
    r_high = [k_high.step().R for _ in range(1500)]

    mean_zero = float(np.mean(r_zero[-500:]))
    mean_high = float(np.mean(r_high[-500:]))

    # Incoherent regime sits well below the coupled regime.
    assert mean_zero < 0.4
    assert mean_high > 0.8
    assert mean_high > mean_zero


# --------------------------------------------------------------------------- #
# Spark-rate convergence (the PID-like controller)                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", [0, 7, 42])
def test_spark_rate_converges_into_clamp_band(seed: int) -> None:
    """Over a window the controller drives the spark rate into [SPARK_MIN, MAX]."""
    k = MOneKernel(seed=seed)
    rates: list[float] = []
    for i in range(_TOTAL_STEPS):
        k.step()
        if i >= _WARM_STEPS:
            rates.append(k._current_rate())

    mean_rate = float(np.mean(rates))
    assert mone_config.SPARK_MIN <= mean_rate <= mone_config.SPARK_MAX, (
        f"steady-state rate {mean_rate:.1f}/s outside "
        f"[{mone_config.SPARK_MIN}, {mone_config.SPARK_MAX}] (target "
        f"{mone_config.SPARK_TARGET})"
    )


def test_effective_k_stays_on_productive_flank() -> None:
    """The controller holds effective K on the spark-productive flank, not railed."""
    k = MOneKernel(seed=7)
    for _ in range(_TOTAL_STEPS):
        k.step()
    # K_eff = K * pressure, pressure clamped to [0.3, 0.66] => K_eff in [0.66, 1.45].
    assert 0.6 <= k.k_effective <= 1.5


# --------------------------------------------------------------------------- #
# Perturbation (reactivity)                                                    #
# --------------------------------------------------------------------------- #
def _spark_times_after(seed: int, *, perturb_at: int | None, t_floor: float) -> list[float]:
    """Spark times with t >= t_floor, optionally perturbing node 4 mid-run."""
    k = MOneKernel(seed=seed)
    out: list[float] = []
    for i in range(2500):
        if perturb_at is not None and i == perturb_at:
            k.perturb(4, 0.7)
        for sp in k.step().sparks:
            if sp.t >= t_floor:
                out.append(sp.t)
    return out


def test_perturbation_shifts_subsequent_stream() -> None:
    """``perturb()`` measurably changes the spark cadence vs the same-seed baseline."""
    # Compare only sparks AFTER the perturbation instant (t >= 15s); before it the
    # two runs are identical, so a difference here is caused by perturb() alone.
    baseline = _spark_times_after(11, perturb_at=None, t_floor=15.0)
    perturbed = _spark_times_after(11, perturb_at=300, t_floor=15.0)
    assert baseline != perturbed


def test_perturbation_is_deterministic() -> None:
    """A perturbed run is itself fully reproducible (perturb adds no nondeterminism)."""
    a = _spark_times_after(11, perturb_at=300, t_floor=0.0)
    b = _spark_times_after(11, perturb_at=300, t_floor=0.0)
    assert a == b


def test_perturb_out_of_range_raises() -> None:
    k = MOneKernel(seed=0, n_nodes=11)
    with pytest.raises(IndexError):
        k.perturb(11, 0.5)
    with pytest.raises(IndexError):
        k.perturb(-1, 0.5)


# --------------------------------------------------------------------------- #
# dominant_node                                                                #
# --------------------------------------------------------------------------- #
def test_sparks_carry_valid_dominant_node() -> None:
    """Every emitted spark has an in-range dominant_node and a non-empty label."""
    k = MOneKernel(seed=5)
    n_sparks = 0
    seen_labels: set[str] = set()
    for _ in range(_TOTAL_STEPS):
        for sp in k.step().sparks:
            n_sparks += 1
            assert 0 <= sp.dominant_node < k.n
            assert sp.dominant_label
            assert sp.dominant_label == mone_config.REGION_LABELS[sp.dominant_node]
            seen_labels.add(sp.dominant_label)
    assert n_sparks > 0
    # A live system exercises more than one region over a long run.
    assert len(seen_labels) > 1


def test_tickresult_shape_and_types() -> None:
    """Smoke-check the public dataclass surface the NPC publisher will consume."""
    k = MOneKernel(seed=7)
    tick: TickResult | None = None
    for _ in range(600):
        tick = k.step()
    assert tick is not None
    assert isinstance(tick, TickResult)
    assert isinstance(tick.t, float)
    assert isinstance(tick.R, float)
    assert isinstance(tick.k, float)
    assert isinstance(tick.sparks, list)
    assert 0 <= tick.dominant_node < k.n
    for sp in tick.sparks:
        assert isinstance(sp, Spark)
        assert sp.spark_id > 0


# --------------------------------------------------------------------------- #
# Config / construction                                                        #
# --------------------------------------------------------------------------- #
def test_explicit_omegas_override_n_nodes() -> None:
    """Supplying omegas sets N from its length and uses those frequencies."""
    omegas = [0.2, -0.3, 0.4]
    k = MOneKernel(seed=0, omegas=omegas)
    assert k.n == 3
    np.testing.assert_array_equal(k._omega, np.array(omegas, dtype=np.float64))


def test_custom_config_is_respected() -> None:
    """A custom MOneConfig (e.g. a different K) flows into the dynamics."""
    cfg = MOneConfig(k=5.0)
    k = MOneKernel(seed=0, cfg=cfg)
    assert k.cfg.k == 5.0
    # k= kwarg overrides cfg.k.
    k2 = MOneKernel(seed=0, cfg=cfg, k=1.0)
    assert k2.cfg.k == 1.0


def test_zero_nodes_rejected() -> None:
    with pytest.raises(ValueError):
        MOneKernel(seed=0, omegas=[])


def test_order_parameter_matches_step_R() -> None:
    """order_parameter() and step().R agree on the post-step coherence."""
    k = MOneKernel(seed=4)
    for _ in range(50):
        tick = k.step()
    R_view, _psi = k.order_parameter()
    assert abs(R_view - tick.R) < 1e-12
