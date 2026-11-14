"""robot_control's state on the rover, guessed from the /joy presses orintwo sends.

Plain Python (no ROS), so the press sequencing can be tested without a robot. The ROS
side is rover_arming.py.

robot_control boots in manual input (/manual_cmd_vel) + crab steering + stopped. It
reads /joy (sensor_msgs/Joy, exactly 17 buttons):
  button 1   input -> autonomous (/cmd_vel, what teleop_mux publishes)
  button 16  toggles Ackermann-only <-> crab
  button 2   resume motion
Each press is one Joy with that button = 1, then one all-zero Joy, `gap` seconds apart.
Commands run one at a time; one arriving mid-sequence waits in the queue. What a
command presses is decided when it starts, from the tracked state at that moment, so
`steer_ackermann` twice presses 16 once.
"""
from collections import deque

N_AXES = 8
N_BUTTONS = 17
BTN_INPUT_AUTO = 1
BTN_STEER_TOGGLE = 16
BTN_RESUME = 2

BOOT = {'input': 'manual', 'steering': 'crab', 'motion': 'stopped'}
COMMANDS = ('input_auto', 'steer_ackermann', 'steer_crab', 'resume', 'arm', 'reset')
OTHER_STEERING = {'crab': 'ackermann', 'ackermann': 'crab'}


def buttons(pressed=None):
    """The 17 button values of one Joy message, `pressed` = 1, the rest 0."""
    b = [0] * N_BUTTONS
    if pressed is not None:
        b[pressed] = 1
    return b


class RoverTracker:
    def __init__(self, gap=0.2, max_queue=8):
        self.gap = gap
        self.max_queue = max_queue
        self.state = dict(BOOT)
        self.queue = deque()        # (command, source) waiting to start
        self.steps = deque()        # current command: (buttons or None, effects or None)
        self.next_t = None          # earliest time the next Joy may go out
        self.last_cmd = None
        self.last_cmd_t = None
        self.last_cmd_by = None
        self.presses = 0            # presses sent by last_cmd
        self.rejected = None

    # ── input ────────────────────────────────────────────────────────────────

    def submit(self, cmd, source, active_source):
        """Queue `cmd` from `source`. Returns None if accepted, else the reason."""
        reason = None
        if cmd not in COMMANDS:
            reason = f'unknown command {cmd!r} from {source}'
        elif active_source is None:
            reason = f'{cmd} from {source} refused: teleop_mux source unknown (no /teleop/state)'
        elif source != active_source:
            reason = f'{cmd} from {source} refused: active source is {active_source}'
        elif len(self.queue) >= self.max_queue:
            reason = f'{cmd} from {source} refused: {len(self.queue)} commands already queued'
        if reason is None:
            self.queue.append((cmd, source))
        self.rejected = reason
        return reason

    def busy(self):
        return bool(self.steps or self.queue)

    # ── sequencing ───────────────────────────────────────────────────────────

    def plan(self, cmd):
        """Steps for `cmd` from the current tracked state: a press is (button, effects),
        a state change without a press is (None, effects)."""
        steering = self.state['steering']
        if cmd == 'input_auto':
            return [(BTN_INPUT_AUTO, {'input': 'autonomous'})]
        if cmd in ('steer_ackermann', 'steer_crab'):
            want = cmd.split('_')[1]
            if steering == want:
                return [(None, {'steering': want})]   # no press; still re-sends the mux limit
            return [(BTN_STEER_TOGGLE, {'steering': want})]
        if cmd == 'resume':
            return [(BTN_RESUME, {'motion': 'running'})]
        if cmd == 'arm':
            steer = ((None, {'steering': 'ackermann'}) if steering == 'ackermann'
                     else (BTN_STEER_TOGGLE, {'steering': 'ackermann'}))
            return [(BTN_INPUT_AUTO, {'input': 'autonomous'}), steer,
                    (BTN_RESUME, {'motion': 'running'})]
        if cmd == 'reset':
            return [(None, dict(BOOT))]
        raise ValueError(cmd)

    def step(self, now):
        """Advance by the clock. Returns events, in order:
          ('joy', [17 buttons])     publish this Joy (axes all zero)
          ('steering', 'crab'|...)  tracked steering was set: update teleop_mux max_angular
        At most one Joy per call, and never sooner than `gap` after the previous one."""
        events = []
        while True:
            if self.steps:
                btns, effects = self.steps[0]
                if btns is not None:
                    if self.next_t is not None and now < self.next_t:
                        break
                    events.append(('joy', btns))
                    self.next_t = now + self.gap
                self.steps.popleft()
                if effects is not None:
                    if btns is not None:
                        self.presses += 1
                    self.state.update(effects)
                    if 'steering' in effects:
                        events.append(('steering', effects['steering']))
                if btns is not None:
                    break
                continue
            if not self.queue:
                break
            cmd, source = self.queue.popleft()
            self.last_cmd, self.last_cmd_t, self.last_cmd_by = cmd, now, source
            self.presses = 0
            for button, effects in self.plan(cmd):
                if button is None:
                    self.steps.append((None, effects))
                else:
                    self.steps.append((buttons(button), effects))
                    self.steps.append((buttons(), None))
        return events

    # ── report ───────────────────────────────────────────────────────────────

    def report(self, now):
        """The /teleop/rover_state JSON fields."""
        age = None if self.last_cmd_t is None else round(now - self.last_cmd_t, 1)
        return {
            'tracked': True,
            'input': self.state['input'],
            'steering': self.state['steering'],
            'motion': self.state['motion'],
            'last_cmd': self.last_cmd,
            'last_cmd_age': age,
            'last_cmd_by': self.last_cmd_by,
            'presses': self.presses,
            'rejected': self.rejected,
        }
