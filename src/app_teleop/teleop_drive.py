"""Gears, speed ramp and speed-dependent steering for normalized stick input (#37).

Plain Python (no ROS), so the math can be tested without a robot. The ROS side is
teleop_mux.py, which feeds it /teleop/<source>/stick and /teleop/<source>/gear.

Per tick (dt seconds), with throttle, steer in [-1, 1] (steer + = left):
  v_target = clamp(throttle, 1) * gear_speeds[gear - 1], capped at max_linear
  v        ramps towards v_target: at `accel` while |v| grows (same sign), at `decel`
           while |v| shrinks (stick released, lower gear, or towards 0 before reversing)
  steer_f  follows steer at most `steer_rate` per second
  kappa_max(v) = min(1 / min_turn_radius, a_lat_max / v^2)      [1/m]
  kappa    = steer_f * kappa_max(|v|)
  omega    = v * kappa, clamped to max_angular                    [rad/s]
so the lateral acceleration v * omega = v^2 * kappa never exceeds a_lat_max. Reversing
(v < 0) steers like a car: steer left while backing up gives omega < 0.

Immediate zero (deadman, STOP, mode or source change) is `zero()`: v and steer_f jump
to 0, no ramp.
"""
import math

GEAR_CMDS = ('up', 'down')


def clamp(x, limit):
    """x limited to [-limit, limit]; non-finite -> 0."""
    return max(-limit, min(limit, x)) if math.isfinite(x) else 0.0


def towards(x, target, max_step):
    return x + clamp(target - x, max_step)


def kappa_max(v, a_lat_max, min_turn_radius):
    """Largest allowed curvature [1/m] at speed v [m/s]."""
    k_lock = 1.0 / min_turn_radius
    v2 = v * v
    return k_lock if v2 <= 0.0 else min(k_lock, a_lat_max / v2)


def parse_gear(text, gear, n_gears):
    """New gear for a /teleop/<src>/gear command, or None if the text is not one.

    'up' / 'down' step by one and stop at 1 and n_gears; '1'..'n' select directly."""
    t = text.strip().lower()
    if t == 'up':
        return min(gear + 1, n_gears)
    if t == 'down':
        return max(gear - 1, 1)
    if t in {str(g) for g in range(1, n_gears + 1)}:   # ASCII '1'..'n' only
        return int(t)
    return None


class DriveParams:
    def __init__(self, gear_speeds=(0.15, 0.30, 0.50, 0.80), accel=0.3, decel=0.5,
                 a_lat_max=0.5, min_turn_radius=1.0, steer_rate=2.0):
        self.gear_speeds = [float(g) for g in gear_speeds]
        self.accel = float(accel)
        self.decel = float(decel)
        self.a_lat_max = float(a_lat_max)
        self.min_turn_radius = float(min_turn_radius)
        self.steer_rate = float(steer_rate)

    def problems(self):
        """Why these values can't be used, or [] if they can."""
        bad = []
        if not self.gear_speeds:
            bad.append('gear_speeds is empty')
        if any(not (math.isfinite(g) and g > 0) for g in self.gear_speeds):
            bad.append('gear_speeds must all be > 0')
        for name in ('accel', 'decel', 'a_lat_max', 'min_turn_radius', 'steer_rate'):
            v = getattr(self, name)
            if not (math.isfinite(v) and v > 0):
                bad.append(f'{name} must be > 0')
        return bad


class DriveCore:
    def __init__(self, params=None):
        self.p = params or DriveParams()
        self.gear = 1
        self.v = 0.0          # ramped forward speed, m/s (what goes out as linear.x)
        self.steer_f = 0.0    # rate-limited steer, [-1, 1]
        self.v_target = 0.0
        self.kappa_max = kappa_max(0.0, self.p.a_lat_max, self.p.min_turn_radius)

    @property
    def n_gears(self):
        return len(self.p.gear_speeds)

    def set_params(self, params):
        self.p = params
        self.gear = min(self.gear, self.n_gears)

    def shift(self, text):
        """Apply a gear command; returns the new gear, or None if not understood."""
        g = parse_gear(text, self.gear, self.n_gears)
        if g is not None:
            self.gear = g
        return g

    def reset_gear(self):
        self.gear = 1

    def zero(self):
        """Immediate stop: no ramp, steering back to centre."""
        self.v = 0.0
        self.steer_f = 0.0
        self.v_target = 0.0
        self.kappa_max = kappa_max(0.0, self.p.a_lat_max, self.p.min_turn_radius)

    def hold(self, v):
        """Another input (cmd_vel) drives: a later stick ramps on from that speed."""
        self.v = v if math.isfinite(v) else 0.0
        self.steer_f = 0.0
        self.v_target = self.v
        self.kappa_max = kappa_max(self.v, self.p.a_lat_max, self.p.min_turn_radius)

    def step(self, throttle, steer, dt, max_linear, max_angular):
        """One tick: returns (linear.x m/s, angular.z rad/s)."""
        p = self.p
        dt = max(0.0, dt)
        self.v_target = clamp(clamp(throttle, 1.0) * p.gear_speeds[self.gear - 1], max_linear)
        target = self.v_target
        if self.v * target < 0.0:          # reversing direction: brake to 0 first
            target, rate = 0.0, p.decel
        elif abs(target) > abs(self.v):
            rate = p.accel
        else:
            rate = p.decel
        self.v = clamp(towards(self.v, target, rate * dt), max_linear)
        if abs(self.v) < 1e-9:             # float residue after braking: exactly 0
            self.v = 0.0
        self.steer_f = clamp(towards(self.steer_f, clamp(steer, 1.0), p.steer_rate * dt), 1.0)
        self.kappa_max = kappa_max(self.v, p.a_lat_max, p.min_turn_radius)
        omega = clamp(self.v * self.steer_f * self.kappa_max, max_angular)
        return self.v, omega

    def steer_limited(self):
        return self.kappa_max < 1.0 / self.p.min_turn_radius
