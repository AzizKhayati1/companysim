# Diagnosis thresholds

How `detect_problems()` decides a simulation run has a problem worth
diagnosing. Code: [`src/companysim/ml/diagnostics.py`](../src/companysim/ml/diagnostics.py).

## Overview

Every simulation run produces a week-by-week (tick-by-tick) history —
active headcount, quits, mean burnout/engagement/turnover risk, etc.
`detect_problems()` scans that history against four independent
threshold checks. Each check that fires produces a `ProblemFlag`, which
then feeds into root-cause attribution and a recommendation. A run can
trigger zero, some, or all four checks.

Three of the four checks use a **rolling window** (default 3 ticks) to
compare the current value against the *recent* baseline rather than the
run's very first tick — so a slow, expected drift doesn't false-positive,
but a sharp move relative to the last few weeks does.

## The four checks

| # | Metric | Default threshold | Trigger condition | Window |
|---|--------|-------------------|---------------------|--------|
| 1 | `burnout_rate` | `0.15` (15%) | Value exceeds threshold at any tick | none — direct crossing |
| 2 | `mean_engagement` | `0.10` (absolute) | Drop from the recent 3-week peak &ge; threshold | 3 ticks |
| 3 | `mean_turnover_risk` | `0.10` (absolute) | Rise from the recent 3-week low &ge; threshold | 3 ticks |
| 4 | `quits_this_tick` | `2.0` (ratio) | At least 2x the trailing 3-week average, **and** at least 2 actual quits that week | 3 ticks |

### 1. Burnout rate — direct threshold

```python
crossings = history[history["burnout_rate"] > th["burnout_rate"]]
```

`burnout_rate` (produced upstream by the simulation, not by diagnostics)
is the fraction of the active workforce with individual burnout &ge; 0.7.
The check is a plain crossing — no rolling window — because burnout_rate
starts near-zero in a healthy org, so any crossing above 15% is already a
meaningful minority of the workforce in a bad state. The **first** tick
that crosses is reported, not the peak.

### 2. Engagement drop — rolling-peak comparison

```python
recent_peak = eng.rolling(window, min_periods=1).max().shift(1).fillna(eng.iloc[0])
drop = recent_peak - eng
```

For each tick, `recent_peak` is the highest engagement seen in the
*preceding* 3 ticks (the `.shift(1)` excludes the current tick itself, so
a metric can't be compared against its own value). The check fires at
whichever tick shows the single worst drop from that recent peak, if that
drop is &ge; 0.10 (on a 0&ndash;1 engagement scale).

### 3. Turnover risk rise — mirror of #2

Same mechanism, opposite direction: compares each tick against the
*lowest* turnover risk in the preceding 3 ticks, fires on the worst
(largest) rise if it's &ge; 0.10.

### 4. Quit spike — ratio vs. trailing average, with a noise floor

```python
trailing_mean = quits.rolling(window, min_periods=1).mean().shift(1)
ratio = quits / trailing_mean.replace(0, np.nan)
spikes = ratio[(ratio >= th["quit_spike_ratio"]) & (quits >= 2)]
```

Ratio-based rather than absolute, since "spiked" only means something
relative to what's normal for that org's size. The `quits >= 2` floor
exists specifically to stop small orgs from triggering on noise — without
it, a org that normally sees 0 quits/week would flag every single
resignation as an "infinite ratio spike."

## Severity scores

Each `ProblemFlag` also carries a `severity` in `[0, 1]`, clipped, used
for display/sorting (not part of the trigger condition — a flag either
fires or it doesn't). Formulas, per check:

- Burnout: `burnout_rate / threshold - 0.7`
- Engagement drop: `drop / threshold * 0.5`
- Turnover risk rise: `rise / threshold * 0.5`
- Quit spike: `ratio / threshold * 0.4`

These are deliberately simple linear scalings from "just barely crossed
the line" (near 0) toward "far past it" (toward 1) — not a calibrated
statistical severity, just a sort key for the UI.

## Overriding the defaults

```python
from companysim.ml.diagnostics import detect_problems, DEFAULT_THRESHOLDS

detect_problems(history, thresholds={"burnout_rate": 0.10, "quit_spike_ratio": 1.5})
```

Any subset of keys can be overridden; omitted keys fall back to
`DEFAULT_THRESHOLDS`. The rolling `window` (ticks) is a separate
parameter, default `3`, shared by checks 2&ndash;4.

## Why these specific numbers

Not statistically fitted — chosen from the sim's own calibration runs
earlier in the project:

- **15% burnout rate**: in a healthy baseline run, burnout_rate sits near
  0&ndash;1%. 15% represents a clear minority of the workforce in a bad
  state, not sensitivity to normal noise.
- **0.10 absolute** for engagement/turnover-risk moves: both metrics
  operate on a 0&ndash;1 scale with typical week-to-week noise in the
  0.01&ndash;0.03 range from the underlying agent dynamics; 0.10 is well
  above that noise floor.
- **2x quit ratio + 2-quit floor**: catches a real cluster (e.g. an
  8-quit week against a ~2/week baseline, as seen in test runs) without
  flagging every ordinary single resignation.

These are reasonable starting points, not validated against real
attrition data (there isn't any — this is a synthetic system). If a
particular org size or scenario is producing too many or too few
detections, override the thresholds per-call rather than treating the
defaults as fixed.

## Tests

[`tests/test_diagnostics.py`](../tests/test_diagnostics.py) covers: no
false positives on a flat history, all four checks firing on a
deliberately spiky synthetic history, and severity scores staying within
`[0, 1]`.
