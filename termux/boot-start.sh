#!/data/data/com.termux/files/usr/bin/sh
# Copy this to ~/.termux/boot/start-yt-reposter after installing Termux:Boot.
set -eu

ROOT=${YT_REPOSTER_HOME:-"$HOME/yt-reposter"}
[ -x "$ROOT/termux/service.sh" ] || exit 0
mkdir -p "$ROOT/logs"
nohup "$ROOT/termux/service.sh" >>"$ROOT/logs/service.log" 2>&1 &
