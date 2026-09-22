"""Camera Overlay: a reference image over the camera frame.

Its own sidebar tab ('Camera Overlay'). Viewport only -- it is a working aid
for matching a shot, and never appears in a render.

Module map:
    overlay.py    shader, texture cache, draw handler, status string
    props.py      the scene PropertyGroup
    panels.py     sidebar UI

Diagnostics live in core/ and cover the whole toolkit; this package just
contributes its own section to that report.

`classes` is built at import time, so the addon's reload guard must reload
these submodules BEFORE reloading this package.
"""

import bpy

from . import overlay
from . import props
from . import panels
from ..core import diagnostics

classes = props.classes + panels.classes


@bpy.app.handlers.persistent
def _on_load(_dummy):
    """Reset GPU state that must not survive a file load.

    A GPUTexture held across a file load is a crash risk, so the cache is
    dropped. The handler is then re-synced because `enabled` is saved in the
    .blend: the file being opened decides whether the overlay should be on,
    not whatever the previous file left behind.
    """
    overlay.clear_cache()
    overlay.clear_status()
    overlay.sync_handler()


def _deferred_sync():
    """One-shot timer callback: pick up the open file's `enabled` state.

    register() runs while `bpy.data` is still restricted -- it has no
    `scenes` attribute at all, and touching it there aborts the whole addon's
    registration. By the time a timer fires, the data is real.
    """
    overlay.sync_handler()
    return None


def register():
    props.register_properties()
    diagnostics.register_section("Camera Overlay", overlay.report_section)

    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)

    # A .blend already open when the addon is enabled may want the overlay on,
    # but we cannot look until Blender lets go of bpy.data -- hence the timer.
    try:
        bpy.app.timers.register(_deferred_sync, first_interval=0.0)
    except Exception:
        # Headless runs may refuse timers. The overlay simply stays off until
        # the user toggles it or a file is loaded, which is not a failure.
        pass


def unregister():
    # Teardown has to be complete enough to survive repeated reloads: a
    # leaked draw handler would keep drawing against unregistered properties.
    if bpy.app.timers.is_registered(_deferred_sync):
        bpy.app.timers.unregister(_deferred_sync)

    diagnostics.unregister_section("Camera Overlay")
    overlay.shutdown()

    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)

    props.unregister_properties()
