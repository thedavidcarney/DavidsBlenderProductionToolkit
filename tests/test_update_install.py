"""
Headless test of the updater's install-on-startup path across the restructure.

Run it with tests/run_update_install_test.sh, which sandboxes BOTH the scripts
dir and the config dir. That second part matters: _get_update_dir() and
_get_backup_dir() hang off bpy.utils.user_resource('CONFIG'), so without
BLENDER_USER_CONFIG this test would stage updates and write backups into the
real Blender config. The test refuses to run if it detects that.

Why this exists
---------------
The package restructure is the first update that changes the addon's directory
SHAPE, and the install handler copies a staged folder over the live one. Two
distinct transitions have to work, and only one of them is obvious:

  A. v1.0.15 (flat) -> restructured
     The updater doing the work is the OLD flat one. Its `addon_dir` resolution
     was already correct, so this transition looks fine -- but it leaves the
     now-dead flat updater.py / operators.py behind unless they're cleaned up.

  B. restructured -> next restructured build
     The updater doing the work now lives in core/. Before the fix it resolved
     addon_dir as os.path.dirname(__file__), which is .../lightgroup_tools/core
     rather than .../lightgroup_tools -- so it would have installed the new
     build INSIDE core/ and backed up only core/.

B is the dangerous one: shipping the restructure would appear to work perfectly
(because A is what everyone runs first), and then the FOLLOWING release would
brick every install. That's the whole reason the restructure ships alone.
"""

import os
import shutil
import sys

import bpy

ADDON = "lightgroup_tools"

FAILURES = []


def check(condition, message):
    if not condition:
        FAILURES.append(message)
    return bool(condition)


def updater_module():
    for name, module in list(sys.modules.items()):
        if (name == ADDON or name.startswith(ADDON + ".")) and module is not None:
            if hasattr(module, "install_update_on_load"):
                return module
    return None


def addon_dir():
    return os.path.dirname(os.path.realpath(sys.modules[ADDON].__file__))


def tree(root):
    """Relative paths of every file under root, for readable assertions."""
    found = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for filename in filenames:
            if filename.endswith(".pyc"):
                continue
            found.add(os.path.relpath(os.path.join(dirpath, filename), root).replace("\\", "/"))
    return found


# --- Safety: refuse to touch the real Blender config ------------------------

config_dir = bpy.utils.user_resource('CONFIG')
sandbox = os.environ.get("FESTOON_TEST_SANDBOX", "")

if not sandbox or os.path.realpath(sandbox) not in os.path.realpath(config_dir):
    print("REFUSING TO RUN: config dir is not inside the test sandbox.")
    print("  config:  " + config_dir)
    print("  sandbox: " + str(sandbox))
    print("  This test writes backups and staged updates next to the config dir;")
    print("  running it unsandboxed would touch the real Blender install.")
    sys.exit(2)

# The source build to stage as 'the update', passed after -- on the CLI.
staging_source = sys.argv[sys.argv.index("--") + 1]


# --- Helpers ----------------------------------------------------------------

def stage_update(version_label):
    """Copy the restructured build into the updater's own staging location."""
    updater = updater_module()
    update_base = updater._get_update_dir()
    if os.path.exists(update_base):
        shutil.rmtree(update_base)
    os.makedirs(update_base, exist_ok=True)

    staged_path = os.path.join(update_base, ADDON)
    shutil.copytree(staging_source, staged_path,
                    ignore=shutil.ignore_patterns('__pycache__'))

    prefs = bpy.context.preferences.addons[ADDON].preferences
    prefs.staged_update_path = staged_path
    prefs.staged_update_version = version_label
    prefs.update_downloaded = True
    return staged_path


def run_install():
    updater = updater_module()
    updater._auto_check_done_this_session = True   # no network
    updater.install_update_on_load(None)


# --- Transition A: flat v1.0.15 -> restructured -----------------------------

print("\n=== transition A: flat v1.0.15 -> restructured ===")

bpy.ops.preferences.addon_enable(module=ADDON)
updater_module()._auto_check_done_this_session = True

installed = addon_dir()
before = tree(installed)
print("    before: " + str(sorted(before)))
check("updater.py" in before,
      "[A] fixture is wrong: expected a FLAT v1.0.15 install to start from")

stage_update("1.0.16")
run_install()

after = tree(installed)
print("    after:  " + str(sorted(after)))

check("core/updater.py" in after, "[A] core/updater.py missing after install")
check("lightgroups/operators.py" in after, "[A] lightgroups/operators.py missing after install")
check("lightgroups/panels.py" in after, "[A] lightgroups/panels.py missing after install")
check("__init__.py" in after, "[A] __init__.py missing after install")

# The flat modules SURVIVE this transition, and that is expected, not a bug.
# The code performing this install is v1.0.15's updater, which predates the
# orphan cleanup -- an installer can only run cleanup logic it already has.
# They're inert (nothing imports them) and get removed by the next update,
# which transition B below asserts. Pinned here so the one-release window is
# a documented fact rather than a surprise.
check("updater.py" in after,
      "[A] flat updater.py unexpectedly gone -- if the old updater learned to "
      "clean orphans, update this expectation and B's")
check("operators.py" in after,
      "[A] flat operators.py unexpectedly gone -- see above")

# The backup must capture the TOP-LEVEL package, not a subdirectory of it.
backup = updater_module()._get_backup_dir()
backup_tree = tree(backup)
check("updater.py" in backup_tree,
      "[A] backup does not contain the old flat updater.py -- backed up the wrong dir? "
      + str(sorted(backup_tree)))
check("__init__.py" in backup_tree,
      "[A] backup does not contain __init__.py -- backed up the wrong dir")

prefs = bpy.context.preferences.addons[ADDON].preferences
check(not prefs.update_downloaded, "[A] update_downloaded flag not cleared")
# update_just_installed is asserted in B, where OUR code is the one setting it.
# In A it's v1.0.15's behaviour, and the in-session reload re-creates the
# preferences object, so reading it back here measures the old build, not this
# change.


# --- Transition B: restructured -> next restructured build ------------------
#
# The live addon on disk is now the restructured build, and crucially the
# updater running the install lives in core/. This is where a __file__-derived
# addon_dir installs one level too deep.

print("\n=== transition B: restructured -> next restructured build ===")

# Re-enable so the freshly installed (restructured) code is what runs.
try:
    bpy.ops.preferences.addon_disable(module=ADDON)
except Exception:
    pass
for name in [m for m in sys.modules if m == ADDON or m.startswith(ADDON + ".")]:
    del sys.modules[name]
bpy.ops.preferences.addon_refresh()
bpy.ops.preferences.addon_enable(module=ADDON)
updater_module()._auto_check_done_this_session = True

running_updater = updater_module()
print("    updater now running from: " + running_updater.__name__)
check(running_updater.__name__ == ADDON + ".core.updater",
      "[B] fixture is wrong: expected the restructured updater to be live, got "
      + running_updater.__name__)

stage_update("1.0.17")
run_install()

after_b = tree(addon_dir())
print("    after:  " + str(sorted(after_b)))

check("core/updater.py" in after_b, "[B] core/updater.py missing after second install")
check("lightgroups/operators.py" in after_b, "[B] lightgroups/operators.py missing after second install")

# Now the restructured updater IS the installer, so the orphans left behind by
# transition A must finally be gone.
check("updater.py" not in after_b,
      "[B] pre-restructure updater.py was not cleaned up by the new installer")
check("operators.py" not in after_b,
      "[B] pre-restructure operators.py was not cleaned up by the new installer")

# The signature of the bug: the staged build copied INSIDE core/.
check(not os.path.exists(os.path.join(addon_dir(), "core", "core")),
      "[B] install landed inside core/ -- addon_dir resolved one level too deep")
check(not os.path.exists(os.path.join(addon_dir(), "core", "lightgroups")),
      "[B] install landed inside core/ -- addon_dir resolved one level too deep")
check(not any(p.startswith("core/core/") or p.startswith("core/lightgroups/") for p in after_b),
      "[B] nested package copy detected: " + str(sorted(after_b)))

# And the backup must again be the whole package, not just core/.
backup_tree_b = tree(running_updater._get_backup_dir())
check("__init__.py" in backup_tree_b and "core/updater.py" in backup_tree_b,
      "[B] backup is not the top-level package -- got " + str(sorted(backup_tree_b)))

prefs_b = bpy.context.preferences.addons[ADDON].preferences
print("    DIAG update_just_installed=" + repr(prefs_b.update_just_installed)
      + " last_installed_version=" + repr(prefs_b.last_installed_version)
      + " backup_available=" + repr(prefs_b.backup_available)
      + " backup_version=" + repr(prefs_b.backup_version))
check(not prefs_b.update_downloaded,
      "[B] update_downloaded flag not cleared -- would re-install on every startup")

# KNOWN, PRE-EXISTING: every preference reads back at its default here --
# update_just_installed, last_installed_version, backup_available and
# backup_version all reset, even though the install log shows them being set and
# a backup being written. The in-session reload (addon_disable -> addon_enable)
# re-creates the AddonPreferences instance from defaults.
#
# save_userpref() runs BEFORE that reload, so the values are on disk and return
# on the next Blender start -- which is why nobody has noticed. The visible
# effect is that the "Update installed, restart Blender" banner and the "Restore
# Previous Version" button are both missing for the remainder of the session
# that installed the update.
#
# v1.0.15 behaves identically (transition A shows the same), so the restructure
# did not introduce it, and fixing it here would break this release's
# "nothing user-visible changed" contract. Asserted as-is so that a future fix
# trips this test rather than passing silently.
check(not prefs_b.update_just_installed,
      "[B] update_just_installed now SURVIVES the in-session reload. That's the "
      "known prefs-reset bug being fixed -- good, but update this expectation.")

# Finally: the addon must still actually work.
try:
    bpy.ops.preferences.addon_disable(module=ADDON)
    for name in [m for m in sys.modules if m == ADDON or m.startswith(ADDON + ".")]:
        del sys.modules[name]
    bpy.ops.preferences.addon_refresh()
    bpy.ops.preferences.addon_enable(module=ADDON)
    updater_module()._auto_check_done_this_session = True
    check(hasattr(bpy.ops.lightgroup, "denoise_all_cycles"),
          "[B] addon does not register after two consecutive updates")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[B] addon failed to re-enable after two updates: "
                    + type(exc).__name__ + ": " + str(exc))


# --- Result -----------------------------------------------------------------

print("\n" + "=" * 60)
if FAILURES:
    print("UPDATE INSTALL TEST: FAILED (" + str(len(FAILURES)) + " problem(s))")
    for failure in FAILURES:
        print("  FAIL  " + failure)
    print("=" * 60)
    sys.exit(1)

print("UPDATE INSTALL TEST: PASSED")
print("  flat->restructured and restructured->restructured both install cleanly")
print("=" * 60)
