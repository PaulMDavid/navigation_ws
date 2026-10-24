// Rover teleop over foxglove_bridge (Foxglove WebSocket protocol, subprotocol foxglove.sdk.v1).
// Publishes /teleop/phone/cmd_vel at 10 Hz (the robot's deadman needs a steady stream)
// and /teleop/phone/set_mode; shows /teleop/state as the robot reports it.
// No external libraries: on the robot's access point the phone has no internet.
'use strict';

const PARAMS = new URLSearchParams(location.search);
const URL_WS = PARAMS.get('ws') || `ws://${location.hostname || '10.42.0.1'}:8765`;
const SEND_HZ = 10;
const STATE_STALE_MS = 1000;
const CH_CMD = 1, CH_MODE = 2;  // client channel ids
const SUB_STATE = 1;            // subscription id

const $ = (id) => document.getElementById(id);
const enc = new TextEncoder(), dec = new TextDecoder();

let ws = null, connected = false;
let state = null, stateAt = 0;
let stick = { x: 0, y: 0 };      // -1..1, y up = forward
let pendingMode = null;

// ── Link ───────────────────────────────────────────────────────────────────
function connect() {
  ws = new WebSocket(URL_WS, ['foxglove.sdk.v1']);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { connected = true; };
  ws.onclose = () => { connected = false; ws = null; setTimeout(connect, 1000); };
  ws.onerror = () => ws && ws.close();
  ws.onmessage = (ev) => (typeof ev.data === 'string' ? onJson(JSON.parse(ev.data)) : onBinary(ev.data));
}

function onJson(msg) {
  if (msg.op === 'serverInfo') {
    send({ op: 'advertise', channels: [
      { id: CH_CMD, topic: '/teleop/phone/cmd_vel', encoding: 'json', schemaName: 'geometry_msgs/msg/Twist' },
      { id: CH_MODE, topic: '/teleop/phone/set_mode', encoding: 'json', schemaName: 'std_msgs/msg/String' },
    ] });
  } else if (msg.op === 'advertise') {
    const ch = msg.channels.find((c) => c.topic === '/teleop/state');
    if (ch) send({ op: 'subscribe', subscriptions: [{ id: SUB_STATE, channelId: ch.id }] });
  } else if (msg.op === 'status' && msg.level >= 1) {
    console.warn('bridge:', msg.message);
  }
}

function onBinary(buf) {
  const v = new DataView(buf);
  // messageData: op(1) subscriptionId(u32) timestamp(u64) payload
  if (v.getUint8(0) !== 1 || v.getUint32(1, true) !== SUB_STATE) return;
  // std_msgs/String in CDR: 4-byte encapsulation header, u32 length (incl. NUL), bytes
  const len = v.getUint32(13 + 4, true);
  const text = dec.decode(new Uint8Array(buf, 13 + 8, Math.max(0, len - 1)));
  try { state = JSON.parse(text); stateAt = performance.now(); } catch (e) { /* ignore */ }
}

function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

function publish(channel, obj) {
  if (!ws || ws.readyState !== 1) return;
  const body = enc.encode(JSON.stringify(obj));
  const frame = new Uint8Array(5 + body.length);
  const v = new DataView(frame.buffer);
  v.setUint8(0, 1);                  // clientMessageData
  v.setUint32(1, channel, true);
  frame.set(body, 5);
  ws.send(frame);
}

function setMode(mode) {
  pendingMode = mode;
  // repeated: a lost frame must not leave the robot driving after STOP
  for (let i = 0; i < 3; i++) setTimeout(() => publish(CH_MODE, { data: mode }), i * 80);
}

// ── Command stream (deadman) ────────────────────────────────────────────────
function limits() {
  return state ? [state.max_linear, state.max_angular] : [0, 0];
}

setInterval(() => {
  // a hidden page stops sending, so the robot's deadman stops the rover
  if (document.hidden) return;
  const [maxLin, maxAng] = limits();
  publish(CH_CMD, {
    linear: { x: stick.y * maxLin, y: 0, z: 0 },
    angular: { x: 0, y: 0, z: -stick.x * maxAng },
  });
}, 1000 / SEND_HZ);

// ── Joystick ────────────────────────────────────────────────────────────────
const pad = $('pad'), knob = $('knob');
let pointerId = null;

function moveStick(ev) {
  const r = pad.getBoundingClientRect();
  const radius = Math.min(r.width, r.height) * 0.35;
  let dx = ev.clientX - (r.left + r.width / 2), dy = ev.clientY - (r.top + r.height / 2);
  const d = Math.hypot(dx, dy);
  if (d > radius) { dx *= radius / d; dy *= radius / d; }
  stick = { x: dx / radius, y: -dy / radius };
  knob.style.transform = `translate(${dx}px, ${dy}px)`;
}

function releaseStick() {
  pointerId = null;
  stick = { x: 0, y: 0 };
  knob.style.transform = '';
}

pad.addEventListener('pointerdown', (ev) => {
  pointerId = ev.pointerId;
  pad.setPointerCapture(ev.pointerId);
  moveStick(ev);
});
pad.addEventListener('pointermove', (ev) => { if (ev.pointerId === pointerId) moveStick(ev); });
for (const t of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  pad.addEventListener(t, (ev) => { if (ev.pointerId === pointerId) releaseStick(); });
}
document.addEventListener('visibilitychange', releaseStick);

// ── Buttons ─────────────────────────────────────────────────────────────────
document.querySelectorAll('.modes button').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
$('stop').addEventListener('pointerdown', () => { releaseStick(); setMode('stop'); });

// ── Display: what the robot reports, not what the app last sent ─────────────
function render() {
  const fresh = state && performance.now() - stateAt < STATE_STALE_MS;
  const linkText = !connected ? 'no link' : fresh ? 'connected' : 'link, no robot state';
  $('link').textContent = linkText;
  $('linkDot').style.background = !connected ? 'var(--bad)' : fresh ? 'var(--ok)' : 'var(--warn)';

  const mode = fresh ? state.mode : null;
  $('mode').textContent = mode ? mode : '—';
  $('source').textContent = fresh ? state.source : '—';
  const age = fresh ? state.teleop_age.phone : null;
  $('age').textContent = age == null ? '—' : age < state.teleop_timeout ? `yes (${Math.round(age * 1000)} ms)` : 'no';
  if (pendingMode && mode === pendingMode) pendingMode = null;

  document.querySelectorAll('.modes button').forEach((b) => {
    b.classList.toggle('active', b.dataset.mode === mode);
    b.classList.toggle('pending', b.dataset.mode === pendingMode);
  });

  const warn = $('warning');
  const msg = fresh && state.source !== 'phone'
    ? `The robot takes commands from "${state.source}". Only STOP works from the phone.`
    : fresh && mode !== 'manual' ? 'Joystick is ignored unless the robot is in Manual.' : '';
  warn.textContent = msg;
  warn.style.display = msg ? 'block' : 'none';
  pad.classList.toggle('disabled', !(fresh && mode === 'manual' && state.source === 'phone'));

  const [maxLin, maxAng] = limits();
  $('readout').textContent = `v ${(stick.y * maxLin).toFixed(2)} m/s   ω ${(-stick.x * maxAng).toFixed(2)} rad/s`;
  requestAnimationFrame(render);
}

$('url').textContent = URL_WS;
connect();
render();
