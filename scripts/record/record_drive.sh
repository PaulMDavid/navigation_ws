#!/usr/bin/env bash
# Bag recording on orintwo's NVMe (issue #29), for the phone (`phone_ctl.sh record …`) and by hand.
#
# ⚠️ REBUILT, NOT COPIED. The working original is orintwo:/mnt/ssd/pdavid/bags/record_drive.sh
# (2026-11-14 version, unreadable when this was written). This one is rebuilt from its
# 2026-11-12 14:32 copy (laptop /mnt/data_drive/orintwo_bags/2026-11-12/record_drive.sh), the
# 2026-11-14 bag's metadata.yaml + record log, and the notes in issue #29. Diff it against the
# original on orintwo and merge what is missing before relying on it.
#
#   presets                          groups + presets from presets.yaml
#   topics                           every live topic: type, Hz, MB/s over a short window
#   start <preset> [+/topic …] [-/topic …]
#                                    start sensors if down, wait for them, record
#   status [once]                    every ~2 s while recording (once: a single line)
#   stop                             SIGINT the recorder, wait for the bag to close
#
# Output: JSON lines as in scripts/phone_ctl.sh, contract in src/app_teleop/README.md
# ("Recording from the phone"). Hand use: `record_drive.sh status | jq -c .`
#
# Recorder: throwaway `docker run --rm` of the ZED image (zed2i_rec, has rosbag2), host
# network + IPC, navigation_ws cyclonedds.xml (DDS pinned to eno1), microstrain message
# overlay on AMENT_PREFIX_PATH / LD_LIBRARY_PATH so /mip/* types load, sqlite3 storage
# (no MCAP plugin in the images), zstd FILE compression, 2 GB chunks, QoS overrides for the
# latched topics. record_watch.py runs beside it in the same container for `status`.
# Power cut mid-bag: `ros2 bag reindex -s sqlite3 <bag dir>` (in the same image) recovers it.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=${NAVWS_REPO:-$(cd "$here/../.." && pwd)}
source "$repo/scripts/phone_ctl_lib.sh"

bags=${BAGS_DIR:-/mnt/ssd/pdavid/bags}
ssd=${SSD_MOUNT:-/mnt/ssd}
presets=${RECORD_PRESETS:-$here/presets.yaml}
image=${RECORD_IMAGE:-zed2i_rec:2026-11-14}
recorder=${RECORDER:-rec_drive}
dds=${RECORD_DDS:-$repo/src/config/dds/cyclonedds.xml}
overlay=${RECORD_OVERLAY:-/bags/.overlay_microstrain_msgs}   # path inside the recorder
domain=${RECORD_DOMAIN:-0}
prefix=${BAG_PREFIX:-drive}                   # bag = <prefix>_YYYY-MM-DD_HHMMSS
min_free_gb=${MIN_FREE_GB:-20}
max_bag_size=${MAX_BAG_SIZE:-2000000000}      # measured: 2026-11-14 chunks are 2.000 GB uncompressed
silent_window=${SILENT_WINDOW:-8}             # s; 4 s gave false NO MESSAGES
sensor_timeout=${SENSOR_TIMEOUT:-90}          # s to wait for silent sensors, then record anyway
record_settle=${RECORD_SETTLE:-8}             # s after docker run before counting subscriptions
topics_window=${TOPICS_WINDOW:-3}             # s, `topics` rate window
status_period=${STATUS_PERIOD:-2}
status_max=${STATUS_MAX:-3600}                # s; `status` ends after this, the app re-attaches
stop_timeout=${STOP_TIMEOUT:-120}
poll=${PHONE_CTL_POLL:-2}
lock=${RECORD_LOCK:-/tmp/record_drive.lock}
current=$bags/.record_current                 # bag=, preset=, start= of the last start
helper=(python3 "$here/record_helper.py")

# ---------- helpers ----------
num() { awk "BEGIN{printf \"%.${2:-1}f\", $1}"; }          # num <expr> [decimals]
hms() { printf '%02d:%02d:%02d' $(($1 / 3600)) $(($1 % 3600 / 60)) $(($1 % 60)); }
free_bytes() { df -B1 --output=avail "$ssd" 2>/dev/null | tail -n 1 | tr -dc 0-9; }
bag_bytes() { du -sb "$bags/$1" 2>/dev/null | awk '{print $1}'; }
jarr() {  # JSON array of strings from the arguments
  local s='' x
  for x in "$@"; do s+="${s:+, }\"$(jstr "$x")\""; done
  printf '[%s]' "$s"
}
read_current() {  # → C_bag C_preset C_start
  C_bag='' C_preset='' C_start=0
  local line
  [[ -f $current ]] || return 1
  while IFS= read -r line; do
    case ${line%%=*} in bag|preset|start) printf -v "C_${line%%=*}" '%s' "${line#*=}" ;; esac
  done <"$current"
  [[ -n $C_bag ]]
}
# helper lines "<kind> <json>": H_<kind> = json (last one), H_err = reason of an error line
run_helper() {
  local line k
  H_lines=$("${helper[@]}" "$@" 2>&1); H_rc=$?
  H_err=''
  while IFS= read -r line; do
    k=${line%% *}
    case $k in error) H_err=${line#error } ;; topics|silent|baginfo) printf -v "H_$k" '%s' "${line#* }" ;; esac
  done <<<"$H_lines"
  (( H_rc == 0 )) || H_err=${H_err:-$(lastline "$H_lines" "record_helper.py failed (rc $H_rc)")}
  [[ -z $H_err ]]
}
# bag dirs with chunks but no metadata.yaml (power cut / killed recorder), except $1
unclosed() {
  local d n out=()
  for d in "$bags"/*/; do
    n=$(basename "$d")
    [[ $n == "${1:-}" || -f $d/metadata.yaml ]] && continue
    compgen -G "$d*.db3*" >/dev/null && out+=("$n")
  done
  jarr "${out[@]}"
}

# ---------- presets ----------
do_presets() {
  local line k j
  run_helper presets "$presets" || { emit presets fail "$H_err"; done_line false; }
  while IFS= read -r line; do
    k=${line%% *}; j=${line#* }
    case $k in
      group|preset) [[ $j =~ \"name\":\ \"([^\"]+)\" ]]; emit presets ok "$k ${BASH_REMATCH[1]}" "\"$k\": $j" ;;
      quiet_ok) emit presets ok quiet_ok "\"quiet_ok\": $j" ;;
    esac
  done <<<"$H_lines"
  done_line true
}

# ---------- topics ----------
do_topics() {
  local line j n=0
  emit topics running "sampling every live topic for $topics_window s"
  if ! PT=$(( ${topics_window%.*} + 40 )) probe topics --window "$topics_window"; then
    emit topics fail "$P_DETAIL"; done_line false
  fi
  while IFS= read -r line; do
    [[ $line == 'topic {'* ]] || continue
    j=${line#topic }
    [[ $j =~ \"name\":\ \"([^\"]+)\" ]] || continue
    emit topics ok "${BASH_REMATCH[1]}" "\"topic\": $j"; n=$((n + 1))
  done <<<"$P_OUT"
  emit topics ok "$n topics; $P_DETAIL" "\"count\": $n"
  done_line true
}

# ---------- start ----------
check_free() {  # sets FREE_GB
  local b
  mountpoint -q "$ssd" || { set_ck fail "$ssd not mounted (NVMe)"; return; }
  b=$(free_bytes); [[ -n $b ]] || { set_ck fail "df $ssd failed"; return; }
  FREE_GB=$(num "$b / 1e9")
  if awk "BEGIN{exit !($b < $min_free_gb * 1e9)}"; then
    set_ck fail "only $FREE_GB GB free on $ssd (need $min_free_gb)"
  else set_ck ok "$FREE_GB GB free on $ssd"; fi
}

start_preflight() {
  if running "$recorder"; then
    read_current; set_ck fail "already recording${C_bag:+ $C_bag}"; return
  fi
  [[ -d $bags ]] || { set_ck fail "$bags missing"; return; }
  [[ -f $dds ]] || { set_ck fail "DDS config missing: $dds"; return; }
  check_free
}

# silent_of <topics…>: probe one rate window; SILENT = topics without messages
silent_of() {
  local line t hz
  SILENT=()
  if ! PT=$(( silent_window + 40 )) probe topics --window "$silent_window" --discover 3 "$@"; then
    SILENT=("$@"); CHECK_ERR=$P_DETAIL; return 1
  fi
  CHECK_ERR=''
  for t in "$@"; do
    line=$(printf '%s\n' "$P_OUT" | sed -n "s|^topic \(.*\"name\": \"$t\".*\)|\1|p" | head -n 1)
    [[ $line =~ \"hz\":\ ([0-9.]+) ]] && hz=${BASH_REMATCH[1]} || hz=0
    awk "BEGIN{exit !($hz > 0)}" || SILENT+=("$t")
  done
  (( ${#SILENT[@]} == 0 ))
}

start_sensors() {
  local line j name ctr stop c checks=() warn=() deadline next
  while IFS= read -r line; do
    [[ $line == 'sensor {'* ]] || continue
    j=${line#sensor }
    [[ $j =~ \"name\":\ \"([^\"]+)\" ]] && name=${BASH_REMATCH[1]}
    [[ $j =~ \"container\":\ \"([^\"]+)\" ]] && ctr=${BASH_REMATCH[1]} || ctr=''
    [[ $j =~ \"stop_first\":\ \[([^]]*)\] ]] && stop=${BASH_REMATCH[1]//[\",]/} || stop=''
    [[ $j =~ \"check\":\ \[([^]]*)\] ]] && checks+=(${BASH_REMATCH[1]//[\",]/})
    if [[ -n $ctr ]] && ! running "$ctr"; then
      for c in $stop; do
        running "$c" || continue
        emit sensors running "$name: docker stop $c (same device as $ctr)"
        docker stop "$c" >/dev/null 2>&1 || warn+=("docker stop $c failed")
      done
      emit sensors running "$name: docker start $ctr"
      out=$(docker start "$ctr" 2>&1) || warn+=("docker start $ctr: $(lastline "$out" failed)")
    fi
  done <<<"$H_lines"
  (( ${#checks[@]} )) || { set_ck ok "no sensor to check"; return; }
  deadline=$((SECONDS + sensor_timeout))
  while :; do
    if silent_of "${checks[@]}"; then
      if (( ${#warn[@]} )); then set_ck warn "${warn[*]}; sensors publishing"
      else set_ck ok "publishing: ${checks[*]}"; fi
      SENSOR_SILENT=(); return
    fi
    [[ -n $CHECK_ERR && $CHECK_ERR == 'app_teleop not running' ]] && break
    (( SECONDS >= deadline )) && break
    emit sensors running "waiting for ${SILENT[*]} (${silent_window} s window${CHECK_ERR:+; $CHECK_ERR})"
    sleep "$poll"
  done
  SENSOR_SILENT=("${SILENT[@]}")
  if [[ -n $CHECK_ERR ]]; then
    set_ck warn "${warn[*]:+${warn[*]}; }can't check sensors ($CHECK_ERR); recording anyway"
  else
    set_ck warn "${warn[*]:+${warn[*]}; }no messages after ${sensor_timeout} s: ${SILENT[*]}; recording anyway (topics are picked up when they appear)"
  fi
}

start_record() {
  local now bag inner n i
  now=$(date +%s)
  bag=${prefix}_$(date -d "@$now" +%Y-%m-%d_%H%M%S)
  [[ -e $bags/$bag ]] && { set_ck fail "$bags/$bag exists"; return; }
  printf '%s\n' "${TOPICS[@]}" >"$bags/${bag}_record.topics" || { set_ck fail "can't write to $bags"; return; }
  printf 'bag=%s\npreset=%s\nstart=%s\n' "$bag" "$PRESET" "$now" >"$current"
  inner="source /opt/ros/humble/setup.bash
export AMENT_PREFIX_PATH=$overlay:\$AMENT_PREFIX_PATH LD_LIBRARY_PATH=$overlay/lib:\$LD_LIBRARY_PATH
export PYTHONPATH=$overlay/local/lib/python3.10/dist-packages:$overlay/lib/python3.10/site-packages:\${PYTHONPATH:-}
python3 /navws_record/record_watch.py --topics-file /bags/${bag}_record.topics --out /bags/${bag}_watch.json --window $silent_window >/bags/${bag}_watch.log 2>&1 &
exec ros2 bag record -o /bags/$bag -s sqlite3 --qos-profile-overrides-path /navws_record/qos_latched_overrides.yaml \
  --compression-mode file --compression-format zstd --max-bag-size $max_bag_size ${TOPICS[*]} >/bags/${bag}_record.log 2>&1"
  emit record running "docker run $recorder ($image) → $bags/$bag, ${#TOPICS[@]} topics"
  out=$(docker run -d --name "$recorder" --rm --init --stop-signal SIGINT --stop-timeout 60 \
          --network host --ipc host --user "$(id -u):$(id -g)" -e HOME=/tmp \
          -e ROS_DOMAIN_ID="$domain" -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
          -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml -v "$dds:/etc/cyclonedds.xml:ro" \
          -v "$bags:/bags" -v "$here:/navws_record:ro" --label "navws.bag=$bag" \
          --entrypoint bash "$image" -c "$inner" 2>&1) \
    || { set_ck fail "docker run failed: $(lastline "$out" '?')"; return; }
  for (( i = 0; i < record_settle * 2; i++ )); do
    running "$recorder" || break
    sleep 0.5
  done
  if ! running "$recorder"; then
    set_ck fail "recorder exited: $(lastline "$(tail -n 5 "$bags/${bag}_record.log" 2>/dev/null)" 'no log')"; return
  fi
  n=$(awk '/Subscribed to topic/{n++} END{print n+0}' "$bags/${bag}_record.log" 2>/dev/null)
  BAG=$bag
  set_ck ok "recording $bag: ${n:-0}/${#TOPICS[@]} topics subscribed (others are picked up when they appear)"
  REC_EXTRA="\"bag\": \"$bag\", \"preset\": \"$PRESET\", \"subscribed\": ${n:-0}, \"topics\": $(jarr "${TOPICS[@]}")"
}

do_start() {
  local t
  take_lock "$lock"
  emit preflight running ""
  CK_STATE=fail; start_preflight
  emit preflight "$CK_STATE" "$CK_REASON" "${FREE_GB:+\"free_gb\": $FREE_GB}"
  if [[ $CK_STATE == fail ]]; then emit sensors skipped "preflight failed"; emit record skipped "preflight failed"; done_line false; fi
  emit sensors running ""
  SENSOR_SILENT=(); start_sensors
  emit sensors "$CK_STATE" "$CK_REASON" "\"silent\": $(jarr "${SENSOR_SILENT[@]}")"
  REC_EXTRA=''
  CK_STATE=fail; start_record
  emit record "$CK_STATE" "$CK_REASON" "$REC_EXTRA"
  [[ $CK_STATE == ok ]] && done_line true || done_line false
}

# ---------- status ----------
status_line() {  # one status line; returns 1 when not recording
  local rec=false now el=null size=null rate=null left=null free fb silent=null inp=null unw='[]' st=ok reason n=0 unc
  read_current
  fb=$(free_bytes); free=$( [[ -n $fb ]] && num "$fb / 1e9" || echo null)
  if running "$recorder" && [[ -n $C_bag ]]; then
    rec=true
    now=$(date +%s); el=$(( now - C_start )); (( el > 0 )) || el=1
    size=$(bag_bytes "$C_bag"); size=${size:-0}
    rate=$(num "$size / $el / 1e6" 2)
    if [[ -n $fb ]] && awk "BEGIN{exit !($size > 0)}"; then left=$(num "$fb / ($size / $el) / 3600"); fi
    size=$(num "$size / 1e6")
    n=$(wc -l <"$bags/${C_bag}_record.topics" 2>/dev/null || echo 0)
    if run_helper silent "$presets" "$bags/${C_bag}_record.topics" "$bags/${C_bag}_watch.json" "$silent_window"; then
      [[ $H_silent =~ \"silent\":\ (null|\[[^]]*\]) ]] && silent=${BASH_REMATCH[1]}
      [[ $H_silent =~ \"input_mbps\":\ ([0-9.]+|null) ]] && inp=${BASH_REMATCH[1]}
      [[ $H_silent =~ \"unwatched\":\ (\[[^]]*\]) ]] && unw=${BASH_REMATCH[1]}
    fi
    [[ $silent == null || $silent == '[]' ]] || st=warn
    reason="recording $C_bag $(hms "$el"), $size MB, $rate MB/s, $free GB free"
    [[ $st == warn ]] && reason+="; no messages for ${silent_window} s: ${silent//[\[\]\"]/}"
    [[ $silent == null ]] && reason+="; topic watch starting"
  else
    reason="not recording"
    C_bag=${C_bag:-}
  fi
  unc=$(unclosed "$( [[ $rec == true ]] && echo "$C_bag")")
  if [[ $unc != '[]' ]]; then
    st=warn; reason+="; unclosed bag(s) ${unc//[\[\]\"]/}: ros2 bag reindex -s sqlite3 <dir>"
  fi
  emit status "$st" "$reason" "\"recording\": $rec, \"bag\": $( [[ -n $C_bag ]] && printf '"%s"' "$(jstr "$C_bag")" || echo null), \
\"preset\": $( [[ -n $C_preset ]] && printf '"%s"' "$(jstr "$C_preset")" || echo null), \"elapsed_s\": $el, \
\"size_mb\": $size, \"rate_mbps\": $rate, \"input_mbps\": $inp, \"free_gb\": $free, \"left_h\": $left, \
\"topics\": $n, \"silent\": $silent, \"unwatched\": $unw, \"unclosed\": $unc"
  [[ $rec == true ]]
}

do_status() {
  local end=$((SECONDS + status_max))
  while :; do
    status_line || done_line true
    [[ ${1:-} == once ]] && done_line true
    (( SECONDS >= end )) && done_line true
    sleep "$status_period"
  done
}

# ---------- stop ----------
do_stop() {
  local deadline next size info=''
  take_lock "$lock"
  read_current
  if ! running "$recorder"; then
    emit stop ok "not recording" "\"recording\": false"; done_line true
  fi
  emit stop running "SIGINT to $recorder; waiting for ${C_bag:-the bag} to close" "\"bag\": \"$(jstr "$C_bag")\""
  docker kill -s INT "$recorder" >/dev/null 2>&1
  deadline=$((SECONDS + stop_timeout)); next=$((SECONDS + 10))
  while running "$recorder"; do
    if (( SECONDS >= deadline )); then
      emit stop fail "$recorder still running after $stop_timeout s; not killed (a SIGKILL leaves the bag unclosed): run record stop again" \
        "\"bag\": \"$(jstr "$C_bag")\""
      done_line false
    fi
    if (( SECONDS >= next )); then
      next=$((SECONDS + 10)); emit stop running "closing ${C_bag}: compressing the last chunk, writing metadata"
    fi
    sleep "$poll"
  done
  size=$(bag_bytes "$C_bag"); size=$(num "${size:-0} / 1e6")
  if run_helper baginfo "$bags/$C_bag"; then
    [[ $H_baginfo =~ \"duration_s\":\ ([0-9.]+) ]] && dur=${BASH_REMATCH[1]} || dur=0
    [[ $H_baginfo =~ \"messages\":\ ([0-9]+) ]] && msgs=${BASH_REMATCH[1]} || msgs=null
    [[ $H_baginfo =~ \"files\":\ ([0-9]+) ]] && files=${BASH_REMATCH[1]} || files=null
    emit stop ok "$C_bag closed: $size MB, $(hms "${dur%.*}"), $msgs messages in $files files" \
      "\"bag\": \"$(jstr "$C_bag")\", \"size_mb\": $size, \"duration_s\": $dur, \"messages\": $msgs, \"files\": $files"
    done_line true
  fi
  emit stop fail "$C_bag not closed cleanly (no metadata.yaml): ros2 bag reindex -s sqlite3 $bags/$C_bag" \
    "\"bag\": \"$(jstr "$C_bag")\", \"size_mb\": $size"
  done_line false
}

# ---------- command line ----------
verb=${1:-}; shift || true
case $verb in
  presets|topics|stop)
    (( $# == 0 )) || refuse "record $verb takes no arguments" ;;
  status)
    (( $# == 0 )) || [[ $# == 1 && $1 == once ]] || refuse "record status takes nothing or 'once'" ;;
  start)
    (( $# )) || refuse "record start needs a preset (record presets lists them)"
    [[ $1 =~ ^[a-z0-9_]+$ ]] || refuse "bad preset name"
    PRESET=$1
    run_helper resolve "$presets" "$@" || refuse "$H_err"
    TOPICS=($(printf '%s' "$H_topics" | tr -d '[]",'))
    ;;
  *) refuse "unknown record verb '${verb}' (presets|topics|start <preset> [+/topic] [-/topic]|status [once]|stop)" ;;
esac

case $verb in
  presets) do_presets ;;
  topics)  do_topics ;;
  start)   do_start ;;
  status)  do_status "$@" ;;
  stop)    do_stop ;;
esac
