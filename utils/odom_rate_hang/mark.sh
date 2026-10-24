#!/usr/bin/env bash
# Append a timestamped marker (e.g. "step rate=1.5") to the running logger's events.log.
set -euo pipefail
dir=$(ls -1dt /mnt/ssd/pdavid/logs/*/ | head -1)
echo "$(date +%s) $*" >> "$dir/events.log"
sync "$dir/events.log"
