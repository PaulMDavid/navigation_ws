#!/usr/bin/env bash
# Rover side of scripts/robot_setup/phone_link.sh (run there as user rover, from this folder):
#   ./install.sh "<orintwo's public key line>"
# - orintwo's key in ~/.ssh/authorized_keys, restricted to rover_wheels_ctl.sh
# - rover-wheels.service as a systemd user unit (not enabled at boot), linger on
# Idempotent; prints what it did.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
key=${1:?usage: install.sh "<public key line>"}
say() { echo "rover: $*"; }

# 1. restricted key
read -r ktype kbody _ <<<"$key"
[[ $ktype == ssh-* && -n $kbody ]] || { echo "not a public key: $key" >&2; exit 1; }
line="restrict,command=\"$here/rover_wheels_ctl.sh\" $ktype $kbody orintwo-phone-ctl"
ak=$HOME/.ssh/authorized_keys
install -d -m 700 "$HOME/.ssh"; touch "$ak"; chmod 600 "$ak"
if grep -qxF "$line" "$ak"; then
  say "orintwo key already in $ak"
elif grep -qF "$kbody" "$ak"; then
  grep -vF "$kbody" "$ak" > "$ak.tmp"; echo "$line" >> "$ak.tmp"; mv "$ak.tmp" "$ak"; chmod 600 "$ak"
  say "orintwo key in $ak updated (now restricted to rover_wheels_ctl.sh)"
else
  echo "$line" >> "$ak"; say "orintwo key added to $ak (restricted to rover_wheels_ctl.sh)"
fi

# 2. user unit
unit_dir=$HOME/.config/systemd/user
install -d "$unit_dir"
new=$(sed "s|@DIR@|$here|" "$here/rover-wheels.service")
if [[ -f $unit_dir/rover-wheels.service ]] && [[ $(cat "$unit_dir/rover-wheels.service") == "$new" ]]; then
  say "rover-wheels.service unchanged"
else
  printf '%s\n' "$new" > "$unit_dir/rover-wheels.service"; say "installed $unit_dir/rover-wheels.service"
fi
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
systemctl --user daemon-reload && say "systemctl --user daemon-reload"

# 3. linger: the user manager (and the unit) must outlive the ssh session that starts it
if [[ $(loginctl show-user "$USER" -p Linger --value 2>/dev/null) == yes ]]; then
  say "linger already on for $USER"
else
  sudo loginctl enable-linger "$USER" && say "linger enabled for $USER (sudo)"
fi

# 4. things the unit needs
source "$here/rover_wheels_common.sh"
[[ -r $WHEELS_WS/install/setup.bash ]] && say "found $WHEELS_WS/install" || say "WARNING: $WHEELS_WS/install/setup.bash missing"
command -v "$MDTOOL" >/dev/null && say "found $(command -v "$MDTOOL")" || say "WARNING: $MDTOOL not in PATH (set MDTOOL in ~/.config/rover-wheels.env)"
if tmux has-session -t wheels 2>/dev/null; then
  say "WARNING: tmux session 'wheels' is running; stop it before using rover-wheels.service"
fi
