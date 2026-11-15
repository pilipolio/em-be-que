#!/bin/sh
# Convert the WhatsApp recording to MP3 (Safari does not play Ogg Opus reliably).
# Usage: scripts/prepare_audio.sh "<path to .opus>"
set -eu
cd "$(dirname "$0")/.."
mkdir -p assets
ffmpeg -v error -y -i "$1" -ac 1 -b:a 64k assets/song.mp3
echo "wrote assets/song.mp3"
