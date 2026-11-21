# Shared by scripts/phone_ctl.sh and scripts/record/record_drive.sh (sourced, not run):
# the JSON-lines output, the docker helpers and the ROS probe in app_teleop_container.
# Output format: src/app_teleop/README.md, "One-button bring-up from the phone".

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

# take_lock <file>: one command at a time; a second one gets `busy` (exit 75)
take_lock() {
  exec 9>"$1" || refuse "can't open lock $1"
  flock -n 9 || { emit command fail "busy: another phone_ctl command is running"
                  printf '{"done": true, "ok": false}\n'; exit 75; }
}

# ---------- helpers ----------
running() { [[ $(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null) == true ]]; }
lastline() { local l; l=$(printf '%s\n' "$1" | sed '/^[[:space:]]*$/d' | tail -n 1); printf '%s' "${l:-$2}"; }

# result of a check: CK_STATE + CK_REASON
set_ck() { CK_STATE=$1; CK_REASON=$2; [[ $1 == ok || $1 == warn ]]; }

# probe <check> [args]: one-shot ROS check inside app_teleop_container (src/app_teleop/phone_probe.py).
# Sets P_OK (0/1), P_DETAIL and P_OUT (all output lines; `topics` prints one `topic {json}` line
# per topic before its ok line). PT = timeout of the docker exec, s (default 60).
probe() {
  local out
  P_OUT=''
  if ! running app_teleop_container; then P_OK=1; P_DETAIL='app_teleop not running'; return 1; fi
  P_OUT=$(timeout "${PT:-60}" docker exec app_teleop_container /ros_entrypoint.sh \
          python3 app_teleop/phone_probe.py "$@" 2>&1)
  out=$(printf '%s\n' "$P_OUT" | sed -n '/^\(ok\|fail\)\( \|$\)/p' | tail -n 1)
  case $out in
    ok*)   P_OK=0; P_DETAIL=${out#ok }; return 0 ;;
    fail*) P_OK=1; P_DETAIL=${out#fail }; return 1 ;;
    *)     P_OK=1; P_DETAIL='probe gave no answer'; return 1 ;;
  esac
}
