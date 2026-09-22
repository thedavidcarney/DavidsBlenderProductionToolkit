#!/usr/bin/env bash
# Show exactly what the team will see in Blender for a candidate release note.
#
#   ./preview_release_note.sh "Camera Overlay: reference image over the camera frame"
#   ./preview_release_note.sh --prerelease "Diagnostics button"
#
# The note goes in the GitHub release body, and the update popup renders it as
# "What's new" -- so this is the only text most of the team ever reads about a
# release. It gets approved before publishing, every time.
#
# This runs the REAL draw_release_info() from core/updater.py against a
# sandboxed Blender, so the wrapping and truncation shown here are what the
# popup actually produces, not an approximation.

set -euo pipefail

PRERELEASE="False"
if [[ "${1:-}" == "--prerelease" ]]; then
  PRERELEASE="True"
  shift
fi

NOTE="${1:-}"
if [[ -z "$NOTE" ]]; then
  echo "usage: $0 [--prerelease] \"the release note\"" >&2
  exit 1
fi

BLENDER_VERSION="${BLENDER_VERSION:-5.2}"
BLENDER_EXE="/c/Program Files/Blender Foundation/Blender ${BLENDER_VERSION}/blender.exe"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

if [[ ! -f "$BLENDER_EXE" ]]; then
  echo "Blender ${BLENDER_VERSION} not found at: $BLENDER_EXE" >&2
  exit 1
fi

mkdir -p "$SANDBOX/addons" "$SANDBOX/config"
cp -r "$REPO_ROOT/lightgroup_tools" "$SANDBOX/addons/"
find "$SANDBOX/addons" -name '__pycache__' -type d -prune -exec rm -rf {} +

NOTE="$NOTE" PRERELEASE="$PRERELEASE" \
BLENDER_USER_SCRIPTS="$SANDBOX" \
BLENDER_USER_CONFIG="$SANDBOX/config" \
"$BLENDER_EXE" --background --factory-startup --python-expr "
import bpy, os, sys
bpy.ops.preferences.addon_enable(module='lightgroup_tools')
for _n, _m in list(sys.modules.items()):
    if _m is not None and hasattr(_m, 'install_update_on_load'):
        _m._auto_check_done_this_session = True

prefs = bpy.context.preferences.addons['lightgroup_tools'].preferences
updater = sys.modules['lightgroup_tools.core.updater']
prefs.latest_notes = os.environ['NOTE']
prefs.latest_is_prerelease = os.environ['PRERELEASE'] == 'True'
prefs.latest_version = 'X.Y.Z'


class Fake:
    '''Collects the labels the real draw code emits.'''

    def __init__(self, sink):
        self.sink = sink
        self.alert = False

    def label(self, text='', icon=''):
        self.sink.append((text, icon))

    def box(self):
        return Fake(self.sink)

    def column(self, align=False):
        return Fake(self.sink)

    def row(self):
        return Fake(self.sink)

    def separator(self):
        pass

    def operator(self, idname, **kwargs):
        self.sink.append(('[ ' + kwargs.get('text', idname) + ' ]', 'BUTTON'))


lines = []
Fake(lines).label(text='Lightgroup Tools vX.Y.Z is available', icon='INFO')
Fake(lines).label(text='You are running v1.0.17')
updater.draw_release_info(Fake(lines), prefs)
lines.append(('[ Update Now ]   [ Ignore ]', 'BUTTON'))
lines.append(('You can update later -- and roll back after.', 'INFO'))

width = max([len(t) for t, _ in lines] + [44]) + 4
print('')
print('  What the team sees in Blender:')
print('  +' + '-' * width + '+')
for text, icon in lines:
    marker = '!' if icon == 'ERROR' else ' '
    print('  |' + marker + ' ' + text.ljust(width - 2) + '|')
print('  +' + '-' * width + '+')
print('')
raw = os.environ['NOTE']
print('  release body, %d chars: %s' % (len(raw), raw))
print('')
" 2>/dev/null | sed -n '/What the team sees/,$p'
