#!/usr/bin/env bash
# Install or update Voldemar on an Ubuntu 22.04+ server (ARM64 or x86-64). Safe to re-run.
#
#   sudo bash setup-server.sh [--branch NAME] [--with-cipher] [--no-start]
#
#   --branch NAME    git branch to run (default: main)
#   --with-cipher    also install yt-cipher, needed for YouTube on most cloud servers
#   --no-start       install everything, but don't (re)start the bot
#
# Everything runs as the unprivileged "voldemar" user. The bot's .env (with the Discord token) is
# never downloaded: copy it to /home/voldemar/voldemar/.env yourself.
set -euo pipefail

REPO_URL="https://github.com/tsvietkovnikita-crypto/voldemar.git"
BRANCH="main"
WITH_CIPHER=0
START=1
APP_USER="voldemar"
APP_HOME="/home/$APP_USER"
APP_DIR="$APP_HOME/voldemar"
CIPHER_DIR="$APP_HOME/yt-cipher"
CIPHER_ENV="$APP_HOME/yt-cipher.env"
CIPHER_COMMIT="1e1fd8e2f34ca90cf23545be72e46307bd3d3d2a" # yt-cipher, Aug 6 2026
EJS_COMMIT="cd4e87f52e87ab6d8b318fd3a817adda6fafa8dc"    # the yt-dlp/ejs version it expects

while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --with-cipher) WITH_CIPHER=1; shift ;;
    --no-start) START=0; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo." >&2; exit 1; }

as_app() { sudo -u "$APP_USER" -H bash -c "$1"; }

# Set KEY=VALUE in an env file: replace the line if the key exists, append it otherwise.
set_env() {
  local file="$1" key="$2" value="$3"
  if grep -q "^$key=" "$file"; then
    sed -i "s|^$key=.*|$key=$value|" "$file"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

echo "==> System packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  openjdk-21-jre-headless git curl unzip ca-certificates >/dev/null

echo "==> User $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"

echo "==> uv (Python package manager)"
as_app '[ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh -s -- --quiet'

echo "==> Voldemar ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  as_app "cd '$APP_DIR' && git fetch --quiet origin && git checkout --quiet '$BRANCH' && git pull --quiet --ff-only origin '$BRANCH'"
else
  as_app "git clone --quiet --branch '$BRANCH' '$REPO_URL' '$APP_DIR'"
fi
as_app "cd '$APP_DIR' && ~/.local/bin/uv sync --quiet --frozen --no-dev"

if [ -f "$APP_DIR/.env" ]; then
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

if [ "$WITH_CIPHER" -eq 1 ]; then
  echo "==> yt-cipher"
  as_app '[ -x ~/.deno/bin/deno ] || curl -fsSL https://deno.land/install.sh | sh -s -- -y --no-modify-path >/dev/null'
  [ -d "$CIPHER_DIR/.git" ] || as_app "git clone --quiet https://github.com/kikkia/yt-cipher.git '$CIPHER_DIR'"
  as_app "cd '$CIPHER_DIR' && git fetch --quiet origin && git checkout --quiet --detach '$CIPHER_COMMIT'"
  # yt-cipher needs a patched copy of yt-dlp's ejs library; patch it once per ejs version.
  if [ ! -f "$CIPHER_DIR/.ejs-$EJS_COMMIT" ]; then
    as_app "cd '$CIPHER_DIR' && rm -rf ejs .ejs-* && git clone --quiet https://github.com/yt-dlp/ejs.git ejs \
      && git -C ejs checkout --quiet --detach '$EJS_COMMIT' \
      && ~/.deno/bin/deno run --quiet --allow-read --allow-write ./scripts/patch-ejs.ts \
      && touch '.ejs-$EJS_COMMIT'"
  fi
  if [ ! -f "$CIPHER_ENV" ]; then
    printf 'HOST=127.0.0.1\nPORT=8001\nAPI_TOKEN=%s\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" >"$CIPHER_ENV"
  fi
  chown "$APP_USER:$APP_USER" "$CIPHER_ENV"
  chmod 600 "$CIPHER_ENV"
  # Point the bot at it.
  if [ -f "$APP_DIR/.env" ]; then
    set_env "$APP_DIR/.env" YOUTUBE_CIPHER_URL "http://127.0.0.1:8001"
    set_env "$APP_DIR/.env" YOUTUBE_CIPHER_TOKEN "$(sed -n 's/^API_TOKEN=//p' "$CIPHER_ENV")"
  fi
  install -m 644 "$APP_DIR/deploy/yt-cipher.service" /etc/systemd/system/yt-cipher.service
  systemctl daemon-reload
  systemctl enable --quiet yt-cipher
  systemctl restart yt-cipher
fi

echo "==> systemd service"
install -m 644 "$APP_DIR/deploy/voldemar.service" /etc/systemd/system/voldemar.service
systemctl daemon-reload
systemctl enable --quiet voldemar

if [ ! -f "$APP_DIR/.env" ]; then
  echo "!! $APP_DIR/.env is missing. Copy it there, then run: sudo systemctl restart voldemar"
elif [ "$START" -eq 1 ]; then
  systemctl restart voldemar
  echo "==> Voldemar (re)started. Follow the log with: journalctl -u voldemar -f"
else
  echo "==> Installed, not started (--no-start). Start with: sudo systemctl restart voldemar"
fi
