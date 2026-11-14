#!/usr/bin/env bash
# Phone one-button bring-up on orintwo (issue #27). The phone's ssh key may run only this
# script (command="…/phone_ctl.sh" in ~/.ssh/authorized_keys, installed by
# scripts/robot_setup/phone_link.sh); the verb comes from SSH_ORIGINAL_COMMAND, or from
# the arguments when run by hand:
#
#   up            preflight → teleop → rover_link → wheels, stops at the first failing step
#   camera        ZED + app_teleop_camera (not part of up: the ZED's first start takes ~6 min)
#   stop          wheels service, camera, app_rover_arming + app_nav_relay (mux + bridge stay up)
#   status        every check, starts nothing
#   zero <ids>    re-zero steering MD80s (ids from 11 12 13 14), restart wheels, reset rover_arming
#   log <step>    last ~50 log lines of preflight|teleop|rover_link|wheels|camera
#
# Output: one JSON object per line, streamed as steps run,
#   {"step": "wheels", "state": "running|ok|fail|warn|skipped", "reason": "...", "t": 12.3}
# and a final {"done": true, "ok": true}. `t` = seconds since the command started.
# `log` prints each log line as {"step": <step>, "state": "ok", "reason": <line>, "t": …, "log": true}.
# The rover is reached over the wired link with a key that may run only
# rover_wheels_ctl.sh there (scripts/robot_setup/rover/).
set -uo pipefail

repo=${NAVWS_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
project=${COMPOSE_PROJECT:-navbringup}
rover_host=${ROVER_HOST:-192.168.1.230}
rover_user=${ROVER_USER:-rover}
rover_key=${ROVER_KEY:-$HOME/.ssh/navws_rover_ed25519}
lock=${PHONE_CTL_LOCK:-/tmp/phone_ctl.lock}
ssd=${SSD_MOUNT:-/mnt/ssd}
# timeouts, s
compose_timeout=${COMPOSE_TIMEOUT:-900}   # includes building a missing image on first run
mux_timeout=${MUX_TIMEOUT:-30}
wheels_timeout=${WHEELS_TIMEOUT:-150}     # launch + up to 3 MD80 retries (each ~10 s)
camera_timeout=${CAMERA_TIMEOUT:-480}     # the ZED's first start optimizes its depth model (~6 min)
camera_min_hz=${CAMERA_MIN_HZ:-8}         # "~10 Hz" (teleop_camera caps at 10)
poll=${PHONE_CTL_POLL:-2}
md80_retries=${MD80_RETRIES:-3}

teleop_services=(app_teleop app_foxglove_bridge app_rover_arming app_nav_relay)
camera_services=(app_zed2i_camera app_teleop_camera)
declare -A container=([app_teleop]=app_teleop_container [app_foxglove_bridge]=app_foxglove_bridge_container
                      [app_rover_arming]=app_rover_arming_container [app_nav_relay]=app_nav_relay_container [app_teleop_camera]=app_teleop_camera_container
                      [app_zed2i_camera]=app_zed2i_camera)
steps=(preflight teleop rover_link wheels camera)
ids_ok=(11 12 13 14)

start_us=${EPOCHREALTIME/./}

# ---------- output ----------
jstr() {  # JSON string body: escape \ " and whitespace controls, drop other control chars
  local LC_ALL=C s=$1
  s=${s//\\/\\\\}; s=${s//\"/\\\"}
  s=${s//$'\n'/\\n}; s=${s//$'\r'/\\r}; s=${s//$'\t'/\\t}
  s=${s//[$'\001'-$'\037']/}
  printf '%s' "$s"
}
elapsed() { local d=$(( (${EPOCHREALTIME/./} - start_us) / 100000 )); printf '%d.%d' $((d / 10)) $((d % 10)); }
emit() {  # step state reason [extra json]
  printf '{"step": "%s", "state": "%s", "reason": "%s", "t": %s%s}\n' \
    "$1" "$2" "$(jstr "$3")" "$(elapsed)" "${4:+, $4}"
}
done_line() { printf '{"done": true, "ok": %s}\n' "$1"; [[ $1 == true ]]; exit $?; }
refuse() { emit command fail "refused: $1"; printf '{"done": true, "ok": false}\n'; exit 64; }

# ---------- helpers ----------
compose() { (cd "$repo/src" && timeout "$compose_timeout" docker compose -p "$project" "$@"); }
running() { [[ $(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null) == true ]]; }
lastline() { local l; l=$(printf '%s\n' "$1" | sed '/^[[:space:]]*$/d' | tail -n 1); printf '%s' "${l:-$2}"; }

# probe <check> [args]: one-shot ROS check inside app_teleop_container (src/app_teleop/phone_probe.py).
# Sets P_OK (0/1) and P_DETAIL.
probe() {
  local out
  if ! running app_teleop_container; then P_OK=1; P_DETAIL='app_teleop not running'; return 1; fi
  out=$(timeout 60 docker exec app_teleop_container /ros_entrypoint.sh \
          python3 app_teleop/phone_probe.py "$@" 2>&1)
  out=$(printf '%s\n' "$out" | sed -n '/^\(ok\|fail\)\( \|$\)/p' | tail -n 1)
  case $out in
    ok*)   P_OK=0; P_DETAIL=${out#ok }; return 0 ;;
    fail*) P_OK=1; P_DETAIL=${out#fail }; return 1 ;;
    *)     P_OK=1; P_DETAIL='probe gave no answer'; return 1 ;;
  esac
}

ssh_opts=(-i "$rover_key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5
          -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ServerAliveCountMax=3)
# rover <verb…>: the restricted key runs rover_wheels_ctl.sh with this as SSH_ORIGINAL_COMMAND
rover() { timeout "${RT:-30}" ssh "${ssh_opts[@]}" "$rover_user@$rover_host" "$*"; }

# rover status → R_<key> variables (active, phase, attempt, failed_id, last_failed, added, reason)
rover_status() {
  local out line k
  R_active=unknown R_phase=unknown R_attempt=0 R_failed_id='' R_last_failed='' R_added='' R_reason=''
  out=$(RT=15 rover status 2>&1) || { R_err=$(lastline "$out" "ssh failed"); return 1; }
  while IFS= read -r line; do
    k=${line%%=*}
    case $k in active|phase|attempt|failed_id|last_failed|added|reason) printf -v "R_$k" '%s' "${line#*=}" ;; esac
  done <<<"$out"
  return 0
}

# result of a check: CK_STATE + CK_REASON
set_ck() { CK_STATE=$1; CK_REASON=$2; [[ $1 == ok || $1 == warn ]]; }

# ---------- checks ----------
check_preflight() {
  local pct
  mountpoint -q "$ssd" || { set_ck fail "$ssd not mounted (NVMe)"; return; }
  [[ -f $repo/src/config/dds/cyclonedds.xml ]] || { set_ck fail "DDS config missing: src/config/dds/cyclonedds.xml"; return; }
  pct=$(df --output=pcent / 2>/dev/null | tail -n 1 | tr -dc 0-9)
  [[ -n $pct ]] || { set_ck fail "df / failed"; return; }
  if (( pct >= 100 )); then set_ck fail "/ is full (${pct} %)"
  elif (( pct >= 95 )); then set_ck warn "/ at ${pct} %; $ssd mounted, DDS config present"
  else set_ck ok "$ssd mounted, DDS config present, / at ${pct} %"; fi
}

check_teleop() {
  local s down=()
  for s in "${teleop_services[@]}"; do running "${container[$s]}" || down+=("$s"); done
  (( ${#down[@]} == 0 )) || { set_ck fail "not running: ${down[*]}"; return; }
  probe mux_source --timeout 5 || { set_ck fail "$P_DETAIL"; return; }
  [[ $P_DETAIL == phone ]] || { set_ck fail "teleop source is $P_DETAIL, not phone"; return; }
  set_ck ok "source phone; ${teleop_services[*]} running"
}

check_rover_link() {
  local i
  for i in 1 2 3; do ping -c 1 -W 1 "$rover_host" >/dev/null 2>&1 && break
    (( i == 3 )) && { set_ck fail "$rover_host doesn't answer ping (wired link?)"; return; }
  done
  rover_status || { set_ck fail "ssh $rover_user@$rover_host: $R_err"; return; }
  set_ck ok "ping + ssh ok; rover-wheels $R_active"
}

# wheels health from the rover's status (R_*) + the subscriber check
wheels_health() {
  [[ $R_active == active ]] || { set_ck fail "rover-wheels $R_active${R_reason:+: $R_reason}"; return; }
  case $R_phase in
    ready|quiet) ;;
    *) set_ck fail "rover-wheels $R_phase${R_reason:+: $R_reason}"; return ;;
  esac
  probe subs /joy /cmd_vel --timeout 5 || { set_ck fail "MD80 ok, but $P_DETAIL"; return; }
  if [[ $R_phase == quiet ]]; then
    set_ck warn "no 'Added MD80' lines in wheels.log, no failures either; /joy + /cmd_vel subscribed"
  else
    set_ck ok "MD80 ${R_added} added; /joy + /cmd_vel subscribed"
  fi
}

check_wheels() {
  rover_status || { set_ck fail "rover unreachable: $R_err"; return; }
  wheels_health
}

check_camera() {
  local s down=()
  for s in "${camera_services[@]}"; do running "${container[$s]}" || down+=("$s"); done
  if (( ${#down[@]} == 2 )); then set_ck skipped "not started (camera verb)"; return 0; fi
  (( ${#down[@]} == 0 )) || { set_ck fail "not running: ${down[*]}"; return; }
  camera_rate 10
}

camera_rate() {  # timeout for the first frame
  local hz
  probe rate /teleop/camera/compressed --phone --window 3 --timeout "$1" || { set_ck fail "$P_DETAIL"; return; }
  hz=$P_DETAIL
  if awk "BEGIN{exit !($hz >= $camera_min_hz)}"; then set_ck ok "relayed image at $hz Hz"
  else set_ck warn "relayed image at only $hz Hz (want ~10)"; fi
}

# ---------- actions ----------
up_preflight() { check_preflight; }

up_teleop() {
  local out deadline
  emit teleop running "docker compose up -d ${teleop_services[*]} (TELEOP_SOURCE=phone)"
  out=$(TELEOP_SOURCE=phone compose up -d "${teleop_services[@]}" 2>&1) \
    || { set_ck fail "compose up failed: $(lastline "$out" '?')"; return; }
  deadline=$((SECONDS + mux_timeout))
  while :; do
    check_teleop && return 0
    (( SECONDS >= deadline )) && return 1
    sleep "$poll"
  done
}

up_rover_link() { check_rover_link; }

# wait for the wheels service to come up healthy, streaming retries
wait_wheels() {
  local deadline=$((SECONDS + wheels_timeout)) seen=1
  CK_REASON=''
  while :; do
    if rover_status; then
      if (( R_attempt > seen )); then
        seen=$R_attempt
        emit wheels running "retry $((R_attempt - 1))/$md80_retries: MD80 ${R_last_failed:-?} failed to add; mdtool encoder, relaunch"
      fi
      case $R_active/$R_phase in
        active/ready|active/quiet) wheels_health && return 0 ;;
        */gave_up) set_ck fail "MD80 ${R_failed_id:-?} failed to add after $md80_retries retries"; return 1 ;;
        active/*) ;;
        activating/*) ;;
        *) set_ck fail "rover-wheels $R_active ($R_phase)${R_reason:+: $R_reason}"; return 1 ;;
      esac
    fi
    if (( SECONDS >= deadline )); then
      set_ck fail "not ready after $wheels_timeout s: rover-wheels $R_active/$R_phase${CK_REASON:+; $CK_REASON}"
      return 1
    fi
    sleep "$poll"
  done
}

reset_arming() {
  local health=$CK_REASON
  probe rover_cmd reset --timeout 5 || { set_ck fail "wheels up, but rover_arming reset failed: $P_DETAIL"; return; }
  set_ck "$CK_STATE" "$health; rover_arming reset"
}

up_wheels() {
  local out
  rover_status || { set_ck fail "rover unreachable: $R_err"; return; }
  if [[ $R_active == active ]] && wheels_health; then
    # systemd would not restart it, so robot_control keeps its state: no reset
    set_ck "$CK_STATE" "already running: $CK_REASON (tracked state kept)"; return
  fi
  emit wheels running "starting rover-wheels.service"
  out=$(RT=30 rover start 2>&1) || { set_ck fail "start: $(lastline "$out" 'failed')"; return; }
  wait_wheels || return 1
  reset_arming
}

up_camera() {
  local out deadline next=$((SECONDS + 30))
  emit camera running "docker compose up -d ${camera_services[*]}"
  out=$(compose up -d "${camera_services[@]}" 2>&1) \
    || { set_ck fail "compose up failed: $(lastline "$out" '?')"; return; }
  deadline=$((SECONDS + camera_timeout))
  while :; do
    check_camera_up && return 0
    (( SECONDS >= deadline )) && { set_ck fail "no image after $camera_timeout s: $CK_REASON"; return 1; }
    if (( SECONDS >= next )); then
      next=$((SECONDS + 30))
      emit camera running "waiting for the ZED (first start optimizes its depth model, ~6 min): $CK_REASON"
    fi
    sleep "$poll"
  done
}
check_camera_up() {
  local s
  for s in "${camera_services[@]}"; do
    running "${container[$s]}" || { set_ck fail "$s not running"; return 1; }
  done
  camera_rate 10
}

# run a step: running line, the action, the result line
step() {
  local name=$1 fn=$2
  emit "$name" running ""
  CK_STATE=fail CK_REASON=''
  "$fn"
  emit "$name" "$CK_STATE" "$CK_REASON"
  [[ $CK_STATE == ok || $CK_STATE == warn || $CK_STATE == skipped ]]
}

take_lock() {
  exec 9>"$lock" || refuse "can't open lock $lock"
  flock -n 9 || { emit command fail "busy: another phone_ctl command is running"
                  printf '{"done": true, "ok": false}\n'; exit 75; }
}

# ---------- verbs ----------
do_up() {
  local s failed=''
  for s in preflight teleop rover_link wheels; do
    if [[ -n $failed ]]; then emit "$s" skipped "$failed failed"; continue; fi
    step "$s" "up_$s" || failed=$s
  done
  [[ -z $failed ]] && done_line true || done_line false
}

do_status() {
  local ok=true link=1
  step preflight check_preflight || ok=false
  step teleop check_teleop || ok=false
  step rover_link check_rover_link || { ok=false; link=0; }
  if (( link )); then step wheels check_wheels || ok=false
  else emit wheels skipped "rover_link failed"; ok=false; fi
  step camera check_camera || ok=false
  done_line $ok
}

do_camera() { step camera up_camera && done_line true || done_line false; }

stop_wheels() {
  local out
  out=$(RT=40 rover stop 2>&1) && set_ck ok "rover-wheels stopped" \
    || set_ck fail "rover stop: $(lastline "$out" 'ssh failed')"
}
stop_camera() {
  local out
  out=$(compose stop "${camera_services[@]}" 2>&1) && set_ck ok "${camera_services[*]} stopped" \
    || set_ck fail "compose stop: $(lastline "$out" '?')"
}
stop_teleop() {
  local out
  out=$(compose stop app_rover_arming app_nav_relay 2>&1) && set_ck ok "app_rover_arming + app_nav_relay stopped; app_teleop + app_foxglove_bridge stay up" \
    || set_ck fail "compose stop: $(lastline "$out" '?')"
}
do_stop() {  # best effort: every step runs even if one fails
  local ok=true
  step wheels stop_wheels || ok=false
  step camera stop_camera || ok=false
  step teleop stop_teleop || ok=false
  done_line $ok
}

zero_ids() {
  local line rc out
  emit zero running "wheels go limp: stopping rover-wheels, then mdtool config zero/save ${ZERO_IDS[*]}"
  # stream the rover's progress lines
  exec 8< <(RT=$((60 + 10 * ${#ZERO_IDS[@]})) rover zero "${ZERO_IDS[@]}" 2>&1; echo "__rc=$?")
  rc=1 out=''
  while IFS= read -r line <&8; do
    if [[ $line == __rc=* ]]; then rc=${line#__rc=}; continue; fi
    [[ -n $line ]] || continue
    out=$line
    emit zero running "$line"
  done
  exec 8<&-
  if (( rc == 0 )); then set_ck ok "zeroed + saved ${ZERO_IDS[*]}"
  else set_ck fail "${out:-rover zero failed (rc $rc)}"; fi
}
zero_wheels() { wait_wheels || return 1; reset_arming; }
do_zero() {
  local ok=true
  step rover_link check_rover_link || { emit zero skipped "rover_link failed"; emit wheels skipped "rover_link failed"; done_line false; }
  step zero zero_ids || ok=false
  # the rover restarts the wheels service even after a failed mdtool call
  step wheels zero_wheels || ok=false
  done_line $ok
}

log_lines() {  # step: prints raw lines
  local c
  case $1 in
    preflight) findmnt "$ssd" 2>&1; df -h / "$ssd" 2>&1; ls -l "$repo/src/config/dds/cyclonedds.xml" 2>&1 ;;
    teleop|camera)
      local -n svcs=$1_services
      for c in "${svcs[@]}"; do echo "== ${container[$c]} =="; docker logs --tail 50 "${container[$c]}" 2>&1; done ;;
    rover_link) ping -c 1 -W 1 "$rover_host" 2>&1; RT=15 rover status 2>&1 ;;
    wheels) RT=15 rover log 2>&1 ;;
  esac
}
do_log() {
  local line
  while IFS= read -r line; do emit "$1" ok "$line" '"log": true'; done < <(log_lines "$1")
  done_line true
}

# ---------- command line ----------
if [[ -n ${SSH_ORIGINAL_COMMAND+x} ]]; then cmd=$SSH_ORIGINAL_COMMAND; else cmd="$*"; fi
[[ $cmd =~ ^[a-z0-9_\ ,]*$ ]] || refuse "unexpected characters in command"
cmd=${cmd//,/ }
read -r -a words <<<"$cmd"
(( ${#words[@]} )) || refuse "no command (up|stop|status|camera|zero <ids>|log <step>)"
verb=${words[0]}; args=("${words[@]:1}")

case $verb in
  up|stop|status|camera)
    (( ${#args[@]} == 0 )) || refuse "$verb takes no arguments" ;;
  zero)
    (( ${#args[@]} )) || refuse "zero needs ids from ${ids_ok[*]}"
    ZERO_IDS=()
    for a in "${args[@]}"; do
      [[ " ${ids_ok[*]} " == *" $a "* ]] || refuse "MD80 id $a not in ${ids_ok[*]}"
      [[ " ${ZERO_IDS[*]} " == *" $a "* ]] || ZERO_IDS+=("$a")
    done ;;
  log)
    (( ${#args[@]} == 1 )) && [[ " ${steps[*]} " == *" ${args[0]} "* ]] \
      || refuse "log needs one step from ${steps[*]}" ;;
  *) refuse "unknown verb $verb (up|stop|status|camera|zero <ids>|log <step>)" ;;
esac

case $verb in
  up)     take_lock; do_up ;;
  stop)   take_lock; do_stop ;;
  camera) take_lock; do_camera ;;
  zero)   take_lock; do_zero ;;
  status) do_status ;;
  log)    do_log "${args[0]}" ;;
esac
