"""Camera Overlay sidebar panel.

Its own tab, per the toolkit's rule that unrelated tools do not share a panel.

Layout follows actual use rather than the feature list: loading an image and
pulling the opacity slider is the whole daily workflow, so that is the entire
main panel. Mask mode and the transform controls are real but rarely touched,
so they live in sub-panels that start collapsed -- present when wanted,
invisible when not.
"""

import bpy

from . import overlay


def _draw_status(layout):
    """Show the failure reason, if there is one.

    The point of the whole module. An overlay that silently does nothing is
    unreportable; one that says why is a five-minute fix.
    """
    status = overlay.get_status()
    if not status:
        return
    box = layout.box()
    box.alert = True
    box.label(text=status, icon='ERROR')


class CAMOVERLAY_PT_main_panel(bpy.types.Panel):
    bl_label = "Camera Overlay"
    bl_idname = "CAMOVERLAY_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Overlay'

    @classmethod
    def poll(cls, context):
        return context.space_data is not None and \
            context.space_data.type == 'VIEW_3D'

    def draw(self, context):
        layout = self.layout
        props = context.scene.cam_overlay

        layout.prop(props, "enabled", toggle=False)

        # template_ID is the standard datablock widget: Open, unlink, pack,
        # and the browse dropdown -- all for free, because `image` is a real
        # Image pointer rather than a path string.
        layout.template_ID(props, "image", open="image.open")

        body = layout.column()
        body.enabled = props.image is not None
        body.prop(props, "opacity", slider=True)

        if props.image is None:
            layout.label(text="Load an image to begin", icon='INFO')
        elif not props.enabled:
            layout.label(text="Overlay is off", icon='HIDE_ON')
        else:
            # Worth saying plainly: people expect an overlay to be a render
            # feature, and then wonder why it is missing from the EXR.
            layout.label(text="Viewport only, in camera view", icon='INFO')

        _draw_status(layout)


class CAMOVERLAY_PT_display_panel(bpy.types.Panel):
    """Mask mode. Collapsed by default -- Normal is what gets used."""

    bl_label = "Display Mode"
    bl_idname = "CAMOVERLAY_PT_display_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Overlay'
    bl_parent_id = "CAMOVERLAY_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.cam_overlay
        layout.enabled = props.image is not None

        layout.prop(props, "mode", expand=True)

        if props.mode == 'MASK':
            column = layout.column(align=True)
            column.prop(props, "channel")
            column.prop(props, "threshold", slider=True)
            column.prop(props, "invert")
            column.prop(props, "tint")


class CAMOVERLAY_PT_transform_panel(bpy.types.Panel):
    """Fit, scale, offset, rotation, flip. Set once, then left alone."""

    bl_label = "Transform"
    bl_idname = "CAMOVERLAY_PT_transform_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Overlay'
    bl_parent_id = "CAMOVERLAY_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.cam_overlay
        layout.enabled = props.image is not None

        layout.prop(props, "fit", expand=True)

        column = layout.column(align=True)
        column.prop(props, "scale")
        column.prop(props, "offset_x")
        column.prop(props, "offset_y")
        column.prop(props, "rotation")

        row = layout.row(align=True)
        row.prop(props, "flip_x", toggle=True)
        row.prop(props, "flip_y", toggle=True)


class CAMOVERLAY_PT_support_panel(bpy.types.Panel):
    bl_label = "Support"
    bl_idname = "CAMOVERLAY_PT_support_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Camera Overlay'
    bl_parent_id = "CAMOVERLAY_PT_main_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("camoverlay.diagnostics", icon='CONSOLE')
        layout.label(text="Colours use the image's own", icon='INFO')
        layout.label(text="colour space setting")


classes = (
    CAMOVERLAY_PT_main_panel,
    CAMOVERLAY_PT_display_panel,
    CAMOVERLAY_PT_transform_panel,
    CAMOVERLAY_PT_support_panel,
)
