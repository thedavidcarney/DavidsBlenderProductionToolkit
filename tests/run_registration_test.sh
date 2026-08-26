#!/usr/bin/env bash
# Run the headless registration regression test against a real Blender.
#
#   tests/run_registration_test.sh                  # default Blender (5.2)
#   tests/run_registration_test.sh "5.0"            # a specific version
#
# The addon is copied into a throwaway scripts directory and Blender is
# pointed at it with BLENDER_USER_SCRIPTS, so your real Blender config,
# your real installed addons, and any staged update are never touched.

set -euo pipefail

BLENDER_VERSION="${1:-5.2}"
BLENDER_EXE="/c/Program Files/Blender Foundation/Blender ${BLENDER_VERSION}/blender.exe"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

if [[ ! -f "$BLENDER_EXE" ]]; then
  echo "Blender ${BLENDER_VERSION} not found at: $BLENDER_EXE" >&2
  echo "Installed versions:" >&2
  ls "/c/Program Files/Blender Foundation/" >&2
  exit 1
fi

# Stage a clean copy of the addon -- no __pycache__, which would otherwise let
# a stale .pyc mask exactly the kind of import problem this test hunts for.
mkdir -p "$SANDBOX/addons"
cp -r "$REPO_ROOT/lightgroup_tools" "$SANDBOX/addons/"
find "$SANDBOX/addons" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Blender:  ${BLENDER_VERSION}"
echo "Sandbox:  $SANDBOX"
echo

BLENDER_USER_SCRIPTS="$SANDBOX" "$BLENDER_EXE" \
  --background \
  --factory-startup \
  --python "$REPO_ROOT/tests/test_registration.py"
