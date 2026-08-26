#!/usr/bin/env bash
# Exercise the updater's install-on-startup path across the package restructure.
#
#   tests/run_update_install_test.sh                # default Blender (5.2)
#   tests/run_update_install_test.sh "5.0"
#
# Sandboxes BOTH the scripts dir and the config dir. The config part is not
# optional: the updater derives its staging and backup directories from
# bpy.utils.user_resource('CONFIG'), so an unsandboxed run would write into the
# real Blender config and could stage a bogus update for the real addon. The
# Python side refuses to run if it doesn't see itself inside the sandbox.
#
# Fixture: the addon is installed at the pre-restructure state (from the
# stable-pre-restructure tag) and the working tree is staged as "the update".

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

mkdir -p "$SANDBOX/addons" "$SANDBOX/config" "$SANDBOX/source"

# Old, flat, production-tested build -> installed as the live addon.
git -C "$REPO_ROOT" archive stable-pre-restructure lightgroup_tools \
  | tar -x -C "$SANDBOX/addons"

# Current working tree -> what gets staged as the update.
cp -r "$REPO_ROOT/lightgroup_tools" "$SANDBOX/source/"
find "$SANDBOX" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Blender:  ${BLENDER_VERSION}"
echo "Sandbox:  $SANDBOX"
echo

BLENDER_USER_SCRIPTS="$SANDBOX" \
BLENDER_USER_CONFIG="$SANDBOX/config" \
FESTOON_TEST_SANDBOX="$SANDBOX" \
"$BLENDER_EXE" \
  --background \
  --factory-startup \
  --python "$REPO_ROOT/tests/test_update_install.py" \
  -- "$SANDBOX/source/lightgroup_tools"
