bl_info = {
    "name": "Lightgroup Tools",
    "author": "David Carney",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Lightgroups",
    "description": "Tools for managing lightgroups and compositor setup",
    "category": "Lighting",
}

import bpy

# --- Package layout ---------------------------------------------------------
#
#   core/            shared infrastructure (diagnostics)
#   lightgroups/     the Lightgroups tab
#   camera_overlay/  the Camera Overlay tab
#
# Each subpackage owns a `classes` tuple; this module just aggregates and
# registers them. A new tool means a new subpackage and two lines here -- it
# does NOT mean touching the existing tools.
#
# --- Reload guard -----------------------------------------------------------
#
# If this module's globals already hold the subpackages, we're being re-executed
# over a live addon -- e.g. Blender's "Install from Disk" onto an already-enabled
# older version. A plain import would hand back the STALE modules from
# sys.modules, and register() would then fail on any class newer than the
# previously installed build (this bit a tester on v1.0.14 with
# "module 'lightgroup_tools.updater' has no attribute
# LIGHTGROUP_OT_restore_backup").
#
# Order is load-bearing: LEAF MODULES FIRST, THEN THEIR PACKAGES. Each package's
# `classes` tuple is built at import time from its submodules, so reloading a
# package before its submodules would rebuild that tuple out of stale classes --
# the exact bug the guard exists to prevent, just moved one level up.
#
# importlib.reload mutates modules in place and returns the same object, so
# every existing reference (including `core.diagnostics`, and the package attributes
# themselves) sees the new code once this block has run.
if "core" in locals():
    import importlib

    importlib.reload(core.diagnostics)
    importlib.reload(lightgroups.operators)
    importlib.reload(lightgroups.solo)
    importlib.reload(lightgroups.output_check)
    importlib.reload(lightgroups.panels)
    # camera_overlay: overlay is the leaf (it owns the GPU state); props and
    # panels both import it.
    importlib.reload(camera_overlay.overlay)
    importlib.reload(camera_overlay.props)
    importlib.reload(camera_overlay.operators)
    importlib.reload(camera_overlay.panels)
    importlib.reload(core)
    importlib.reload(lightgroups)
    importlib.reload(camera_overlay)
else:
    from . import core
    from . import lightgroups
    from . import camera_overlay


# Registration order across the toolkit: core first, panels last.
classes = core.classes + lightgroups.classes + camera_overlay.classes


def _guarded(action, tool_name, func):
    """Run a building tool's setup so a failure cannot take the addon down.

    Blender aborts addon_enable on the first exception out of register().
    Verified consequence: the addon is left marked DISABLED while its classes
    stay registered -- so Lightgroups half-works for the rest of the session
    and is simply gone after the next restart, preferences orphaned.

    Lightgroups is the tool this team uses on every job; Camera Overlay is a
    building aid that touches the GPU, which is where driver- and
    platform-specific failures live. A broken building tool must not cost
    anyone their lightpass workflow mid-job, so it is isolated. core/ and lightgroups/ are deliberately NOT guarded: if they
    fail, the addon really is broken and should say so loudly.

    The failure is printed in full, never swallowed -- a silent degradation
    would be its own bug.
    """
    try:
        func()
        return True
    except Exception:
        import traceback

        print("[lightgroup_tools] %s failed to %s -- it will be unavailable, "
              "but the rest of the toolkit is unaffected:" % (tool_name, action))
        traceback.print_exc()
        return False


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    lightgroups.register_properties()
    # After the classes: these register scene PointerProperties that
    # reference their own PropertyGroups, which have to be registered types
    # by the time the pointer is created.
    _guarded("register", "Camera Overlay", camera_overlay.register)


def unregister():
    # Guarded for the same reason, and because a tool whose register() failed
    # part way may well fail to tear down cleanly too. Leaking one tool's
    # handler must not stop the classes below from unregistering.
    _guarded("unregister", "Camera Overlay", camera_overlay.unregister)
    lightgroups.unregister_properties()
    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
