"""MOne kernel constants — extracted from the AETHER ``MOne`` source.

Every magic number the kernel needs lives here, named, so that the dynamics in
:mod:`avatar.mone.kernel` read as physics rather than a wall of literals. The
defaults are the *real* (load-bearing) constants pulled out of the original
single-file ``AI_consciousness_MOne_1.html`` Kuramoto kernel — the cosmetic
physics (Hawking temperature, NFW dark matter, Regge trajectories, the ~37 other
"forces") were decorative multipliers and are deliberately NOT reproduced.

Provenance (file: ``AI_consciousness_MOne_1.html``):

- ``PHI``                 line 962  ``const PHI = 1.6180339887``
- ``K_KURAMOTO``          line 998  ``const K_KURAMOTO = 2.2``  (slightly > K_c)
- ``DELTA_THRESHOLD``     line 1128 ``const DELTA_THRESHOLD = PI / PHI``  (~1.942 rad)
- ``SPARK_TARGET``        line 1867 ``const SPARK_TARGET = 49``  (ideal sparks/sec)
- ``SPARK_MIN/MAX``       line 1868 ``const SPARK_MIN = 40, SPARK_MAX = 70``
- coupling-pressure PID   line 1884 ``couplingPressure += err * 0.0004``
                          line 1885 clamp ``Math.max(0.3, Math.min(2.8, ...))``
- order parameter R       line 1922-1923 ``R = sqrt(sx**2+sy**2)/N`` over ``e^{i*theta}``
- mean-field Kuramoto     line 2483-2490 ``(K/N)*sin(Psi-theta)*fieldMag``
- phase-lag accumulator   line 2700-2701 ``phaseLagAccum += |delta|*dt*speed*0.1`` then ``*= 0.998``
- phase integration       line 2905 ``s.phase += s.phaseV * dt * speed * 0.6``
- velocity clamp          line 2903 ``|phaseV| <= 1.5``
- region labels (11)      line 1328-1351 ``REGION_DEFS``

See the module docstring of :mod:`avatar.mone.kernel` for how these compose into
the deterministic per-tick update.
"""

from __future__ import annotations

import math
from typing import Final

# -- Golden ratio & derived threshold -----------------------------------------
# phi -- the golden ratio. Source line 962.
PHI: Final[float] = 1.6180339887

# delta-accumulation spark threshold = pi/phi ~= 1.942 rad. Source line 1128.
# When a node's accumulated absolute phase-lag crosses this, it is at a "pause"
# point (all harmonics momentarily cancel) -> it becomes spark-eligible.
DELTA_THRESHOLD: Final[float] = math.pi / PHI

# -- Topology -----------------------------------------------------------------
# Default node count -- the 11 brain-region labels of the MOne source
# (REGION_DEFS, lines 1328-1351). Used as the default N when no explicit
# ``omegas`` array is supplied.
DEFAULT_N_NODES: Final[int] = 11

# The 11 region labels in source order. ``dominant_node`` on a Spark indexes
# into this list so downstream can map MOTOR->step, CONCEPT->speak, etc.
REGION_LABELS: Final[tuple[str, ...]] = (
    "META",  # meta -- top-level executive / conscious decision
    "WORK",  # work -- working memory
    "PRED",  # pred -- predictive
    "MOTOR",  # motor -- motor cortex    -> drives NPC movement
    "SENS",  # sens -- sensory cortex
    "ASSOC",  # assoc -- association hub
    "FEAT",  # feat -- feature layer
    "CONCEPT",  # concept -- concept layer -> drives NPC speech
    "CEREB",  # cereb -- cerebellum
    "REFLEX",  # reflex -- reflex arc
    "BRAIN",  # brain -- brainstem (ground state)
)

# -- Kuramoto dynamics --------------------------------------------------------
# Global coupling K. K_c ~= 2/(pi*g(0)) ~= 2.0 for the unimodal case, so 2.2
# sits *slightly above* critical -> partial synchronization (not full lock, not
# incoherent). Source line 998.
K_KURAMOTO: Final[float] = 2.2

# Integration timestep. The MOne source ran on wall-clock frame deltas
# (~0.016 s @ 60 fps, source line 2263) which is non-deterministic; we fix it.
# The brief specifies dt ~= 0.05 (Euler integration).
DEFAULT_DT: Final[float] = 0.05

# Phase-integration scale: source advances ``phase += phaseV * dt * speed * 0.6``
# (line 2905). The 0.6 keeps a node from advancing more than ~one step's worth
# of phase per tick at the velocity clamp.
PHASE_INTEGRATION_SCALE: Final[float] = 0.6

# Hard clamp on |dtheta/dt|. Source line 2903: ``|phaseV| <= 1.5`` ("physical
# boundary -- field amplitude limit, not damping").
PHASE_VELOCITY_CLAMP: Final[float] = 1.5

# Default natural-frequency band [lo, hi) for omega when sampled from the seeded
# RNG. Mirrors the source string init ``phaseV in +/-[0.1, 0.5)`` (line 1612):
# magnitude in [0.1, 0.5), random sign.
OMEGA_ABS_LO: Final[float] = 0.1
OMEGA_ABS_HI: Final[float] = 0.5

# -- Phase-lag accumulator (spark predictor) ----------------------------------
# The source integrated |delta| as an unbounded running sum with slow decay
# (lines 2700-2701: ``phaseLagAccum += |delta|*dt*speed*0.1`` then ``*= 0.998``).
# At 60 fps the per-frame decay kept that sum bounded inside a noisy, never-fully
# -locking field.
#
# CALIBRATION (deviation from source, see kernel docstring): a clean 11-node
# mean-field kernel at dt=0.05 either locks cleanly (|delta| -> 0, the source's
# 0.1 gain never reaches DELTA_THRESHOLD -> zero sparks) or, with an unbounded
# integral, makes the ignition step heavily seed-dependent. We instead drive an
# *exponential moving average* (EMA) of the phase drive: bounded, reaching steady
# state in ~1/(1-decay) ticks, so eligibility responds within ~tens of ticks for
# EVERY seed. The golden threshold DELTA_THRESHOLD = pi/phi still gates
# eligibility. PHASE_LAG_DECAY is the EMA retention; the per-tick drive is scaled
# by PHASE_LAG_DRIVE_SCALE. Source values: gain 0.1, decay 0.998 (unbounded sum).
PHASE_LAG_DECAY: Final[float] = 0.9
PHASE_LAG_DRIVE_SCALE: Final[float] = 9.0

# Weight on the *frequency-detuning* term in the accumulator drive. A pure
# instantaneous phase-lag |psi - theta_i| vanishes when the field locks (R -> 1),
# which starves sparks for any seed whose natural frequencies happen to
# synchronize cleanly -- making the spark stream fragile across seeds. We add the
# persistent detuning |phaseV_i - mean(phaseV)| (a node's residual frequency
# offset from the pack, which survives partial sync) so spark eligibility is
# robust for every seed. Set to 0.0 to recover the pure source phase-lag drive.
PHASE_LAG_DETUNE_WEIGHT: Final[float] = 1.0

# -- Adaptive K -- PID-like spark-rate controller -----------------------------
# Target spark rate (sparks per SPARK_WINDOW_SEC). 49 = 7^2 is the source's
# "resonant integer"; biologically ~40-70 Hz cortical gamma. Source line 1867.
SPARK_TARGET: Final[float] = 49.0
# Clamp band for the measured/target rate. Source line 1868.
SPARK_MIN: Final[float] = 40.0
SPARK_MAX: Final[float] = 70.0
# Rolling window over which spark rate is measured, in seconds. Source line 1876
# filtered ``now - ts < 2000`` ms -> a 2-second window.
SPARK_WINDOW_SEC: Final[float] = 2.0

# Controller gain on the coupling pressure that multiplies K. Source line 1884:
# ``couplingPressure += err * 0.0004``. We use a slightly stronger proportional
# gain so the controller settles within a few rolling windows rather than
# thousands of ticks. Source value: 0.0004.
COUPLING_PRESSURE_GAIN: Final[float] = 0.002

# Controller sign. In the 28-string source, raising coupling made coherence peak
# more often -> MORE sparks, so error (target - rate) added to pressure. In the
# clean 11-node mean-field kernel the spark rate is a UNIMODAL function of K_eff:
# it peaks at partial sync (K_eff ~ 0.8-1.0, R ~ 0.85-0.94) and falls to zero at
# both K_eff -> 0 (incoherent, coherence below the floor) and K_eff >~ 2 (locked,
# no residual lag). On the productive left flank that the controller is clamped
# to (see below), higher K -> fewer sparks, so to raise the rate the controller
# must LOWER K: a -1 sign (deviation from source). +1 reproduces source behavior.
COUPLING_PRESSURE_SIGN: Final[float] = -1.0
# Coupling-pressure clamp. Source line 1885: ``max(0.3, min(2.8, ...))``.
#
# DEVIATION: with the source's wide [0.3, 2.8] band an inverted proportional
# controller is unstable -- it rails to a clamp and lands either in the locked
# dead zone (K_eff = K*pressure >~ 2, zero sparks) or the incoherent floor (R
# below 0.618). We clamp pressure to a NARROW band that keeps K_eff = 2.2*pressure
# on the productive left flank of the unimodal rate curve: pressure in [0.3, 0.66]
# -> K_eff in [0.66, 1.45], where rate decreases monotonically with K so the -1
# controller is stable. INIT = 0.45 starts K_eff ~ 1.0, near the spark peak, for
# fast (< ~320-tick) ignition on every seed. Source values: 0.3, 2.8, init 1.0.
COUPLING_PRESSURE_MIN: Final[float] = 0.3
COUPLING_PRESSURE_MAX: Final[float] = 0.66
COUPLING_PRESSURE_INIT: Final[float] = 0.45

# -- Spark firing -------------------------------------------------------------
# A node is spark-*eligible* when coherence = R*phi > this. Source line 2145:
# ``if (coherence > 1.0 ...)`` -- i.e. R > 1/phi ~= 0.618, the golden coherence
# floor (the phi-threshold tick on the source's phase meter, line 2239).
COHERENCE_SPARK_FLOOR: Final[float] = 1.0

# When the measured rate is below SPARK_MIN the source boosts spark probability
# (x1.4), and throttles hard above SPARK_MAX (x0.15). Source lines 2146-2148.
RATE_BOOST_BELOW_MIN: Final[float] = 1.4
RATE_DAMP_ABOVE_MAX: Final[float] = 0.15

# Fraction of a node's phase-lag accumulator retained after it fires (the
# "collapse" discharge). The source kept the accumulator and let it decay; we
# multiply by this on firing so a node firmly past threshold keeps a tunable
# cadence rather than starving while it rebuilds from zero. 0.6 = lose 40% per
# spark. (No direct source constant -- this replaces the source's implicit
# decay-only discharge.)
SPARK_DISCHARGE: Final[float] = 0.5
