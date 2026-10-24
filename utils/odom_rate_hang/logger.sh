#!/usr/bin/env bash
# System logger meant to survive the freeze: everything is appended to plain files
# on the SSD and fsync'd every second, so whatever was written before orintwo locked
# up is still there after the reboot. Gaps in the 1 Hz timestamps show the freeze.
#
#   ./logger.sh start [label]   -> prints the log dir
#   ./logger.sh stop
set -euo pipefail
root=/mnt/ssd/pdavid/logs
pidfile=$root/.logger.pid

if [[ ${1:-} == stop ]]; then
  [[ -f $pidfile ]] || { echo "logger not running"; exit 0; }
  kill -- -"$(cat "$pidfile")" 2>/dev/null || true
  rm -f "$pidfile"
  echo "logger stopped"
  exit 0
fi
[[ ${1:-} == start ]] || { echo "usage: $0 start [label] | stop"; exit 1; }
[[ -f $pidfile ]] && kill -0 -- -"$(cat "$pidfile")" 2>/dev/null && {
  echo "logger already running (pgid $(cat "$pidfile"))"; exit 1; }

dir=$root/$(date +%Y%m%d-%H%M%S)${2:+-$2}
mkdir -p "$dir"

# metadata: what the system looked like, so before/after-tuning runs compare fairly
{
  date -Is; uname -a; head -1 /etc/nv_tegra_release
  nvpmodel -q 2>/dev/null | head -1
  sysctl net.core.rmem_max net.core.rmem_default net.ipv4.ipfrag_time net.ipv4.ipfrag_high_thresh
  echo "journal persistent: $([[ -d /var/log/journal ]] && echo yes || echo no)"
  docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
} > "$dir/metadata.txt"

setsid bash -c '
  dir=$1
  tegrastats --interval 1000 >> "$dir/tegrastats.log" 2>&1 &
  vmstat -n -t 1 >> "$dir/vmstat.log" &
  ( while :; do                       # docker stats is slow (~2 s), so its own loop
      { echo "## $(date +%s)"; docker stats --no-stream \
          --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"; } >> "$dir/docker_stats.log"
      sleep 5
    done ) &
  while :; do
    t=$(date +%s)
    echo "$t $(cat /proc/loadavg) $(awk "/MemAvailable|SwapFree/{printf \"%s=%s \", \$1, \$2}" /proc/meminfo)" >> "$dir/load.log"
    echo "$t $(nstat -az UdpRcvbufErrors UdpInErrors IpReasmFails | awk "NR>1{printf \"%s=%s \", \$1, \$2}")" >> "$dir/udp.log"
    { echo "## $t"; ps -eo pid,pcpu,rss,comm --sort=-pcpu | head -11; } >> "$dir/top_cpu.log"
    { echo "## $t"; ps -eo pid,pcpu,rss,comm --sort=-rss | head -11; } >> "$dir/top_rss.log"
    sync "$dir"/*.log
    sleep 1
  done
' _ "$dir" > /dev/null 2>&1 < /dev/null &
echo $! > "$pidfile"
echo "$dir"
