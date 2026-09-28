"""Camera Overlay operators."""

import bpy


class CAMOVERLAY_OT_match_resolution(bpy.types.Operator):
    """Set the render resolution to the overlay image's pixel size"""

    bl_idname = "camoverlay.match_resolution"
    bl_label = "Match File to Image Resolution"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Failing poll is what greys the button out -- no image, nothing to
        # match.
        props = getattr(context.scene, "cam_overlay", None)
        return props is not None and props.image is not None

    def execute(self, context):
        image = context.scene.cam_overlay.image
        width, height = image.size

        # A missing or unreadable file reports 0x0. Writing that would give a
        # 4x4 render (Blender's floor), so refuse and say why.
        if width <= 0 or height <= 0:
            self.report({'ERROR'},
                        "Could not read the size of '" + image.name
                        + "' -- is the file missing?")
            return {'CANCELLED'}

        render = context.scene.render
        render.resolution_x = width
        render.resolution_y = height

        # Resolution % is deliberately left alone: it is a preview-quality
        # knob, and quietly resetting it would change someone's test renders.
        message = "Resolution set to " + str(width) + " x " + str(height)
        if render.resolution_percentage != 100:
            message += " (render % is " + str(render.resolution_percentage) \
                + ", not 100)"
        self.report({'INFO'}, message)
        return {'FINISHED'}


classes = (
    CAMOVERLAY_OT_match_resolution,
)
