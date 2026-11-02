#!/usr/bin/env bash
# Headless tests for the single-EXR denoise setup and the output check.
#
#   tests/run_single_exr_test.sh          # default Blender (5.2)
#   tests/run_single_exr_test.sh "5.1"    # older versions: two-file setup kept
#
# Includes real Cycles animation renders, read back from disk.
# Sandboxes the scripts and config dirs so your real Blender is untouched.

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
BLENDER_USER_EXTENSIONS="$SANDBOX/extensions" \
"$BLENDER_EXE" \
  --background \
  --factory-startup \
  --python "$REPO_ROOT/tests/test_single_exr.py"
