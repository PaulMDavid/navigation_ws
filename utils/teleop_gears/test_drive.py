"""Unit tests of teleop_drive.py: gears, speed ramp, kappa_max, lateral-acceleration
bound, steer rate limit, max_angular clamp, reverse sign. No ROS needed; fake time."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.environ.get('APP_DIR', os.path.join(os.path.dirname(__file__), '../../src/app_teleop')))
from teleop_drive import DriveCore, DriveParams, kappa_max, parse_gear  # noqa: E402

DT = 0.05            # teleop_mux rate 20 Hz
MAX_LIN, MAX_ANG = 0.8, 1.0
GEARS = [0.15, 0.30, 0.50, 0.80]


def core(gear=1, **kw):
    c = DriveCore(DriveParams(**kw))
    c.gear = gear
    return c


def run(c, throttle, steer, secs, max_lin=MAX_LIN, max_ang=MAX_ANG):
    """[(t, v, omega)] over secs at 20 Hz."""
    out = []
    for i in range(int(round(secs / DT))):
        v, w = c.step(throttle, steer, DT, max_lin, max_ang)
        out.append(((i + 1) * DT, v, w))
    return out


def first_time(samples, pred):
    return next((t for t, v, w in samples if pred(v, w)), None)


# ── gears ───────────────────────────────────────────────────────────────────
def test_defaults_match_issue():
    p = DriveParams()
    assert p.gear_speeds == GEARS
    assert (p.accel, p.decel, p.a_lat_max, p.min_turn_radius, p.steer_rate) == (0.3, 0.5, 0.5, 1.0, 2.0)
    assert [round(g * 3.6, 2) for g in p.gear_speeds] == [0.54, 1.08, 1.8, 2.88]
    assert DriveCore().gear == 1


def test_gear_up_down_clamp():
    c = core()
    seq = [c.shift('up') for _ in range(5)]
    assert seq == [2, 3, 4, 4, 4]
    seq = [c.shift('down') for _ in range(5)]
    assert seq == [3, 2, 1, 1, 1]


@pytest.mark.parametrize('text,gear', [('1', 1), ('2', 2), ('3', 3), ('4', 4), (' UP ', 3), ('Down', 1)])
def test_gear_direct_and_case(text, gear):
    c = core(gear=2)
    assert c.shift(text) == gear and c.gear == gear


@pytest.mark.parametrize('text', ['0', '5', '-1', '2.0', '', 'fast', 'upp', '١'])
def test_gear_invalid_ignored(text):
    c = core(gear=3)
    assert c.shift(text) is None and c.gear == 3


def test_parse_gear_follows_gear_count():
    assert parse_gear('3', 1, 2) is None
    assert parse_gear('up', 2, 2) == 2


def test_fewer_gears_clamps_current():
    c = core(gear=4)
    c.set_params(DriveParams(gear_speeds=[0.1, 0.2]))
    assert c.gear == 2


def test_reset_gear():
    c = core(gear=4)
    c.reset_gear()
    assert c.gear == 1


def test_upshift_mid_drive_only_raises_target():
    c = core(gear=1)
    run(c, 1.0, 0.0, 2.0)
    assert c.v == pytest.approx(0.15)
    c.shift('up')
    s = run(c, 1.0, 0.0, 0.1)
    assert c.v_target == pytest.approx(0.30)
    assert s[-1][1] == pytest.approx(0.15 + 0.3 * 0.1)       # ramps at accel, no jump


def test_downshift_decelerates_at_decel():
    c = core(gear=4)
    run(c, 1.0, 0.0, 4.0)
    assert c.v == pytest.approx(0.8)
    c.shift('1')
    s = run(c, 1.0, 0.0, 1.3)
    assert s[0][1] == pytest.approx(0.8 - 0.5 * DT)
    assert first_time(s, lambda v, w: v <= 0.15 + 1e-9) == pytest.approx(0.65 / 0.5, abs=DT)
    assert c.v == pytest.approx(0.15)


# ── ramp ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('gear', [1, 2, 3, 4])
def test_ramp_up_timing(gear):
    c = core(gear=gear)
    s = run(c, 1.0, 0.0, 4.0)
    vmax = GEARS[gear - 1]
    t_full = first_time(s, lambda v, w: v >= vmax - 1e-9)
    assert t_full == pytest.approx(vmax / 0.3, abs=DT)       # accel 0.3 m/s^2
    for (t0, v0, _), (t1, v1, _) in zip(s, s[1:]):
        assert v1 - v0 <= 0.3 * DT + 1e-9
    assert max(v for _, v, _ in s) == pytest.approx(vmax)


def test_ramp_down_on_release():
    c = core(gear=4)
    run(c, 1.0, 0.0, 4.0)
    s = run(c, 0.0, 0.0, 2.0)
    t_zero = first_time(s, lambda v, w: v <= 1e-9)
    assert t_zero == pytest.approx(0.8 / 0.5, abs=DT)        # decel 0.5 m/s^2
    for (_, v0, _), (_, v1, _) in zip(s, s[1:]):
        assert v0 - v1 <= 0.5 * DT + 1e-9
    assert c.v == 0.0


def test_partial_throttle():
    c = core(gear=3)
    run(c, 0.5, 0.0, 3.0)
    assert c.v == pytest.approx(0.25) and c.v_target == pytest.approx(0.25)


def test_reverse_brakes_then_accelerates():
    c = core(gear=2)
    run(c, 1.0, 0.0, 2.0)
    assert c.v == pytest.approx(0.30)
    s = run(c, -1.0, 0.0, 3.0)
    t_zero = first_time(s, lambda v, w: v <= 1e-9)
    assert t_zero == pytest.approx(0.30 / 0.5, abs=DT)       # braking at decel
    t_rev = first_time(s, lambda v, w: v <= -0.30 + 1e-9)
    assert t_rev - t_zero == pytest.approx(0.30 / 0.3, abs=DT)  # then accel backwards
    assert c.v == pytest.approx(-0.30)


def test_zero_is_immediate():
    c = core(gear=4)
    run(c, 1.0, 1.0, 4.0)
    c.zero()
    assert (c.v, c.steer_f, c.v_target) == (0.0, 0.0, 0.0)
    assert c.kappa_max == 1.0
    v, w = c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)             # ramps again from 0
    assert v == pytest.approx(0.3 * DT)


def test_max_linear_caps_gear():
    c = core(gear=4)
    run(c, 1.0, 0.0, 4.0, max_lin=0.5)
    assert c.v == pytest.approx(0.5) and c.v_target == pytest.approx(0.5)


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_non_finite_stick_is_zero(bad):
    c = core(gear=2)
    v, w = c.step(bad, bad, DT, MAX_LIN, MAX_ANG)
    assert (v, w, c.v_target, c.steer_f) == (0.0, 0.0, 0.0, 0.0)


def test_stick_beyond_one_is_clamped():
    c = core(gear=1)
    run(c, 5.0, 5.0, 3.0)
    assert c.v == pytest.approx(0.15) and c.steer_f == 1.0


def test_large_dt_ramp_is_bounded():
    c = core(gear=4)
    v, _ = c.step(1.0, 0.0, 0.1, MAX_LIN, MAX_ANG)
    assert v == pytest.approx(0.03)


# ── curvature ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize('v,expect', [(0.0, 1.0), (0.15, 1.0), (0.5, 1.0), (math.sqrt(0.5), 1.0),
                                      (0.8, 0.5 / 0.64), (-0.8, 0.5 / 0.64), (2.0, 0.125)])
def test_kappa_max_formula(v, expect):
    assert kappa_max(v, 0.5, 1.0) == pytest.approx(expect)


def test_kappa_max_other_params():
    assert kappa_max(1.0, 0.3, 2.0) == pytest.approx(0.3)
    assert kappa_max(0.2, 0.3, 2.0) == pytest.approx(0.5)


def test_steer_limited_only_above_crossover():
    # kappa_max < 1/R  <=>  v > sqrt(a_lat_max * R) = 0.707 m/s with the defaults
    for gear, limited in ((1, False), (2, False), (3, False), (4, True)):
        c = core(gear=gear)
        run(c, 1.0, 1.0, 4.0)
        assert c.steer_limited() is limited, gear


@pytest.mark.parametrize('a_lat,radius', [(0.5, 1.0), (0.3, 0.5), (1.0, 2.0)])
def test_lateral_accel_never_above_limit(a_lat, radius):
    """Sweep v (via gear/throttle) and steer, with the ramp and steer rate in the loop:
    |v * omega| <= a_lat_max every tick, and omega = v * steer_f * kappa_max."""
    worst = 0.0
    for gear in (1, 2, 3, 4):
        for throttle in (-1.0, -0.6, -0.3, 0.3, 0.6, 1.0):
            for steer in (-1.0, -0.5, -0.1, 0.1, 0.5, 1.0):
                c = core(gear=gear, a_lat_max=a_lat, min_turn_radius=radius)
                for t, v, w in run(c, throttle, steer, 4.0, max_lin=10.0, max_ang=100.0) + \
                        run(c, 0.0, -steer, 2.0, max_lin=10.0, max_ang=100.0):
                    lat = abs(v * w)
                    worst = max(worst, lat)
                    assert lat <= a_lat + 1e-9
                    assert abs(w) <= abs(v) / radius + 1e-9   # never tighter than the lock
    assert worst > 0.0


def test_full_lock_at_low_speed():
    c = core(gear=1)
    run(c, 1.0, 1.0, 2.0)
    v, w = c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)
    assert w == pytest.approx(0.15 * 1.0)                      # omega = v / R


def test_lateral_limit_at_gear4():
    c = core(gear=4)
    run(c, 1.0, 1.0, 4.0)
    v, w = c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)
    assert v == pytest.approx(0.8)
    assert w == pytest.approx(0.5 / 0.8)                       # a_lat / v
    assert v * w == pytest.approx(0.5)


def test_steer_sign_left_positive():
    c = core(gear=2)
    run(c, 1.0, 1.0, 2.0)
    assert c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)[1] > 0
    c = core(gear=2)
    run(c, 1.0, -1.0, 2.0)
    assert c.step(1.0, -1.0, DT, MAX_LIN, MAX_ANG)[1] < 0


def test_reverse_steers_like_a_car():
    c = core(gear=2)
    run(c, -1.0, 1.0, 2.0)
    v, w = c.step(-1.0, 1.0, DT, MAX_LIN, MAX_ANG)
    assert v == pytest.approx(-0.30)
    assert w == pytest.approx(-0.30)                           # steer left backing up -> omega < 0


def test_no_turn_at_standstill():
    c = core(gear=4)
    v, w = c.step(0.0, 1.0, DT, MAX_LIN, MAX_ANG)
    assert (v, w) == (0.0, 0.0)


# ── max_angular clamp ───────────────────────────────────────────────────────
@pytest.mark.parametrize('max_ang', [0.1, 0.05, 1.0])
def test_max_angular_is_final_clamp(max_ang):
    for gear in (1, 2, 3, 4):
        c = core(gear=gear)
        for _, v, w in run(c, 1.0, 1.0, 4.0, max_ang=max_ang) + run(c, -1.0, -1.0, 4.0, max_ang=max_ang):
            assert abs(w) <= max_ang + 1e-12


def test_crab_max_angular_bites():
    c = core(gear=3)
    run(c, 1.0, 1.0, 3.0, max_ang=0.1)
    v, w = c.step(1.0, 1.0, DT, MAX_LIN, 0.1)
    assert v == pytest.approx(0.5) and w == pytest.approx(0.1)   # would be 0.5 without the clamp


# ── steer rate ──────────────────────────────────────────────────────────────
def test_steer_rate_centre_to_lock():
    c = core(gear=1)
    run(c, 1.0, 0.0, 1.0)
    steer = []
    for _ in range(20):
        c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)
        steer.append(c.steer_f)
    assert steer[0] == pytest.approx(2.0 * DT)
    assert next(i for i, s in enumerate(steer) if s >= 1.0 - 1e-9) + 1 == pytest.approx(0.5 / DT, abs=1)
    for a, b in zip(steer, steer[1:]):
        assert b - a <= 2.0 * DT + 1e-9


def test_steer_flick_lock_to_lock():
    c = core(gear=1)
    run(c, 1.0, 1.0, 1.0)
    assert c.steer_f == 1.0
    steer = []
    for _ in range(25):
        c.step(1.0, -1.0, DT, MAX_LIN, MAX_ANG)
        steer.append(c.steer_f)
    t = (next(i for i, s in enumerate(steer) if s <= -1.0 + 1e-9) + 1) * DT
    assert t == pytest.approx(1.0, abs=DT)                     # 2 units at 2.0 /s


def test_steer_rate_param():
    c = core(gear=1, steer_rate=1.0)
    c.step(1.0, 1.0, DT, MAX_LIN, MAX_ANG)
    assert c.steer_f == pytest.approx(DT)


# ── params ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('kw', [dict(gear_speeds=[]), dict(gear_speeds=[0.1, 0.0]), dict(accel=0.0),
                                dict(decel=-1.0), dict(a_lat_max=math.nan), dict(min_turn_radius=0.0),
                                dict(steer_rate=0.0)])
def test_bad_params(kw):
    assert DriveParams(**kw).problems()


def test_good_params():
    assert DriveParams().problems() == []


def test_hold_takes_over_speed():
    c = core(gear=4)
    c.hold(0.4)
    v, _ = c.step(1.0, 0.0, DT, MAX_LIN, MAX_ANG)
    assert v == pytest.approx(0.4 + 0.3 * DT)
