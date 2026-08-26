bl_info = {
    "name": "Lightgroup Tools",
    "author": "David Carney",
    "version": (1, 0, 16),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Lightgroups",
    "description": "Tools for managing lightgroups and compositor setup",
    "category": "Lighting",
}

import bpy

# --- Package layout ---------------------------------------------------------
#
#   core/         shared infrastructure (updater, preferences)
#   lightgroups/  the Lightgroups tab
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

    importlib.reload(core.updater)
    importlib.reload(lightgroups.operators)
    importlib.reload(lightgroups.panels)
    importlib.reload(core)
    importlib.reload(lightgroups)
else:
    from . import core
    from . import lightgroups


# Registration order across the toolkit. Preferences land first (via core), and
# panels last, matching what shipped in v1.0.15.
classes = core.classes + lightgroups.classes


def register():
    core.updater.register_handlers()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    core.updater.unregister_handlers()


if __name__ == "__main__":
    register()
