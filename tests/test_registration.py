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
  6. isolation         -- a building tool that fails to register must not
                          take Lightgroups down with it
  7. diagnostics       -- the support button writes exactly one file, inside
                          the config dir, and never dirties the open .blend
  8. panel draw        -- the Lightgroups tab draws in every update state,
                          including the one that only exists after a release
                          is published

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
    "lightgroup.write_diagnostics",
)

# NB: two registered classes are deliberately absent from this list because
# neither appears in bpy.types under its class name:
#   LightgroupToolsPreferences -- an AddonPreferences registers under its
#     bl_idname (the module name) instead.
#   FestoonSettings, CameraOverlaySettings -- a PropertyGroup is reached
#     through the ID property it is attached to.
# All are verified functionally in assert_fully_registered() instead.
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
    "LIGHTGROUP_OT_write_diagnostics",
    "CAMOVERLAY_PT_main_panel",
    "CAMOVERLAY_PT_display_panel",
    "CAMOVERLAY_PT_transform_panel",
    "CAMOVERLAY_PT_support_panel",
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
    # Camera Overlay is a third separate tab, for the same reason.
    "CAMOVERLAY_PT_main_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_display_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_transform_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_support_panel": ("VIEW_3D", "Camera Overlay"),
}

EXPECTED_PREF_PROPS = (
    "update_available",
    "latest_version",
    "download_url",
    "latest_notes",
    "latest_is_prerelease",
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

    # get_rna_type(), NOT hasattr.
    #
    # bpy.ops attribute access is entirely lazy: hasattr(bpy.ops.totally_fake,
    # "nope") is True, and even .idname() on it returns without error. An
    # earlier version of this check used hasattr and was therefore vacuous --
    # it would have passed with every operator missing. get_rna_type() raises
    # KeyError for an unregistered operator, and returns the class identifier,
    # so it also confirms the idname maps to the class we expect rather than
    # merely to something.
    for idname in EXPECTED_OPERATORS:
        category, _, name = idname.partition(".")
        expected_class = category.upper() + "_OT_" + name
        group = getattr(bpy.ops, category, None)
        operator = getattr(group, name, None) if group is not None else None
        if not check(operator is not None,
                     "[" + phase + "] operator " + idname + " is not reachable"):
            continue
        try:
            identifier = operator.get_rna_type().identifier
        except (KeyError, RuntimeError, AttributeError) as error:
            FAILURES.append("[" + phase + "] operator " + idname
                            + " is not registered (" + type(error).__name__ + ")")
            continue
        check(identifier == expected_class,
              "[" + phase + "] operator " + idname + " resolves to "
              + identifier + ", expected " + expected_class)

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

    # Camera Overlay's scene PointerProperty, same arrangement.
    check(hasattr(bpy.types.Scene, "cam_overlay"),
          "[" + phase + "] Scene.cam_overlay not registered")
    if scene is not None:
        overlay_settings = getattr(scene, "cam_overlay", None)
        if check(overlay_settings is not None,
                 "[" + phase + "] scene.cam_overlay does not resolve"):
            check(type(overlay_settings).__name__ == "CameraOverlaySettings",
                  "[" + phase + "] cam_overlay is a "
                  + type(overlay_settings).__name__
                  + ", expected CameraOverlaySettings")
            # `image` being an Image pointer rather than a path string is the
            # single decision the whole tool rests on, so it is worth pinning:
            # a StringProperty here would reintroduce the entire bug class.
            check(type(overlay_settings).bl_rna
                  .properties["image"].type == 'POINTER',
                  "[" + phase + "] cam_overlay.image is not a PointerProperty"
                  " -- a path string would break relative paths and packing")
            for field in ("enabled", "opacity", "mode", "channel", "threshold",
                          "invert", "tint", "fit", "scale", "offset_x",
                          "offset_y", "rotation", "flip_x", "flip_y"):
                check(hasattr(overlay_settings, field),
                      "[" + phase + "] cam_overlay setting '" + field
                      + "' missing")


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
    check(not hasattr(bpy.types.Scene, "cam_overlay"),
          "[teardown] Scene.cam_overlay leaked past unregister")

    # A leaked draw handler keeps drawing against unregistered properties,
    # which is a crash rather than a cosmetic bug. The overlay module also
    # owns its own load_post handler, separate from the updater's.
    overlay_module = sys.modules.get(ADDON + ".camera_overlay.overlay")
    if check(overlay_module is not None,
             "[teardown] camera_overlay.overlay not found in sys.modules"):
        check(not overlay_module.handler_registered(),
              "[teardown] camera overlay draw handler survived addon_disable")
    package = sys.modules.get(ADDON + ".camera_overlay")
    if package is not None:
        check(package._on_load not in bpy.app.handlers.load_post,
              "[teardown] camera overlay load_post handler survived disable")
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


# --- Phase 6: a broken building tool must not sink the workhorse ------------
#
# Blender aborts addon_enable on the first exception out of register(). When
# camera_overlay.register() raised during development, the result was NOT a
# clean failure: the addon was left marked DISABLED while its classes stayed
# registered -- so Lightgroups half-worked for that session and would have
# been gone entirely after the next restart, preferences orphaned.
#
# Lightgroups is used on every job. Festoon and Camera Overlay are building
# aids that touch the GPU and the depsgraph, where platform- and
# driver-specific failures live. So those two are isolated, and this asserts
# the isolation actually holds rather than trusting the try/except by eye.

print("=== phase 6: a failing building tool must not break Lightgroups ===")

try:
    bpy.ops.preferences.addon_disable(module=ADDON)
    for name in [n for n in sys.modules
                 if n == ADDON or n.startswith(ADDON + ".")]:
        del sys.modules[name]

    import importlib

    package = importlib.import_module(ADDON)

    # Break each building tool in turn, the way a driver fault would.
    for tool_name in ("camera_overlay", "festoon"):
        tool = getattr(package, tool_name)
        original = tool.register

        def _explode():
            raise RuntimeError("simulated %s failure" % tool_name)

        tool.register = _explode
        try:
            package.register()
            enabled_ok = True
        except Exception as exc:
            enabled_ok = False
            FAILURES.append("[isolation] a failing " + tool_name
                            + " aborted the whole addon's register(): "
                            + type(exc).__name__ + ": " + str(exc))
        finally:
            tool.register = original

        if enabled_ok:
            # The production tool has to be fully there regardless.
            check(hasattr(bpy.types, "LIGHTGROUP_OT_denoise_all_cycles"),
                  "[isolation] denoise operator missing after a "
                  + tool_name + " failure")
            check(hasattr(bpy.types, "LIGHTGROUP_PT_main_panel"),
                  "[isolation] Lightgroups panel missing after a "
                  + tool_name + " failure")
            try:
                bpy.ops.lightgroup.denoise_all_cycles.get_rna_type()
            except Exception:
                FAILURES.append("[isolation] lightgroup.denoise_all_cycles is"
                                " unreachable after a " + tool_name
                                + " failure")
            package.unregister()

    print("    Lightgroups survives a failure in either building tool")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[isolation] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 7: the diagnostics button must not touch anyone's work ----------
#
# This runs on other people's machines, mid-season, while they have real jobs
# open. The button is allowed to write exactly ONE file, under Blender's own
# config directory, beside the updater's staging and backup dirs. It must not
# write near a .blend, a render output, or anything else the artist owns, and
# it must not modify the open file.

print("=== phase 7: diagnostics writes only where it should ===")

try:
    config_root = os.path.realpath(bpy.utils.user_resource('CONFIG'))
    sandbox = os.environ.get("BLENDER_USER_CONFIG")

    # Refuse to run against a real config, the same way the update suite does.
    if not sandbox:
        FAILURES.append("[diagnostics] BLENDER_USER_CONFIG is not sandboxed --"
                        " refusing to write a report into the real config dir")
    else:
        bpy.ops.preferences.addon_enable(module=ADDON)
        silence_auto_check()

        diagnostics = sys.modules.get(ADDON + ".core.diagnostics")
        if check(diagnostics is not None,
                 "[diagnostics] core.diagnostics not in sys.modules"):

            probe = os.path.realpath(diagnostics.report_path())
            check(probe.startswith(config_root),
                  "[diagnostics] report path " + probe + " is OUTSIDE the "
                  "config dir " + config_root)

            # Snapshot the sandbox so we can prove exactly one file appeared.
            def snapshot(root):
                found = {}
                for base, _dirs, files in os.walk(root):
                    for name in files:
                        full = os.path.join(base, name)
                        try:
                            found[full] = os.path.getmtime(full)
                        except OSError:
                            pass
                return found

            sandbox_root = os.path.realpath(os.path.join(sandbox, ".."))
            before = snapshot(sandbox_root)
            blend_dirty_before = bpy.data.is_dirty
            scene_name_before = bpy.context.scene.name

            result = bpy.ops.lightgroup.write_diagnostics()
            check(result == {'FINISHED'},
                  "[diagnostics] operator returned " + repr(result))

            after = snapshot(sandbox_root)
            created = sorted(set(after) - set(before))
            changed = sorted(p for p in set(after) & set(before)
                             if after[p] != before[p])
            removed = sorted(set(before) - set(after))

            # Exactly one new file, it is a report, and it sits in the
            # config dir.
            check(len(created) == 1,
                  "[diagnostics] expected exactly 1 new file, got "
                  + str(len(created)) + ": " + ", ".join(created))
            target = os.path.realpath(created[0]) if created else None
            if target:
                check(target.startswith(config_root),
                      "[diagnostics] wrote OUTSIDE the config dir: " + target)
                check(os.path.basename(target).startswith(
                          diagnostics.REPORT_PREFIX),
                      "[diagnostics] unexpected filename: " + target)

            # Nothing may be modified or removed. The addon must not tidy up
            # after itself on someone's machine mid-season.
            check(not changed,
                  "[diagnostics] modified existing file(s): "
                  + ", ".join(changed))
            check(not removed,
                  "[diagnostics] DELETED file(s): " + ", ".join(removed))

            # It must not dirty the artist's open file.
            check(bpy.data.is_dirty == blend_dirty_before,
                  "[diagnostics] running the report marked the .blend dirty")
            check(bpy.context.scene.name == scene_name_before,
                  "[diagnostics] running the report renamed the scene")

            # The report has to actually say something useful.
            with open(target, "r", encoding="utf-8") as fh:
                body = fh.read()
            for expected in ("Lightgroup Tools", "BLENDER", "REGISTRATION",
                             "SCENE", "end of report"):
                check(expected in body,
                      "[diagnostics] report is missing the '" + expected
                      + "' section")
            check("CAMERA OVERLAY" in body,
                  "[diagnostics] the Camera Overlay section did not register")

            # A second run must KEEP the first report. Reports are a couple of
            # kilobytes; replacing one to save space would mean the addon
            # deleting a file on a user's machine, which is not a trade worth
            # making. Two runs, two files, nothing removed.
            bpy.ops.lightgroup.write_diagnostics()
            after_twice = snapshot(sandbox_root)
            check(target is None or os.path.exists(target),
                  "[diagnostics] the second run destroyed the first report")
            still_removed = sorted(set(after) - set(after_twice))
            check(not still_removed,
                  "[diagnostics] a second run DELETED file(s): "
                  + ", ".join(still_removed))

            print("    one new file per run, inside the config dir, "
                  "nothing deleted, .blend untouched")

        # And statically: the diagnostics and camera overlay code must not
        # contain a delete call at all. The updater legitimately removes its
        # own staging and backup dirs, so it is exempt -- these are not.
        import ast

        destructive = {"remove", "unlink", "rmtree", "rmdir", "removedirs"}
        package_dir = os.path.dirname(sys.modules[ADDON].__file__)
        for relative in (os.path.join("core", "diagnostics.py"),
                         os.path.join("camera_overlay", "overlay.py"),
                         os.path.join("camera_overlay", "props.py"),
                         os.path.join("camera_overlay", "panels.py"),
                         os.path.join("camera_overlay", "__init__.py")):
            full = os.path.join(package_dir, relative)
            if not os.path.exists(full):
                continue
            with open(full, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else getattr(func, "id", None))
                # bpy.app.handlers.load_post.remove() is a list operation, not
                # a filesystem one -- only flag os/shutil style calls.
                if name in destructive and isinstance(func, ast.Attribute):
                    root = func.value
                    root_name = (root.attr if isinstance(root, ast.Attribute)
                                 else getattr(root, "id", ""))
                    if root_name in ("os", "path", "shutil"):
                        FAILURES.append(
                            "[diagnostics] " + relative + " line "
                            + str(node.lineno) + " calls " + root_name + "."
                            + name + " -- this code must never delete files")
        print("    no filesystem delete calls in the new code")
        bpy.ops.preferences.addon_disable(module=ADDON)
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[diagnostics] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 8: the Lightgroups tab must draw in every update state ---------
#
# This is the tab the team uses on every job, and its draw path branches on
# preference state that is FALSE on every machine right now. The
# `update_available` branch only comes alive the moment a release is
# published -- so a mistake in it would be invisible in testing and would
# break everyone's panel simultaneously, mid-season, the instant they check
# for updates. Drive every branch deliberately.

print("=== phase 8: Lightgroups panel draws in every update state ===")

try:
    bpy.ops.preferences.addon_enable(module=ADDON)
    silence_auto_check()
    panels = sys.modules[ADDON + ".lightgroups.panels"]
    prefs = bpy.context.preferences.addons[ADDON].preferences

    class FakeLayout:
        """Records what the real draw code emits, without a UI."""

        def __init__(self, sink):
            self.sink = sink
            self.alert = False
            self.enabled = True
            self.scale_y = 1.0

        def label(self, text="", icon=''):
            self.sink.append(("label", text))

        def operator(self, idname, **kwargs):
            self.sink.append(("operator", idname))
            return self

        def box(self):
            return FakeLayout(self.sink)

        def column(self, align=False):
            return FakeLayout(self.sink)

        def row(self, align=False):
            return FakeLayout(self.sink)

        def separator(self):
            pass

        def prop(self, *args, **kwargs):
            self.sink.append(("prop", args[1] if len(args) > 1 else "?"))

    # Every button the team relies on, in every state below.
    ESSENTIAL = ("lightgroup.clear_all_lightgroups",
                 "lightgroup.create_for_each_light",
                 "lightgroup.assign_to_lightgroup",
                 "lightgroup.denoise_all_cycles",
                 "lightgroup.check_updates")

    STATES = (
        ("clean install", dict(update_available=False, update_downloaded=False,
                               backup_available=False,
                               update_just_installed=False)),
        # What every machine looks like the moment we publish.
        ("update available", dict(update_available=True, latest_version="1.0.18",
                                  latest_notes="Camera Overlay tab. "
                                               "Diagnostics button.",
                                  latest_is_prerelease=True)),
        ("update available, stable", dict(update_available=True,
                                          latest_is_prerelease=False)),
        ("update available, empty notes", dict(update_available=True,
                                               latest_notes="")),
        ("downloaded, awaiting restart", dict(update_available=False,
                                              update_downloaded=True)),
        ("backup present", dict(update_downloaded=False, backup_available=True,
                                backup_version="1.0.17")),
        ("just installed banner", dict(update_just_installed=True,
                                       last_installed_version="1.0.18")),
    )

    for label, state in STATES:
        for field, value in state.items():
            setattr(prefs, field, value)
        sink = []
        try:
            panels._draw_tools(FakeLayout(sink), bpy.context)
        except Exception as exc:
            FAILURES.append("[panel] Lightgroups tab RAISED while drawing in "
                            "state '" + label + "': " + type(exc).__name__
                            + ": " + str(exc))
            continue

        drawn = [name for kind, name in sink if kind == "operator"]
        for idname in ESSENTIAL:
            check(idname in drawn,
                  "[panel] '" + idname + "' missing from the Lightgroups tab "
                  "in state '" + label + "'")

        # A typo'd idname draws a red box in Blender rather than raising, so
        # every button the panel references has to resolve for real.
        for idname in set(drawn):
            category, _, name = idname.partition(".")
            try:
                getattr(getattr(bpy.ops, category), name).get_rna_type()
            except Exception:
                FAILURES.append("[panel] Lightgroups tab draws a button for '"
                                + idname + "' but that operator is not "
                                "registered (state '" + label + "')")

    # Reset so nothing leaks into a later phase or the user's prefs.
    for field in ("update_available", "update_downloaded", "backup_available",
                  "update_just_installed", "latest_is_prerelease"):
        setattr(prefs, field, False)
    for field in ("latest_version", "latest_notes", "backup_version",
                  "last_installed_version"):
        setattr(prefs, field, "")

    print("    drew cleanly in " + str(len(STATES)) + " update states")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[panel] raised " + type(exc).__name__ + ": " + str(exc))


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
      + str(len(EXPECTED_PREF_PROPS)) + " prefs verified across 8 phases")
print("=" * 60)
