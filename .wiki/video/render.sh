#!/usr/bin/env bash
# Renders the 360Ghar wiki overview video to overview.mp4.
set -euo pipefail

# Always operate relative to this script's location.
cd "$(dirname "$0")"

echo "==> Installing dependencies (npm install)"
npm install

echo "==> Rendering Video -> overview.mp4 (H.264, CRF 18)"
# --gl=swiftshader ensures consistent headless rendering across environments
# without relying on a host GPU (needed on macOS headless / CI runners).
npx remotion render src/index.ts Video overview.mp4 --codec=h264 --crf=18 --gl=swiftshader

echo "==> Done: $(pwd)/overview.mp4"
ls -lh overview.mp4
