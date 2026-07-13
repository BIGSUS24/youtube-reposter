#!/data/data/com.termux/files/usr/bin/sh
# Set up the public repository on native Termux.  It deliberately does not
# create or fetch account credentials; import-private-state.sh handles those
# from a local, user-controlled transfer.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

pkg update -y
pkg install -y python python-pip python-ensurepip-wheels ffmpeg nodejs git
chmod +x termux/*.sh

python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

mkdir -p credentials downloads logs
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "Created config.yaml from the example. Import private state before starting."
fi

echo "Termux dependencies installed. Next: ./termux/import-private-state.sh"
