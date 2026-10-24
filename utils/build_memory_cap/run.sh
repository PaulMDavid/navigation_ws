#!/bin/bash
# Builds an image that tries to allocate 10 GB. With the capped builder active this must
# fail inside the builder (OOM in its cgroup) while host MemAvailable stays healthy.
cd "$(dirname "$0")"
docker buildx inspect | sed -n '1,3p'
( while sleep 1; do awk '/MemAvailable/{printf "host MemAvailable %d MB\n", $2/1024}' /proc/meminfo; done ) > minmem.log &
mon=$!
docker compose build --no-cache 2>&1 | tail -4
rc=${PIPESTATUS[0]}
kill $mon
sort -k3 -n minmem.log | head -1 | sed 's/^/lowest /'; rm -f minmem.log
docker image rm -f build_memory_cap_test >/dev/null 2>&1
echo "build exit: $rc (nonzero = capped correctly)"
