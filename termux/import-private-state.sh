#!/data/data/com.termux/files/usr/bin/sh
# Import an account bundle that was transferred locally to this phone.
# Usage: ./termux/import-private-state.sh [bundle-directory]
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE=${1:-"$HOME/storage/downloads/yt-reposter-private"}

need_file() {
    if [ ! -f "$1" ]; then
        echo "Missing required private file: $1" >&2
        exit 1
    fi
}

need_file "$SOURCE/config.yaml"
need_file "$SOURCE/credentials/client_secret.json"
need_file "$SOURCE/credentials/token.json"
need_file "$SOURCE/shorts.db"

mkdir -p "$ROOT/credentials"
cp "$SOURCE/config.yaml" "$ROOT/config.yaml"
cp "$SOURCE/credentials/client_secret.json" "$ROOT/credentials/client_secret.json"
cp "$SOURCE/credentials/token.json" "$ROOT/credentials/token.json"
cp "$SOURCE/shorts.db" "$ROOT/shorts.db"
[ -f "$SOURCE/state.json" ] && cp "$SOURCE/state.json" "$ROOT/state.json" || true
chmod 600 "$ROOT/config.yaml" "$ROOT/credentials/client_secret.json" "$ROOT/credentials/token.json"

echo "Private state imported. It remains outside Git."
