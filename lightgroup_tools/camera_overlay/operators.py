"""Diagnostics for the camera overlay.

The lesson behind this whole tool: the addon it replaces fails silently, so
diagnosing it took a source read rather than five minutes. One button that
prints everything relevant in a single block turns "it doesn't work on my
machine" into something a team member can paste into a chat message.
"""

import bpy
import gpu

from . import overlay


class CAMOVERLAY_OT_diagnostics(bpy.types.Operator):
    bl_idname = "camoverlay.diagnostics"
    bl_label = "Diagnostics"
    bl_description = ("Print overlay and GPU details to the system console, "
                      "and copy them to the clipboard")

    def execute(self, context):
        report = "\n".join(self._lines(context))

        print(report)
        try:
            context.window_manager.clipboard = report
            copied = " (copied to clipboard)"
        except Exception:
            # Not worth failing the operator over; the console copy stands.
            copied = ""

        self.report({'INFO'}, "Camera Overlay diagnostics printed to the "
                              "system console%s" % copied)
        return {'FINISHED'}

    def _lines(self, context):
        props = getattr(context.scene, "cam_overlay", None)

        lines = [
            "--- Camera Overlay diagnostics ---",
            "Blender:       %s (%s)" % (bpy.app.version_string,
                                        bpy.app.build_hash.decode()
                                        if isinstance(bpy.app.build_hash, bytes)
                                        else bpy.app.build_hash),
        ]

        # Each GPU query is guarded separately: on a headless or unusual build
        # one can raise while the others still answer, and a half-filled
        # report is far more useful than a traceback.
        for label, getter in (("GPU backend", gpu.platform.backend_type_get),
                              ("GPU vendor", gpu.platform.vendor_get),
                              ("GPU device", gpu.platform.device_type_get)):
            try:
                lines.append("%-14s %s" % (label + ":", getter()))
            except Exception as exc:
                lines.append("%-14s unavailable (%s)" % (label + ":", exc))

        if props is None:
            lines.append("Properties:    NOT REGISTERED")
            return lines

        image = props.image
        if image is None:
            lines.append("Image:         none selected")
        else:
            lines.append("Image:         %s" % image.name_full)
            lines.append("  size:        %d x %d" % (image.size[0], image.size[1]))
            lines.append("  colorspace:  %s" % image.colorspace_settings.name)
            lines.append("  source:      %s" % image.source)
            lines.append("  filepath:    %s" % (image.filepath or "<none>"))
            lines.append("  is_dirty:    %s" % image.is_dirty)
            lines.append("  packed:      %s" % (image.packed_file is not None))
            lines.append("  has_data:    %s" % image.has_data)

        lines.append("Enabled:       %s" % props.enabled)
        lines.append("Handler:       %s" % ("registered"
                                            if overlay.handler_registered()
                                            else "NOT registered"))
        # shader_state(), not get_shader(): reporting must not trigger a
        # compile, or the button can create the fault it is reporting on.
        lines.append("Shader:        %s" % overlay.shader_state())
        lines.append("Mode:          %s" % props.mode)
        lines.append("Fit:           %s" % props.fit)
        lines.append("Opacity:       %.3f" % props.opacity)

        space = context.space_data
        if space is not None and space.type == 'VIEW_3D':
            rv3d = context.region_data
            lines.append("View:          %s" % (rv3d.view_perspective
                                                if rv3d else "unknown"))
        lines.append("Scene camera:  %s" % (context.scene.camera.name
                                            if context.scene.camera else "none"))

        status = overlay.get_status()
        lines.append("Status:        %s" % (status if status else "healthy"))
        lines.append("--- end ---")
        return lines


classes = (
    CAMOVERLAY_OT_diagnostics,
)
