#!/usr/bin/env bash
# One-time setup for the phone's one-button bring-up (scripts/phone_ctl.sh, issue #27).
# Run on orintwo as user orintwo, from the synced checkout, with the rover on the wired link:
#
#   scripts/robot_setup/phone_link.sh phone.pub           # file with the phone's public key
#   scripts/robot_setup/phone_link.sh "ssh-ed25519 AAAA…" # or the key itself
#   scripts/robot_setup/phone_link.sh                     # rover part only
#
# Installs
#   1. the phone's key in ~orintwo/.ssh/authorized_keys, restricted to phone_ctl.sh
#   2. an orintwo→rover key (~/.ssh/navws_rover_ed25519), restricted on the rover to
#      rover_wheels_ctl.sh
#   3. the rover files (scripts/robot_setup/rover/ → rover:$ROVER_DIR) and the
#      rover-wheels.service user unit there (rover/install.sh; asks for sudo once, for linger)
# Idempotent; prints what it did. Uses your normal ssh login to the rover (password or key)
# for the setup itself.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
rover_host=${ROVER_HOST:-192.168.1.230}
rover_user=${ROVER_USER:-rover}
rover_dir=${ROVER_DIR:-/home/rover/pdavid/navws_rover}
rover_key=${ROVER_KEY:-$HOME/.ssh/navws_rover_ed25519}
say() { echo "phone_link: $*"; }

# 1. phone key
if (( $# )); then
  if [[ -f $1 ]]; then pub=$(head -n 1 "$1"); else pub=$1; fi
  read -r ktype kbody _ <<<"$pub"
  [[ $ktype == ssh-* || $ktype == ecdsa-* ]] && [[ -n ${kbody:-} ]] || { echo "not a public key: $pub" >&2; exit 1; }
  line="restrict,command=\"$repo/scripts/phone_ctl.sh\" $ktype $kbody phone"
  ak=$HOME/.ssh/authorized_keys
  install -d -m 700 "$HOME/.ssh"; touch "$ak"; chmod 600 "$ak"
  if grep -qxF "$line" "$ak"; then
    say "phone key already in $ak"
  elif grep -qF "$kbody" "$ak"; then
    grep -vF "$kbody" "$ak" > "$ak.tmp"; echo "$line" >> "$ak.tmp"; mv "$ak.tmp" "$ak"; chmod 600 "$ak"
    say "phone key in $ak updated (now restricted to phone_ctl.sh)"
  else
    echo "$line" >> "$ak"; say "phone key added to $ak (restricted to phone_ctl.sh)"
  fi
  id -nG | tr ' ' '\n' | grep -qx docker && say "$USER is in group docker" \
    || say "WARNING: $USER is not in group docker; phone_ctl.sh can't run compose"
else
  say "no phone key given: skipping the orintwo part"
fi

# 2. orintwo → rover key
if [[ -f $rover_key ]]; then
  say "rover key $rover_key exists"
else
  ssh-keygen -q -t ed25519 -N '' -C "orintwo-phone-ctl" -f "$rover_key"
  say "created rover key $rover_key"
fi

# 3. rover files + unit, over one shared connection (one password prompt)
ctl=(-o ControlMaster=auto -o "ControlPath=/tmp/phone_link_%C" -o ControlPersist=60
     -o StrictHostKeyChecking=accept-new)
ssh "${ctl[@]}" "$rover_user@$rover_host" "mkdir -p '$rover_dir'"
rsync -a --delete -e "ssh ${ctl[*]}" "$repo/scripts/robot_setup/rover/" "$rover_user@$rover_host:$rover_dir/"
say "copied scripts/robot_setup/rover/ to $rover_user@$rover_host:$rover_dir"
ssh -t "${ctl[@]}" "$rover_user@$rover_host" "'$rover_dir/install.sh' '$(cat "$rover_key.pub")'"
ssh "${ctl[@]}" -O exit "$rover_user@$rover_host" 2>/dev/null || true

# 4. the restricted key works
if out=$(ssh -i "$rover_key" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=5 \
           "$rover_user@$rover_host" status 2>&1); then
  say "restricted rover key works; rover_wheels_ctl.sh status:"; printf '  %s\n' "$out"
else
  say "WARNING: the restricted rover key doesn't work yet: $out"; exit 1
fi
