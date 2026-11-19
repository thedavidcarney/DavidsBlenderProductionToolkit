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
                          (what the old self-updater did; still the cleanest
                          way to prove nothing hides in a stale module)
  3. re-exec over live -- importlib.reload of the top module, then
                          register() again (what Blender's Install from Disk
                          does, and the reason the reload guard exists)
  4. teardown          -- clean unregister, no leaked handler
  5. import hygiene    -- static scan for relative imports hidden inside
                          function bodies, which move silently and only fail
                          when a user clicks the button that runs them
  6. isolation         -- a building tool that fails to register must not
                          take Lightgroups down with it
  7. diagnostics       -- the support button writes exactly one file, inside
                          the config dir, and never dirties the open .blend
  8. panel draw        -- the Lightgroups tab draws, every button resolves
  9. no updater        -- since v1.1.0 IFTK installs and updates the addon,
                          so nothing in it may touch the network, start a
                          thread, or register an update handler

After phases 1-3, every class, operator, panel and preference property that
shipped in the production-tested v1.0.15 build must still resolve.

The EXPECTED_* lists below are the contract. If a restructure legitimately
renames something, edit the list deliberately -- don't let it drift quietly.

Network safety: nothing left in the addon can reach the network, and phase 9
keeps it that way.
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
    "lightgroup.write_diagnostics",
    "camoverlay.match_resolution",
    "lightgroup.solo_light",
)

# NB: CameraOverlaySettings is deliberately absent from this list: a
# PropertyGroup doesn't appear in bpy.types under its class name, it is reached
# through the ID property it is attached to. It is verified functionally in
# assert_fully_registered() instead.
EXPECTED_CLASSES = (
    "LIGHTGROUP_OT_clear_all_lightgroups",
    "LIGHTGROUP_OT_create_for_each_light",
    "LIGHTGROUP_OT_denoise_all_cycles",
    "LIGHTGROUP_OT_assign_to_lightgroup",
    "LIGHTGROUP_PT_main_panel",
    "LIGHTGROUP_PT_compositor_panel",
    "LIGHTGROUP_PT_viewlayer_panel",
    "LIGHTGROUP_OT_write_diagnostics",
    "CAMOVERLAY_PT_main_panel",
    "CAMOVERLAY_PT_display_panel",
    "CAMOVERLAY_PT_transform_panel",
    "CAMOVERLAY_PT_support_panel",
    "CAMOVERLAY_OT_match_resolution",
    "LIGHTGROUP_OT_solo_light",
)

# Panel placement is part of the contract too: the restructure must NOT move
# the lightgroup panels out of the 'Lightgroups' tab. Other tools get their own.
# The properties-editor panel has no tab, hence None.
EXPECTED_PANELS = {
    "LIGHTGROUP_PT_main_panel": ("VIEW_3D", "Lightgroups"),
    "LIGHTGROUP_PT_compositor_panel": ("NODE_EDITOR", "Lightgroups"),
    "LIGHTGROUP_PT_viewlayer_panel": ("PROPERTIES", None),
    # Camera Overlay is deliberately a SEPARATE tab. If these ever read
    # 'Lightgroups', an unrelated building tool has leaked into the panel the
    # team uses on every job.
    "CAMOVERLAY_PT_main_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_display_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_transform_panel": ("VIEW_3D", "Camera Overlay"),
    "CAMOVERLAY_PT_support_panel": ("VIEW_3D", "Camera Overlay"),
}

# Operators the self-updater registered up to v1.0.21. None may come back.
REMOVED_OPERATORS = (
    "lightgroup.check_updates",
    "lightgroup.download_update",
    "lightgroup.restore_backup",
    "lightgroup.dismiss_install_notice",
    "lightgroup.update_dialog",
    "lightgroup.restart_dialog",
    "lightgroup.close_dialog",
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


def addon_handlers():
    """Every app handler owned by the addon, as (list name, dotted function)."""
    found = []
    for list_name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, list_name)
        if not isinstance(handlers, list):
            continue
        for h in handlers:
            module = getattr(h, "__module__", "") or ""
            if module == ADDON or module.startswith(ADDON + "."):
                found.append((list_name, module + "." + getattr(h, "__name__", "?")))
    return found


# The only handlers the addon may own: Solo Light, the output check and Camera
# Overlay's load_post. An update handler (install-on-load, auto-check) must not
# come back.
ALLOWED_HANDLER_MODULES = (ADDON + ".lightgroups.solo",
                           ADDON + ".lightgroups.output_check",
                           ADDON + ".camera_overlay")


SOLO_HANDLER_LISTS = ("depsgraph_update_post", "render_pre", "render_post",
                      "render_cancel", "save_pre", "save_post")


def solo_handler_count(handler_list):
    return sum(1 for h in getattr(bpy.app.handlers, handler_list)
               if getattr(h, "__module__", "").endswith("lightgroups.solo"))


OUTPUT_CHECK_HANDLER_LISTS = ("render_init", "render_pre", "render_post")


def output_check_handler_count(handler_list):
    return sum(1 for h in getattr(bpy.app.handlers, handler_list)
               if getattr(h, "__module__", "").endswith("lightgroups.output_check"))


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

    check(bpy.context.preferences.addons.get(ADDON) is not None,
          "[" + phase + "] addon '" + ADDON + "' not in context.preferences.addons")

    # No updater: its operators are gone, and no handler outside the known
    # tools is registered.
    for idname in REMOVED_OPERATORS:
        category, _, name = idname.partition(".")
        try:
            getattr(getattr(bpy.ops, category), name).get_rna_type()
            FAILURES.append("[" + phase + "] updater operator " + idname
                            + " is registered again")
        except (KeyError, RuntimeError, AttributeError):
            pass
    for list_name, func in addon_handlers():
        check(func.rpartition(".")[0] in ALLOWED_HANDLER_MODULES,
              "[" + phase + "] unexpected " + list_name + " handler " + func
              + " -- the addon must not install update handlers")

    scene = getattr(bpy.context, "scene", None)

    # Solo Light's scene state. It lives in lightgroups/, so unlike the two
    # building tools it is NOT behind _guarded() -- a failure here is loud.
    check(hasattr(bpy.types.Scene, "lightgroup_solo"),
          "[" + phase + "] Scene.lightgroup_solo not registered")
    if scene is not None:
        solo_settings = getattr(scene, "lightgroup_solo", None)
        if check(solo_settings is not None,
                 "[" + phase + "] scene.lightgroup_solo does not resolve"):
            for field in ("active", "view_layer", "soloed", "muted", "spaces"):
                check(hasattr(solo_settings, field),
                      "[" + phase + "] lightgroup_solo setting '" + field
                      + "' missing")
    # Solo's handlers mute lights live and put them back for renders and
    # saves. Exactly one each: zero means a soloed file could save muted
    # lights, two means a reload left a stale copy running beside the new one.
    for handler_list in SOLO_HANDLER_LISTS:
        count = solo_handler_count(handler_list)
        check(count == 1, "[" + phase + "] " + str(count) + " Solo Light "
              + handler_list + " handlers registered, expected exactly 1")
    for handler_list in OUTPUT_CHECK_HANDLER_LISTS:
        count = output_check_handler_count(handler_list)
        check(count == 1, "[" + phase + "] " + str(count) + " output check "
              + handler_list + " handlers registered, expected exactly 1")

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
    assert_fully_registered("cold enable")
except Exception as exc:  # noqa: BLE001 - a raise here IS the test result
    FAILURES.append("[cold enable] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 2: in-session reload (sys.modules eviction) ---------------------

print("=== phase 2: in-session reload (sys.modules eviction) ===")
try:
    bpy.ops.preferences.addon_disable(module=ADDON)

    evicted = [m for m in sys.modules if m == ADDON or m.startswith(ADDON + ".")]
    for module_name in evicted:
        del sys.modules[module_name]
    print("    evicted " + str(len(evicted)) + " module(s): " + str(sorted(evicted)))

    bpy.ops.preferences.addon_refresh()
    bpy.ops.preferences.addon_enable(module=ADDON)
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
    assert_fully_registered("reload guard")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[reload guard] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 4: clean teardown ------------------------------------------------

print("=== phase 4: clean unregister ===")
try:
    bpy.ops.preferences.addon_disable(module=ADDON)
    check(not addon_handlers(),
          "[teardown] handler(s) survived addon_disable: "
          + str(addon_handlers()))
    for cls_name in EXPECTED_CLASSES:
        check(not hasattr(bpy.types, cls_name),
              "[teardown] bpy.types." + cls_name + " still registered after disable")
    check(bpy.context.preferences.addons.get(ADDON) is None,
          "[teardown] addon still present in context.preferences.addons after disable")
    check(not hasattr(bpy.types.Scene, "cam_overlay"),
          "[teardown] Scene.cam_overlay leaked past unregister")
    check(not hasattr(bpy.types.Scene, "lightgroup_solo"),
          "[teardown] Scene.lightgroup_solo leaked past unregister")
    for handler_list in SOLO_HANDLER_LISTS:
        check(solo_handler_count(handler_list) == 0,
              "[teardown] Solo Light " + handler_list
              + " handler survived addon_disable")
    for handler_list in OUTPUT_CHECK_HANDLER_LISTS:
        check(output_check_handler_count(handler_list) == 0,
              "[teardown] output check " + handler_list
              + " handler survived addon_disable")

    # A leaked draw handler keeps drawing against unregistered properties,
    # which is a crash rather than a cosmetic bug. The overlay module also
    # owns its own load_post handler.
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
# operator's execute(). Moving its module into core/ silently repointed it at
# the wrong package, and because it only ran when a user clicked the button,
# nothing above would have caught it -- import succeeds, registration
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
# Lightgroups is used on every job. Camera Overlay is a building aid that
# touches the GPU, where platform- and driver-specific failures live. So it is
# isolated, and this asserts
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
    for tool_name in ("camera_overlay",):
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
# config directory. It must not
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
        # contain a delete call at all.
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


# --- Phase 8: the Lightgroups tab must draw ---------------------------------
#
# The tab the team uses on every job. Draw it through the real code with a
# recording layout, and check every button it references resolves -- a typo'd
# idname draws a red box in Blender rather than raising.

print("=== phase 8: Lightgroups panel draws ===")

try:
    bpy.ops.preferences.addon_enable(module=ADDON)
    panels = sys.modules[ADDON + ".lightgroups.panels"]

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

    ESSENTIAL = ("lightgroup.clear_all_lightgroups",
                 "lightgroup.create_for_each_light",
                 "lightgroup.assign_to_lightgroup",
                 "lightgroup.denoise_all_cycles",
                 "lightgroup.write_diagnostics")

    sink = []
    panels._draw_tools(FakeLayout(sink), bpy.context)
    drawn = [name for kind, name in sink if kind == "operator"]
    for idname in ESSENTIAL:
        check(idname in drawn,
              "[panel] '" + idname + "' missing from the Lightgroups tab")
    for idname in set(drawn):
        category, _, name = idname.partition(".")
        try:
            getattr(getattr(bpy.ops, category), name).get_rna_type()
        except Exception:
            FAILURES.append("[panel] Lightgroups tab draws a button for '"
                            + idname + "' but that operator is not registered")
    for kind, text in sink:
        check(kind != "label" or "update" not in text.lower(),
              "[panel] the Lightgroups tab still talks about updates: "
              + repr(text))
    print("    drew cleanly, " + str(len(set(drawn))) + " buttons resolve")
    bpy.ops.preferences.addon_disable(module=ADDON)
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[panel] raised " + type(exc).__name__ + ": " + str(exc))


# --- Phase 9: no updater, statically ----------------------------------------
#
# From v1.1.0 IFTK installs and updates the addon. The addon itself must make
# no network calls, start no threads, and write no staging or backup folders.
# Checked on the source by AST, so comments explaining the rule don't trip it.

print("=== phase 9: no network, threads or update folders in the source ===")

try:
    import ast

    FORBIDDEN_IMPORTS = {"urllib", "http", "socket", "ssl", "requests",
                         "threading", "_thread", "concurrent", "asyncio",
                         "subprocess"}
    FORBIDDEN_STRINGS = ("api.github.com", "zipball", "lightgroup_tools_update",
                         "lightgroup_tools_backup", "releases/latest")
    package_root = os.path.dirname(sys.modules[ADDON].__file__)
    scanned = 0
    for dirpath, _dirnames, filenames in os.walk(package_root):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            relative = os.path.relpath(path, package_root)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            scanned += 1
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    check(name.partition(".")[0] not in FORBIDDEN_IMPORTS,
                          "[no updater] " + relative + ":" + str(node.lineno)
                          + " imports " + name)
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for needle in FORBIDDEN_STRINGS:
                        check(needle not in node.value,
                              "[no updater] " + relative + ":"
                              + str(node.lineno) + " mentions " + repr(needle))
    print("    scanned " + str(scanned) + " module(s)")
except Exception as exc:  # noqa: BLE001
    FAILURES.append("[no updater] raised " + type(exc).__name__ + ": " + str(exc))


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
      + str(len(EXPECTED_OPERATORS)) + ""
      + " operators verified across 9 phases")
print("=" * 60)
