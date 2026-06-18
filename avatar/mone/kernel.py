"""Deterministic Kuramoto phase-synchronization kernel — the MOne behavior engine.

This is the load-bearing core of AETHER: a pure-Python, numpy-only, deterministic
re-implementation of the runnable kernel inside ``AI_consciousness_MOne_1.html``.
The original was a Kuramoto model dressed in decorative cosmology (Hawking
temperature, dark matter, ~37 "forces"); only the Kuramoto dynamics + golden-ratio
spark gating + the adaptive-K spark-rate controller are load-bearing, and only
those are reproduced here. See :mod:`avatar.mone.config` for constant provenance.

What it does, per :meth:`MOneKernel.step`:

1. **Phase coherence** -- the Kuramoto order parameter
   ``R = |mean(exp(i*theta))|`` in [0, 1], with mean-field angle ``psi``.
   Source: ``R = sqrt(sx**2+sy**2)/N`` (lines 1922-1923).

2. **Mean-field Kuramoto coupling** (Euler step, dt ~= 0.05):
   ``dtheta_i/dt = omega_i + (K_eff/N) * sum_j sin(theta_j - theta_i)``
   which by the order-parameter identity equals
   ``omega_i + K_eff * R * sin(psi - theta_i)``.
   ``K_eff = K * coupling_pressure``. Source: lines 2483-2490 (the explicit
   ``// 12. KURAMOTO SYNCHRONIZATION`` block).

3. **Phase-lag accumulation** -- each node integrates ``|psi - theta_i|`` into a
   per-node accumulator that slowly decays. A node whose accumulator crosses the
   golden threshold ``DELTA_THRESHOLD = pi/phi`` is at a "pause" point and becomes
   spark-eligible. Source: lines 2700-2701.

4. **Spark firing** -- when global coherence ``R*phi > 1`` (i.e. ``R > 1/phi``)
   AND a node is past ``DELTA_THRESHOLD``, the node fires with a probability
   modulated by an adaptive rate factor. The draw uses the *seeded* Generator,
   so the spark stream is fully deterministic. Source: lines 2145-2168.

5. **Adaptive K (PID-like controller)** -- a rolling 2 s window measures the spark
   rate; ``coupling_pressure`` is nudged toward holding ``SPARK_TARGET`` and
   clamped to ``[0.3, 2.8]``. Source: lines 1882-1885.

6. **dominant_node** -- the node most aligned with the mean field at the firing
   instant (``argmax(cos(theta_i - psi))`` among eligible nodes) is named the
   spark's dominant node and mapped to a brain-region label so downstream can
   route MOTOR->step, CONCEPT->speak, etc.

Determinism contract: identical ``seed`` + identical params + identical
``step``/``perturb`` call sequence => byte-identical spark stream and coherence
trace. No wall-clock, no global ``random`` -- all randomness flows through a
single ``numpy.random.Generator(PCG64(seed))``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from avatar.mone import config

__all__ = ["MOneConfig", "MOneKernel", "Spark", "TickResult"]


@dataclass(frozen=True, slots=True)
class Spark:
    """A single discrete firing event emitted by the kernel.

    Downstream (the NPC publisher) consumes these to drive behavior: ``t`` is the
    simulation time of the firing, ``R`` the coherence at that instant, and
    ``dominant_node`` the index (and label) of the region most responsible.
    """

    spark_id: int
    t: float
    R: float
    dominant_node: int
    dominant_label: str


@dataclass(frozen=True, slots=True)
class TickResult:
    """The outcome of one :meth:`MOneKernel.step`.

    ``sparks`` may be empty (no firing this tick) or hold one event per node that
    fired. ``R`` is the post-step coherence; ``k`` is the *effective* coupling
    (``K * coupling_pressure``) the controller is currently holding;
    ``dominant_node`` mirrors the last spark's dominant node, or the globally
    most field-aligned node when no spark fired (handy for telemetry).
    """

    t: float
    R: float
    sparks: list[Spark]
    k: float
    dominant_node: int


@dataclass(frozen=True, slots=True)
class MOneConfig:
    """Tunable parameters for :class:`MOneKernel`.

    Every field defaults to the extracted MOne source value (see
    :mod:`avatar.mone.config`). Construct with overrides to retune without
    touching the kernel body -- nothing in :class:`MOneKernel` hardcodes a magic
    number that is not surfaced here.
    """

    k: float = config.K_KURAMOTO
    dt: float = config.DEFAULT_DT
    delta_threshold: float = config.DELTA_THRESHOLD
    phase_integration_scale: float = config.PHASE_INTEGRATION_SCALE
    phase_velocity_clamp: float = config.PHASE_VELOCITY_CLAMP
    phase_lag_decay: float = config.PHASE_LAG_DECAY
    phase_lag_drive_scale: float = config.PHASE_LAG_DRIVE_SCALE
    phase_lag_detune_weight: float = config.PHASE_LAG_DETUNE_WEIGHT
    coherence_spark_floor: float = config.COHERENCE_SPARK_FLOOR
    # Spark-rate controller.
    spark_target: float = config.SPARK_TARGET
    spark_min: float = config.SPARK_MIN
    spark_max: float = config.SPARK_MAX
    spark_window_sec: float = config.SPARK_WINDOW_SEC
    coupling_pressure_gain: float = config.COUPLING_PRESSURE_GAIN
    coupling_pressure_sign: float = config.COUPLING_PRESSURE_SIGN
    coupling_pressure_min: float = config.COUPLING_PRESSURE_MIN
    coupling_pressure_max: float = config.COUPLING_PRESSURE_MAX
    coupling_pressure_init: float = config.COUPLING_PRESSURE_INIT
    rate_boost_below_min: float = config.RATE_BOOST_BELOW_MIN
    rate_damp_above_max: float = config.RATE_DAMP_ABOVE_MAX
    spark_discharge: float = config.SPARK_DISCHARGE
    # omega sampling band (used only when omegas are not supplied explicitly).
    omega_abs_lo: float = config.OMEGA_ABS_LO
    omega_abs_hi: float = config.OMEGA_ABS_HI
    # Base per-tick spark probability scale for an eligible node at R*phi just
    # above the floor. The source multiplied ~20 decorative gates into this; we
    # collapse them into one named, tunable scalar. Calibrated (with the
    # accumulator gain/decay) so that at the default 11-node topology + K=2.2 the
    # controller converges the rolling spark rate into the [SPARK_MIN, SPARK_MAX]
    # band around SPARK_TARGET.
    spark_base_prob: float = 0.45


class MOneKernel:
    """Deterministic Kuramoto phase-sync engine producing a spark stream.

    Example::

        k = MOneKernel(seed=7)
        for _ in range(200):
            tick = k.step()
            for sp in tick.sparks:
                route(sp.dominant_label)   # MOTOR -> step, CONCEPT -> speak ...

    Same ``seed`` + same calls => same ``tick`` sequence, every run.
    """

    def __init__(
        self,
        *,
        n_nodes: int = config.DEFAULT_N_NODES,
        omegas: NDArray[np.float64] | list[float] | None = None,
        k: float | None = None,
        seed: int = 0,
        cfg: MOneConfig | None = None,
        labels: tuple[str, ...] | None = None,
    ) -> None:
        """Initialize the kernel.

        Args:
            n_nodes: number of phase oscillators (default 11, the MOne regions).
                Ignored if ``omegas`` is supplied (its length wins).
            omegas: explicit natural frequencies. If ``None`` they are sampled
                deterministically from ``[omega_abs_lo, omega_abs_hi)`` with a
                random sign, via the seeded Generator (mirrors source line 1612).
            k: coupling constant override; defaults to ``cfg.k`` (2.2).
            seed: RNG seed. The ONLY source of randomness -- determinism hinges
                on it. Uses ``numpy.random.Generator(PCG64(seed))``.
            cfg: full :class:`MOneConfig`; defaults to all-MOne-source values.
            labels: region labels indexed by ``dominant_node``. Defaults to the
                11 MOne ``REGION_LABELS``; for ``n_nodes != 11`` falls back to
                ``NODE_<i>`` for any index beyond the provided labels.
        """
        self.cfg: MOneConfig = cfg if cfg is not None else MOneConfig()
        if k is not None:
            self.cfg = _with_k(self.cfg, k)

        self._rng: np.random.Generator = np.random.default_rng(seed)

        if omegas is not None:
            self._omega: NDArray[np.float64] = np.asarray(omegas, dtype=np.float64).copy()
            self.n: int = int(self._omega.shape[0])
        else:
            self.n = int(n_nodes)
            mag = self._rng.uniform(self.cfg.omega_abs_lo, self.cfg.omega_abs_hi, size=self.n)
            sign = self._rng.choice(np.array([-1.0, 1.0]), size=self.n)
            self._omega = mag * sign

        if self.n < 1:
            raise ValueError("n_nodes must be >= 1")

        # Region labels, padded for non-default N.
        base = labels if labels is not None else config.REGION_LABELS
        self._labels: tuple[str, ...] = tuple(
            base[i] if i < len(base) else f"NODE_{i}" for i in range(self.n)
        )

        # -- Mutable simulation state --------------------------------------
        # Initial phases uniformly on [0, 2*pi) via the seeded Generator
        # (source seeded each string ``phase = random()*TAU``, line 1611).
        self._theta: NDArray[np.float64] = self._rng.uniform(0.0, 2.0 * np.pi, size=self.n)
        # Phase velocity carries the natural frequency; starts at omega.
        self._phase_v: NDArray[np.float64] = self._omega.copy()
        self._phase_lag_accum: NDArray[np.float64] = np.zeros(self.n, dtype=np.float64)

        self._t: float = 0.0
        self._coupling_pressure: float = self.cfg.coupling_pressure_init
        self._spark_counter: int = 0
        # Timestamps of recent sparks for the rolling-window rate estimate.
        self._spark_window: deque[float] = deque()
        self._last_dominant: int = 0

    # -- Public read-only views ------------------------------------------------
    @property
    def t(self) -> float:
        """Current simulation time (seconds)."""
        return self._t

    @property
    def coupling_pressure(self) -> float:
        """Current controller pressure (the multiplier on K)."""
        return self._coupling_pressure

    @property
    def k_effective(self) -> float:
        """Effective coupling the controller is currently holding (K * pressure)."""
        return self.cfg.k * self._coupling_pressure

    def order_parameter(self) -> tuple[float, float]:
        """Return ``(R, psi)`` -- coherence in [0, 1] and mean-field angle."""
        z = np.exp(1j * self._theta).mean()
        return float(np.abs(z)), float(np.angle(z))

    def phases(self) -> NDArray[np.float64]:
        """A copy of the current phase vector (read-only snapshot)."""
        return self._theta.copy()

    # -- Perturbation hook -----------------------------------------------------
    def perturb(self, node: int, delta_omega: float) -> None:
        """Nudge a node's natural frequency (reactive-NPC hook).

        "A player approached" -> ``perturb(node, +0.3)`` raises that region's
        intrinsic drive, detuning it from the pack and visibly shifting sync /
        spark cadence on subsequent steps. Deterministic: the change is a plain
        in-place add, no RNG draw, so a perturbed run stays reproducible.

        Args:
            node: oscillator index in ``[0, n)``.
            delta_omega: additive change to ``omega[node]`` (rad/s, can be < 0).
        """
        if not 0 <= node < self.n:
            raise IndexError(f"node {node} out of range [0, {self.n})")
        self._omega[node] += delta_omega
        # Apply immediately to the live velocity too, so the nudge takes effect
        # this tick rather than waiting for the integrator to catch up.
        self._phase_v[node] += delta_omega

    # -- Core integration ------------------------------------------------------
    def step(self, dt: float | None = None) -> TickResult:
        """Advance the simulation by one Euler step and return the tick result.

        Args:
            dt: timestep override; defaults to ``cfg.dt`` (~= 0.05).

        Returns:
            :class:`TickResult` with the post-step coherence ``R``, any sparks
            fired this tick, the effective ``k``, and the dominant node.
        """
        cfg = self.cfg
        h = cfg.dt if dt is None else dt

        # 1. Order parameter from current phases.
        z = np.exp(1j * self._theta).mean()
        R = float(np.abs(z))
        psi = float(np.angle(z))

        # 2. Mean-field Kuramoto coupling toward the global phase psi, weighted by
        #    the order parameter R (identity: (K/N) sum_j sin(theta_j - theta_i)
        #    == K * R * sin(psi - theta_i)). couplingPressure scales K.
        k_eff = cfg.k * self._coupling_pressure
        coupling = k_eff * R * np.sin(psi - self._theta)

        # Phase velocity = natural frequency + coupling pull. (The source kept a
        # persistent phaseV with inertia; we use the textbook first-order form
        # dtheta/dt = omega + coupling, which is the load-bearing dynamics.)
        self._phase_v = self._omega + coupling
        # Velocity clamp (source line 2903: |phaseV| <= 1.5).
        np.clip(
            self._phase_v,
            -cfg.phase_velocity_clamp,
            cfg.phase_velocity_clamp,
            out=self._phase_v,
        )

        # 3. Phase-lag accumulation per node (spark predictor). The per-tick drive
        #    has two parts: the instantaneous wrapped phase-lag |psi - theta_i|
        #    (source 2700-2701) PLUS a persistent frequency-detuning term
        #    |phaseV_i - mean(phaseV)| that survives synchronization (so a cleanly
        #    locking seed still sparks). We feed this through a bounded EMA rather
        #    than the source's unbounded running sum, so eligibility responds in
        #    ~1/(1-decay) ticks for every seed. The golden threshold
        #    DELTA_THRESHOLD = pi/phi gates eligibility in _maybe_fire.
        delta = np.angle(np.exp(1j * (psi - self._theta)))
        detune = np.abs(self._phase_v - self._phase_v.mean())
        drive = (np.abs(delta) + cfg.phase_lag_detune_weight * detune) * cfg.phase_lag_drive_scale
        self._phase_lag_accum = (
            cfg.phase_lag_decay * self._phase_lag_accum + (1.0 - cfg.phase_lag_decay) * drive
        )

        # 4. Integrate phase (Euler). Source line 2905: phase += phaseV*dt*scale.
        self._theta = self._theta + self._phase_v * h * cfg.phase_integration_scale
        # Keep phases in [0, 2*pi) for numerical hygiene (does not affect dynamics).
        self._theta = np.mod(self._theta, 2.0 * np.pi)
        self._t += h

        # Recompute coherence post-integration for the reported R / spark gate.
        z2 = np.exp(1j * self._theta).mean()
        R = float(np.abs(z2))
        psi = float(np.angle(z2))

        sparks = self._maybe_fire(R, psi)

        dominant = self._last_dominant if sparks else self._most_aligned(psi)
        return TickResult(t=self._t, R=R, sparks=sparks, k=k_eff, dominant_node=dominant)

    # -- Spark gating & adaptive K --------------------------------------------
    def _maybe_fire(self, R: float, psi: float) -> list[Spark]:
        """Evaluate the spark gate for every node, then run the rate controller.

        A node fires iff: global coherence ``R*phi`` clears the floor AND the
        node's phase-lag accumulator is past ``delta_threshold`` AND a seeded RNG
        draw falls under the (rate-modulated) per-node probability.
        """
        cfg = self.cfg
        sparks: list[Spark] = []

        coherence = R * config.PHI
        # Measure current rate over the rolling window and derive the rate factor
        # BEFORE firing, matching the source (adaptiveSparkRate runs each frame).
        rate = self._current_rate()
        if rate < cfg.spark_min:
            rate_factor = cfg.rate_boost_below_min
        elif rate > cfg.spark_max:
            rate_factor = cfg.rate_damp_above_max
        else:
            rate_factor = 1.0

        if coherence > cfg.coherence_spark_floor:
            eligible = self._phase_lag_accum > cfg.delta_threshold
            if eligible.any():
                # Per-node alignment weight: nodes more aligned with the mean
                # field carry more "charge" and are likelier to fire.
                align = np.cos(self._theta - psi)  # in [-1, 1]
                p = cfg.spark_base_prob * np.clip(align, 0.0, 1.0) * coherence * rate_factor
                # One seeded draw per node -> deterministic given seed.
                draws = self._rng.random(self.n)
                fired = eligible & (draws < p)
                fired_idx = np.nonzero(fired)[0]
                for node in fired_idx:
                    n_i = int(node)
                    self._spark_counter += 1
                    self._spark_window.append(self._t)
                    # Firing partially discharges the accumulator (the "collapse").
                    # A partial discharge (not a hard zero) keeps a node that is
                    # firmly past threshold firing at a controllable cadence
                    # instead of starving for hundreds of ticks while it rebuilds.
                    self._phase_lag_accum[n_i] *= cfg.spark_discharge
                    self._last_dominant = n_i
                    sparks.append(
                        Spark(
                            spark_id=self._spark_counter,
                            t=self._t,
                            R=R,
                            dominant_node=n_i,
                            dominant_label=self._labels[n_i],
                        )
                    )

        self._update_coupling_pressure()
        return sparks

    def _current_rate(self) -> float:
        """Spark rate = sparks within the rolling window / window length."""
        cutoff = self._t - self.cfg.spark_window_sec
        while self._spark_window and self._spark_window[0] < cutoff:
            self._spark_window.popleft()
        return len(self._spark_window) / self.cfg.spark_window_sec

    def _update_coupling_pressure(self) -> None:
        """PID-like nudge of coupling pressure toward holding SPARK_TARGET.

        Source lines 1882-1885: proportional error * gentle gain, clamped.
        """
        cfg = self.cfg
        err = cfg.spark_target - self._current_rate()
        self._coupling_pressure += err * cfg.coupling_pressure_gain * cfg.coupling_pressure_sign
        self._coupling_pressure = float(
            np.clip(
                self._coupling_pressure,
                cfg.coupling_pressure_min,
                cfg.coupling_pressure_max,
            )
        )

    def _most_aligned(self, psi: float) -> int:
        """Index of the node whose phase is closest to the mean-field angle psi."""
        return int(np.argmax(np.cos(self._theta - psi)))


def _with_k(cfg: MOneConfig, k: float) -> MOneConfig:
    """Return a copy of ``cfg`` with ``k`` overridden (cfg is frozen)."""
    from dataclasses import replace

    return replace(cfg, k=k)
