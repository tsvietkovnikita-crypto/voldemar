#!/usr/bin/env bash
# Update Voldemar to the latest code on its branch and restart it:
#
#   sudo bash /home/voldemar/voldemar/deploy/update.sh
#
# (If a file under deploy/ itself changed, run setup-server.sh again instead.)
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo." >&2; exit 1; }

sudo -u voldemar -H bash -c 'cd ~/voldemar && git pull --quiet --ff-only && ~/.local/bin/uv sync --quiet --frozen --no-dev'
systemctl restart voldemar
sleep 5
systemctl --no-pager --lines=8 status voldemar
