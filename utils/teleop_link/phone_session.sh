#!/usr/bin/env bash
# Hands-on phone test with the laptop as orintwo: teleop_mux + foxglove_bridge + the
# phone page on this machine, recording everything to results/session.jsonl. The camera
# page gets the OV9281 (on OV9281_DEVICE, default /dev/video2) in place of the ZED.
#   ./phone_session.sh start   then open the printed URL on the phone
#   ./phone_session.sh stop    stops, prints the report (record.py report)
set -euo pipefail
cd "$(dirname "$0")"
export PROBE_UID=$(id -u) TELEOP_SOURCE=phone

case ${1:-} in
  start)
    mkdir -p results && : > results/session.jsonl
    docker compose --profile camera up -d mux fox phone_app camera ov9281
    docker compose --profile probe run -d --name teleop_session_recorder probe python3 record.py record
    ip=$(ip -4 route get 1.1.1.1 | awk '{for (i=1;i<NF;i++) if ($i=="src") print $(i+1)}')
    echo "open on the phone: http://$ip:8080" ;;
  stop)
    docker stop teleop_session_recorder >/dev/null && docker rm teleop_session_recorder >/dev/null
    docker compose --profile camera down
    docker compose --profile probe run --rm --no-deps probe python3 record.py report ;;
  *) echo "usage: $0 start|stop" >&2; exit 64 ;;
esac
