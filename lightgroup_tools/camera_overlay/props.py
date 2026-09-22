"""Scene properties for the camera overlay.

The one decision that matters is at the top: `image` is a PointerProperty to
an Image datablock, not a file path string. That single choice deletes a whole
bug class -- relative paths (`//ref/shot.png`), packed images, reloads, and
formats nobody thought to allow-list. Blender already solves all of it, and
`template_ID` gives us the standard Open / unlink / pack widget for free.

Every property's update callback is just a redraw. There is no cache
invalidation logic here on purpose: the texture cache in overlay.py keys on
the image itself, so nothing in this file can leave it stale.
"""

import bpy

from . import overlay


def _redraw(self, context):
    """Tag every 3D view, not just the active one.

    The overlay can be visible in several viewports at once, and a property
    edited in the sidebar of one should update all of them.
    """
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _toggle(self, context):
    """`enabled` owns the draw handler's lifetime.

    Adding and removing rather than leaving a handler installed and returning
    early means a disabled overlay costs exactly nothing per redraw.
    `enable_handler` is idempotent, so toggling cannot stack handlers.
    """
    if self.enabled:
        overlay.enable_handler()
    else:
        overlay.sync_handler()
    _redraw(self, context)


class CameraOverlaySettings(bpy.types.PropertyGroup):
    """Per-scene overlay state, reached as `scene.cam_overlay`."""

    image: bpy.props.PointerProperty(
        name="Image", type=bpy.types.Image, update=_redraw,
        description="Reference image drawn over the camera frame. "
                    "Uses the image datablock, so relative paths and packed "
                    "images resolve correctly on any machine")
    enabled: bpy.props.BoolProperty(
        name="Enable", default=False, update=_toggle,
        description="Draw the reference over the camera frame")
    opacity: bpy.props.FloatProperty(
        name="Opacity", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=_redraw)

    mode: bpy.props.EnumProperty(
        name="Mode", update=_redraw,
        items=(('NORMAL', "Normal", "Draw the image as-is"),
               ('MASK', "Mask", "Threshold one channel and tint the result")),
        default='NORMAL')
    channel: bpy.props.EnumProperty(
        name="Channel", update=_redraw,
        items=(('LUMINANCE', "Luminance", "Perceptual brightness"),
               ('R', "Red", "Red channel"),
               ('G', "Green", "Green channel"),
               ('B', "Blue", "Blue channel"),
               ('ALPHA', "Alpha", "Alpha channel")),
        default='LUMINANCE',
        description="Which channel the threshold reads")
    threshold: bpy.props.FloatProperty(
        name="Threshold", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        update=_redraw)
    invert: bpy.props.BoolProperty(
        name="Invert", default=False, update=_redraw,
        description="Show what falls below the threshold instead of above it")
    tint: bpy.props.FloatVectorProperty(
        name="Tint", subtype='COLOR', size=3, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0), update=_redraw,
        description="Colour applied to the masked result")

    fit: bpy.props.EnumProperty(
        name="Fit", update=_redraw,
        items=(('FIT', "Fit", "Whole image inside the frame, letterboxed"),
               ('FILL', "Fill", "Cover the frame, cropping the overflow"),
               ('STRETCH', "Stretch", "Distort to match the frame exactly")),
        default='FIT')
    scale: bpy.props.FloatProperty(
        name="Scale", default=1.0, min=0.1, max=5.0, update=_redraw)
    offset_x: bpy.props.FloatProperty(
        name="Offset X", default=0.0, min=-2.0, max=2.0, update=_redraw,
        description="Horizontal shift, as a fraction of the camera frame")
    offset_y: bpy.props.FloatProperty(
        name="Offset Y", default=0.0, min=-2.0, max=2.0, update=_redraw,
        description="Vertical shift, as a fraction of the camera frame")
    rotation: bpy.props.FloatProperty(
        name="Rotation", default=0.0, subtype='ANGLE', unit='ROTATION',
        update=_redraw,
        description="Rotation about the centre of the image")
    flip_x: bpy.props.BoolProperty(
        name="Flip X", default=False, update=_redraw)
    flip_y: bpy.props.BoolProperty(
        name="Flip Y", default=False, update=_redraw)


classes = (
    CameraOverlaySettings,
)


def register_properties():
    bpy.types.Scene.cam_overlay = bpy.props.PointerProperty(
        type=CameraOverlaySettings)


def unregister_properties():
    if hasattr(bpy.types.Scene, "cam_overlay"):
        del bpy.types.Scene.cam_overlay
