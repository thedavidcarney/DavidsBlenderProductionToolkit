bl_info = {
    "name": "Lightgroup Tools",
    "author": "David Carney",
    "version": (1, 0, 18),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Lightgroups",
    "description": "Tools for managing lightgroups and compositor setup",
    "category": "Lighting",
}

import bpy

# --- Package layout ---------------------------------------------------------
#
#   core/            shared infrastructure (updater, preferences)
#   lightgroups/     the Lightgroups tab
#   festoon/         the Festoon Clicker tab
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
# every existing reference (including `core.updater`, and the package attributes
# themselves) sees the new code once this block has run.
if "core" in locals():
    import importlib

    importlib.reload(core.tags)
    importlib.reload(core.diagnostics)
    importlib.reload(core.updater)
    importlib.reload(lightgroups.operators)
    importlib.reload(lightgroups.panels)
    # festoon's own submodules import each other, so they reload innermost
    # first: picking and shape are leaves, nodes feeds rig, rig feeds operators.
    importlib.reload(festoon.picking)
    importlib.reload(festoon.shape)
    importlib.reload(festoon.overlay)
    importlib.reload(festoon.nodes)
    importlib.reload(festoon.rig)
    importlib.reload(festoon.operators)
    importlib.reload(festoon.panels)
    # camera_overlay: overlay is the leaf (it owns the GPU state); props and
    # panels both import it.
    importlib.reload(camera_overlay.overlay)
    importlib.reload(camera_overlay.props)
    importlib.reload(camera_overlay.panels)
    importlib.reload(core)
    importlib.reload(lightgroups)
    importlib.reload(festoon)
    importlib.reload(camera_overlay)
else:
    from . import core
    from . import lightgroups
    from . import festoon
    from . import camera_overlay


# Registration order across the toolkit. Preferences land first (via core), and
# panels last, matching what shipped in v1.0.15.
classes = (core.classes + lightgroups.classes + festoon.classes
           + camera_overlay.classes)


def _guarded(action, tool_name, func):
    """Run a building tool's setup so a failure cannot take the addon down.

    Blender aborts addon_enable on the first exception out of register().
    Verified consequence: the addon is left marked DISABLED while its classes
    stay registered -- so Lightgroups half-works for the rest of the session
    and is simply gone after the next restart, preferences orphaned.

    Lightgroups is the tool this team uses on every job; Festoon and Camera
    Overlay are building aids that touch the GPU and the depsgraph, which is
    where driver- and platform-specific failures live. A broken building tool
    must not cost anyone their lightpass workflow mid-job, so those two are
    isolated. core/ and lightgroups/ are deliberately NOT guarded: if they
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
    core.updater.register_handlers()
    for cls in classes:
        bpy.utils.register_class(cls)
    # After the classes: these register scene PointerProperties that
    # reference their own PropertyGroups, which have to be registered types
    # by the time the pointer is created.
    _guarded("register", "Festoon Clicker", festoon.register)
    _guarded("register", "Camera Overlay", camera_overlay.register)


def unregister():
    # Guarded for the same reason, and because a tool whose register() failed
    # part way may well fail to tear down cleanly too. Leaking one tool's
    # handler must not stop the classes below from unregistering.
    _guarded("unregister", "Camera Overlay", camera_overlay.unregister)
    _guarded("unregister", "Festoon Clicker", festoon.unregister)
    for cls in classes:
        bpy.utils.unregister_class(cls)
    core.updater.unregister_handlers()


if __name__ == "__main__":
    register()
