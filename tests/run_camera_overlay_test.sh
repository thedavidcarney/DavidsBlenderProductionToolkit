#!/usr/bin/env bash
# Headless tests for the Camera Overlay tool.
#
#   tests/run_camera_overlay_test.sh          # default Blender (5.2)
#   tests/run_camera_overlay_test.sh "5.0"
#
# From 5.2 on this compiles the real shader and checks the pixels it draws.
# Earlier versions have no gpu.init(), so the GPU phases are skipped and the
# run reports that it skipped them.
#
# Sandboxes the scripts dir so your real Blender install is untouched.

set -euo pipefail

BLENDER_VERSION="${1:-5.2}"
BLENDER_EXE="/c/Program Files/Blender Foundation/Blender ${BLENDER_VERSION}/blender.exe"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

if [[ ! -f "$BLENDER_EXE" ]]; then
  echo "Blender ${BLENDER_VERSION} not found at: $BLENDER_EXE" >&2
  exit 1
fi

mkdir -p "$SANDBOX/addons" "$SANDBOX/config"
cp -r "$REPO_ROOT/lightgroup_tools" "$SANDBOX/addons/"
find "$SANDBOX/addons" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Blender:  ${BLENDER_VERSION}"
echo

BLENDER_USER_SCRIPTS="$SANDBOX" \
BLENDER_USER_CONFIG="$SANDBOX/config" \
"$BLENDER_EXE" \
  --background \
  --factory-startup \
  --python "$REPO_ROOT/tests/test_camera_overlay.py"
