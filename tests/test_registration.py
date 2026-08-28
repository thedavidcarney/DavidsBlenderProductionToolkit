"""
Headless registration regression test for the toolkit addon.

Run it with tests/run_registration_test.sh, which points Blender at an
isolated config directory so your real install is never touched.

Why this exists
---------------
Splitting the addon into core/ + feature subpackages touches registration
and the reload guard -- the exact code that broke for a tester on v1.0.14
with "module 'lightgroup_tools.updater' has no attribute
LIGHTGROUP_OT_restore_backup".

That failure class is invisible until somebody installs the addon in anger,
so this test drives the paths that produce it:

  1. cold enable       -- fresh Blender, addon_enable
  2. in-session reload -- disable, evict sys.modules, refresh, enable
                          (what updater.install_update_on_load does)
  3. re-exec over live -- importlib.reload of the top module, then
                          register() again (what Blender's Install from Disk
                          does, and the reason the reload guard exists)
  4. teardown          -- clean unregister, no leaked load_post handler
  5. import hygiene    -- static scan for relative imports hidden inside
                          function bodies, which move silently and only fail
                          when a user clicks the button that runs them

After phases 1-3, every class, operator, panel and preference property that
shipped in the production-tested v1.0.15 build must still resolve.

The EXPECTED_* lists below are the contract. If a restructure legitimately
renames something, edit the list deliberately -- don't let it drift quietly.

Network safety: enabling the addon installs a load_post handler that can
fire an auto-update check against GitHub. Every enable here is followed by
pinning updater._auto_check_done_this_session = True, so a test run never
hits the network and never stages an update.
"""

import atexit
import importlib
import os
import sys

import bpy

ADDON = "lightgroup_tools"

# --- The contract: what v1.0.15 registers -----------------------------------

EXPECTED_OPERATORS = (
    "lightgroup.clear_all_lightgroups",
    "lightgroup.create_for_each_light",
    "lightgroup.denoise_all_cycles",
    "lightgroup.assign_to_lightgroup",
    "lightgroup.check_updates",
    "lightgroup.download_update",
    "lightgroup.restore_backup",
    "lightgroup.dismiss_install_notice",
    "lightgroup.update_dialog",
    "lightgroup.restart_dialog",
    "lightgroup.close_dialog",
    "festoon.place_strand",
    "festoon.place_spiral",
    "festoon.select_controls",
)

# NB: two registered classes are deliberately absent from this list because
# neither appears in bpy.types under its class name:
#   LightgroupToolsPreferences -- an AddonPreferences registers under its
#     bl_idname (the module name) instead.
#   FestoonSettings -- a PropertyGroup is reached through the ID property it
#     is attached to.
# Both are verified functionally in assert_fully_registered() instead.
EXPECTED_CLASSES = (
    "LIGHTGROUP_OT_clear_all_lightgroups",
    "LIGHTGROUP_OT_create_for_each_light",
    "LIGHTGROUP_OT_denoise_all_cycles",
    "LIGHTGROUP_OT_assign_to_lightgroup",
    "LIGHTGROUP_OT_check_updates",
    "LIGHTGROUP_OT_download_update",
    "LIGHTGROUP_OT_restore_backup",
    "LIGHTGROUP_OT_dismiss_install_notice",
    "LIGHTGROUP_OT_update_dialog",
    "LIGHTGROUP_OT_restart_dialog",
    "LIGHTGROUP_OT_close_dialog",
    "LIGHTGROUP_PT_main_panel",
    "LIGHTGROUP_PT_compositor_panel",
    "LIGHTGROUP_PT_viewlayer_panel",
    "FESTOON_OT_place_strand",
    "FESTOON_OT_place_spiral",
    "FESTOON_OT_select_controls",
    "FESTOON_PT_main_panel",
    "FESTOON_PT_strand_panel",
)

# Panel placement is part of the contract too: the restructure must NOT move
# the lightgroup panels out of the 'Lightgroups' tab. Festoon gets its own.
# The properties-editor panel has no tab, hence None.
EXPECTED_PANELS = {
    "LIGHTGROUP_PT_main_panel": ("VIEW_3D", "Lightgroups"),
    "LIGHTGROUP_PT_compositor_panel": ("NODE_EDITOR", "Lightgroups"),
    "LIGHTGROUP_PT_viewlayer_panel": ("PROPERTIES", None),
    # Festoon Clicker is deliberately a SEPARATE tab. If these ever read
    # 'Lightgroups', an unrelated building tool has leaked into the panel the
    # team uses on every job.
    "FESTOON_PT_main_panel": ("VIEW_3D", "Festoon Clicker"),
    "FESTOON_PT_strand_panel": ("VIEW_3D", "Festoon Clicker"),
}

EXPECTED_PREF_PROPS = (
    "update_available",
    "latest_version",
    "download_url",
    "update_downloaded",
    "staged_update_path",
    "staged_update_version",
    "backup_available",
    "backup_version",
    "update_just_installed",
    "last_installed_version",
    "last_auto_check",
)

# --- Tiny assertion harness -------------------------------------------------

FAILURES = []

# An uncaught exception aborts this script but Blender still exits 0, so a
# crashed run looks identical to a clean one to any caller checking the exit
# code. Insist on reaching an explicit verdict.
_VERDICT_REACHED = []


def _abort_guard():
    if not _VERDICT_REACHED:
        print("TEST ABORTED before reaching a verdict -- see traceback above")
        sys.stdout.flush()
        os._exit(1)


atexit.register(_abort_guard)



def check(condition, message):
    if not condition:
        FAILURES.append(message)
    return bool(condition)


def find_updater_module():
    """Locate the updater by what it DOES, not where it lives.

    It moved from lightgroup_tools.updater to lightgroup_tools.core.updater in
    the restructure and could move again, so match on the handler function
    instead of hardcoding a dotted path.
    """
    for name, module in list(sys.modules.items()):
        if name != ADDON and not name.startswith(ADDON + "."):
            continue
        if module is not None and hasattr(module, "install_update_on_load"):
            return module
    return None


def silence_auto_check():
    """Stop the load_post handler from phoning GitHub during a test run."""
    updater = find_updater_module()
    if updater is not None:
        updater._auto_check_done_this_session = True


def assert_fully_registered(phase):
    """Every part of the v1.0.15 contract must resolve."""
    for cls_name in EXPECTED_CLASSES:
        check(hasattr(bpy.types, cls_name),
              "[" + phase + "] bpy.types." + cls_name + " missing")

    for idname in EXPECTED_OPERATORS:
        category, _, name = idname.partition(".")
        group = getattr(bpy.ops, category, None)
        check(group is not None and hasattr(group, name),
              "[" + phase + "] operator " + idname + " does not resolve")

    for panel, (space, tab) in EXPECTED_PANELS.items():
        cls = getattr(bpy.types, panel, None)
        if not check(cls is not None, "[" + phase + "] panel " + panel + " missing"):
            continue
        check(cls.bl_space_type == space,
              "[" + phase + "] " + panel + ".bl_space_type is "
              + repr(cls.bl_space_type) + ", expected " + repr(space))
        if tab is not None:
            actual = getattr(cls, "bl_category", None)
            check(actual == tab,
                  "[" + phase + "] " + panel + ".bl_category is "
                  + repr(actual) + ", expected " + repr(tab))

    prefs_entry = bpy.context.preferences.addons.get(ADDON)
    if check(prefs_entry is not None,
             "[" + phase + "] addon '" + ADDON + "' not in context.preferences.addons"):
        prefs = prefs_entry.preferences
        if check(prefs is not None, "[" + phase + "] preferences object is None"):
            for prop in EXPECTED_PREF_PROPS:
                check(hasattr(prefs, prop),
                      "[" + phase + "] preference property '" + prop + "' missing")

            # Reached through the live prefs object rather than by importing it
            # from a known module, so this keeps working after the preferences
            # class moves into core/ during the restructure.
            prefs_cls = type(prefs)
            check(prefs_cls.is_registered,
                  "[" + phase + "] preferences class " + prefs_cls.__name__
                  + " reports is_registered False")
            check(prefs_cls.bl_idname == ADDON,
                  "[" + phase + "] preferences bl_idname is "
                  + repr(prefs_cls.bl_idname) + ", expected " + repr(ADDON)
                  + " (prefs bind to the addon by module name -- a mismatch"
                  + " silently orphans every saved preference)")

    # The updater's load_post handler is what installs staged updates and runs
    # the auto-check. Losing it in a restructure would silently kill both.
    updater = find_updater_module()
    if check(updater is not None, "[" + phase + "] updater module not found in sys.modules"):
        check(updater.install_update_on_load in bpy.app.handlers.load_post,
              "[" + phase + "] install_update_on_load not registered on load_post")

    # Festoon's scene PointerProperty is registered separately from the class
    # list, after the classes, because it references FestoonSettings.
    check(hasattr(bpy.types.Scene, "festoon_settings"),
          "[" + phase + "] Scene.festoon_settings not registered")
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        settings = getattr(scene, "festoon_settings", None)
        if check(settings is not None,
                 "[" + phase + "] scene.festoon_settings does not resolve"):
            check(type(settings).__name__ == "FestoonSettings",
                  "[" + phase + "] festoon_settings is a "
                  + type(settings).__name__ + ", expected FestoonSettings")
            for field in ("sag_along", "sag_v_ratio", "flatness", "bulb_object"):
                check(hasattr(settings, field),
                      "[" + phase + "] festoon setting '" + field + "' missing")


# --- Phase 1: cold enable ---------------------------------------------------

print("\n=== phase 1: cold enable (" + bpy.app.version_string + ") ===")
try:
    bpy.ops.preferences.addon_enable(module=ADDON)
    silence_auto_check()
    assert_fully_registered("cold enable")
except Exception as exc:  # noqa: BLE001 - a raise here IS the test result
    FAILURES.append("[cold enable] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 2: in-session reload (the updater's own path) --------------------

print("=== phase 2: in-session reload (sys.modules eviction) ===")
try:
    bpy.ops.preferences.addon_disable(module=ADDON)

    evicted = [m for m in sys.modules if m == ADDON or m.startswith(ADDON + ".")]
    for module_name in evicted:
        del sys.modules[module_name]
    print("    evicted " + str(len(evicted)) + " module(s): " + str(sorted(evicted)))

    bpy.ops.preferences.addon_refresh()
    bpy.ops.preferences.addon_enable(module=ADDON)
    silence_auto_check()
    assert_fully_registered("in-session reload")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[in-session reload] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 3: re-exec over a live addon (what the reload guard is for) ------

print("=== phase 3: importlib.reload over live addon ===")
try:
    module = sys.modules[ADDON]
    module.unregister()

    # This is the guard's branch: submodules are already in the module globals,
    # so a plain import would hand back stale objects. A broken recursive reload
    # blows up right here.
    importlib.reload(module)

    check(hasattr(module, "classes"),
          "[reload guard] reloaded module has no 'classes' tuple")
    for cls in getattr(module, "classes", ()):
        check(isinstance(cls, type),
              "[reload guard] classes entry is not a class: " + repr(cls))

    module.register()
    silence_auto_check()
    assert_fully_registered("reload guard")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[reload guard] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 4: clean teardown ------------------------------------------------

print("=== phase 4: clean unregister ===")
try:
    updater = find_updater_module()
    bpy.ops.preferences.addon_disable(module=ADDON)
    if updater is not None:
        check(updater.install_update_on_load not in bpy.app.handlers.load_post,
              "[teardown] load_post handler survived addon_disable (handler leak)")
    for cls_name in EXPECTED_CLASSES:
        check(not hasattr(bpy.types, cls_name),
              "[teardown] bpy.types." + cls_name + " still registered after disable")
    check(bpy.context.preferences.addons.get(ADDON) is None,
          "[teardown] addon still present in context.preferences.addons after disable")
    check(not hasattr(bpy.types.Scene, "festoon_settings"),
          "[teardown] Scene.festoon_settings leaked past unregister")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[teardown] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 5: relative imports must sit at module scope ---------------------
#
# The restructure turned up a `from . import bl_info` buried inside an
# operator's execute(). Moving updater.py into core/ silently repointed it at
# the wrong package, and because it only runs when a user clicks "Check for
# Updates", nothing above would have caught it -- import succeeds, registration
# succeeds, the button breaks in production.
#
# Rather than test for that one instance, forbid the shape: a relative import
# inside a function or class body only runs when that code path runs, so it is
# invisible to every import-time check we have.
#
# Module-level control flow is fine and deliberately allowed -- the reload
# guard's own if/else needs `from . import core` inside it. That still executes
# on every import, so a bad move there fails loudly and instantly.

print("=== phase 5: relative imports outside function/class bodies ===")
try:
    import ast
    import os

    package_root = os.path.dirname(sys.modules[ADDON].__file__)
    scanned = 0
    SCOPED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

    for dirpath, _dirnames, filenames in os.walk(package_root):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            scanned += 1

            relative_to_source = os.path.relpath(path, package_root)
            # Nested defs would report the same import twice, so dedupe.
            reported = set()
            for scope in ast.walk(tree):
                if not isinstance(scope, SCOPED):
                    continue
                for node in ast.walk(scope):
                    if not isinstance(node, ast.ImportFrom) or node.level == 0:
                        continue
                    if node.lineno in reported:
                        continue
                    reported.add(node.lineno)
                    check(False,
                          "[import hygiene] " + relative_to_source + ":"
                          + str(node.lineno) + " has a relative import inside "
                          + scope.name + "() ('from " + ("." * node.level)
                          + (node.module or "") + " import ...')."
                          + " Move it to module scope, or reach the target"
                          + " through sys.modules[__name__.partition('.')[0]].")

    print("    scanned " + str(scanned) + " module(s) under " + package_root)
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[import hygiene] raised " + type(exc).__name__ + ": " + str(exc))


_VERDICT_REACHED.append(True)
# --- Result -----------------------------------------------------------------

print("\n" + "=" * 60)
if FAILURES:
    print("REGISTRATION TEST: FAILED (" + str(len(FAILURES)) + " problem(s))")
    for failure in FAILURES:
        print("  FAIL  " + failure)
    print("=" * 60)
    sys.exit(1)

print("REGISTRATION TEST: PASSED")
print("  " + str(len(EXPECTED_CLASSES)) + " classes, "
      + str(len(EXPECTED_OPERATORS)) + " operators, "
      + str(len(EXPECTED_PREF_PROPS)) + " prefs verified across 5 phases")
print("=" * 60)
