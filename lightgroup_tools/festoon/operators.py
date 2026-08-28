"""The placement operator.

Three clicks: start, end, sag. The sag shape carries over to the next strand,
so a run of similar strands is two clicks and an accept rather than three
deliberate ones.

Placement stays active after each strand until you escape out. Hanging one
festoon is rare; hanging fifteen is Tuesday.
"""

import bpy
from mathutils import Vector

from . import rig, shape
from .overlay import PlacementOverlay
from .picking import pick, point_on_plane

STAGE_START = 'START'
STAGE_END = 'END'
STAGE_SAG = 'SAG'

# Scroll-wheel step for the flatness control during the sag stage.
FLATNESS_STEP = 0.15

# Hard ceiling on wraps. A mouse slip while dragging shouldn't ask Blender for
# eight hundred turns of cable and several thousand bulbs.
MAX_WRAPS = 50.0
MIN_WRAPS = 1.0

# Pixels of vertical mouse travel per added wrap. The full 1..50 range is about
# 750px, so a twitch moves it by one or two rather than tens.
PIXELS_PER_WRAP = 15.0


class FestoonSettings(bpy.types.PropertyGroup):
    """Per-scene placement state.

    The sag shape is stored chord-relative (fractions of span) rather than as
    a world offset, so inheriting it onto a 30m strand gives the same look as
    on a 3m one instead of a nearly-straight line or a puddle.
    """

    sag_along: bpy.props.FloatProperty(
        name="Sag Position", default=shape.DEFAULT_SAG_ALONG, min=0.0, max=1.0)
    sag_v_ratio: bpy.props.FloatProperty(
        name="Sag Depth", default=shape.DEFAULT_SAG_RATIO)
    sag_w_ratio: bpy.props.FloatProperty(name="Sag Bow", default=0.0)
    flatness: bpy.props.FloatProperty(
        name="Flatness", default=shape.DEFAULT_FLATNESS,
        min=shape.MIN_FLATNESS, max=shape.MAX_FLATNESS,
        description="How flat the bottom of the curve is. Low is a sharp V, high is a broad swag")
    bulb_collection: bpy.props.PointerProperty(
        name="Bulb Collection", type=bpy.types.Collection,
        description="Collection instanced as one bulb. Leave empty for the bundled marquee bulb")
    bulb_object: bpy.props.PointerProperty(
        name="Bulb Object", type=bpy.types.Object,
        description="Single object instanced as the bulb. Only needed if you aren't using a collection")
    spiral_turns: bpy.props.FloatProperty(
        name="Turns", default=6.0, min=1.0, max=50.0,
        description="How many times a wrapped string goes around, base to top")
    bulb_spacing: bpy.props.FloatProperty(
        name="Bulb Spacing", default=0.5, min=0.01, max=100.0, unit='LENGTH',
        description="Distance between bulbs on new strands. Also drives the placement preview")


class FESTOON_OT_place_strand(bpy.types.Operator):
    """Click a start point, an end point, then set the sag.

    Scroll during the sag step to flatten or sharpen the curve.
    Right-click or Escape to stop placing.
    """

    bl_idname = "festoon.place_strand"
    bl_label = "Place Festoon Strand"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    # -- helpers ----------------------------------------------------------

    def _settings(self, context):
        return context.scene.festoon_settings

    def _viewport(self, context):
        space = context.space_data
        return space if getattr(space, "type", None) == 'VIEW_3D' else None

    def _header(self, context):
        if self.stage == STAGE_START:
            text = "Festoon: click the START point   |   Esc/RMB to stop"
        elif self.stage == STAGE_END:
            text = "Festoon: click the END point   |   Esc/RMB to cancel"
        else:
            text = ("Festoon: move to set the sag, click to confirm   |   "
                    "scroll = flatness (%.2f)   |   Esc/RMB to cancel"
                    % self.flatness)
        if self.placed:
            text += "   |   %d placed" % self.placed
        context.area.header_text_set(text)

    def _mouse(self, event):
        return (event.mouse_region_x, event.mouse_region_y)

    def _pick_surface(self, context, event):
        return pick(context, context.region, context.region_data,
                    self._mouse(event), viewport=self._viewport(context))

    def _pick_sag(self, context, event):
        """Sag point, constrained to the strand's own vertical plane.

        Constraining it means the drag can't introduce accidental sideways
        bow. Bow is still reachable afterwards by dragging the empty, since
        the node group consumes the full 3D offset.
        """
        plane_co, plane_no = shape.sag_plane(self.start, self.end)
        point = point_on_plane(context.region, context.region_data,
                               self._mouse(event), plane_co, plane_no)
        if point is None:
            return shape.sag_from_local(self.start, self.end,
                                        self.sag_along, self.sag_v, self.sag_w)
        return point

    def _commit(self, context):
        settings = self._settings(context)
        rig.create_strand(
            context, self.start, self.end, self.sag,
            flatness=self.flatness,
            start_normal=self.start_normal,
            end_normal=self.end_normal,
            bulb_object=settings.bulb_object,
            bulb_collection=settings.bulb_collection,
            bulb_spacing=settings.bulb_spacing,
        )

        # Remember the shape for the next strand.
        along, v_ratio, w_ratio = shape.sag_to_local(self.start, self.end, self.sag)
        settings.sag_along = along
        settings.sag_v_ratio = v_ratio
        settings.sag_w_ratio = w_ratio
        settings.flatness = self.flatness

        self.placed += 1
        # One undo step per strand rather than one for the whole session, so a
        # mistake on strand nine doesn't discard the first eight.
        bpy.ops.ed.undo_push(message="Place Festoon Strand")

    def _reset(self):
        self.stage = STAGE_START
        self.start = None
        self.end = None
        self.start_normal = None
        self.end_normal = None
        self.sag = None
        self.hover = None

    def _finish(self, context):
        # cancel() can fire before invoke() finished wiring things up.
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.disable()
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()
        if context.area is not None:
            context.area.tag_redraw()
        if self.placed:
            self.report({'INFO'}, "Placed %d festoon strand%s"
                        % (self.placed, "" if self.placed == 1 else "s"))

    # -- modal ------------------------------------------------------------

    def invoke(self, context, event):
        if context.region_data is None:
            self.report({'ERROR'}, "Needs a 3D viewport")
            return {'CANCELLED'}

        settings = self._settings(context)
        self.placed = 0
        self.sag_along = settings.sag_along
        self.sag_v = settings.sag_v_ratio
        self.sag_w = settings.sag_w_ratio
        self.flatness = settings.flatness
        self.bulb_spacing = settings.bulb_spacing
        self._reset()

        # The overlay reads this operator's state directly each redraw, so
        # there's nothing to keep in sync -- it always shows current values.
        self.overlay = PlacementOverlay(self)
        if not self.overlay.enable(context):
            self.report({'WARNING'},
                        "Viewport preview unavailable; placing without it")

        context.window.cursor_modal_set('CROSSHAIR')
        self._header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Let the user orbit and zoom mid-placement. Being unable to look
        # around while positioning a 20m strand would be miserable.
        if event.type in {'MIDDLEMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE'} \
                and self.stage != STAGE_SAG:
            return {'PASS_THROUGH'}
        if event.type in {'MIDDLEMOUSE'}:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'FINISHED'} if self.placed else {'CANCELLED'}

        if self.stage == STAGE_SAG and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            step = FLATNESS_STEP if event.type == 'WHEELUPMOUSE' else -FLATNESS_STEP
            self.flatness = shape.clamp_flatness(self.flatness + step)
            self._header(context)
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self.stage == STAGE_SAG:
                self.sag = self._pick_sag(context, event)
                self._header(context)
            else:
                # Snap the marker to the surface under the cursor, so the
                # preview shows the point that would actually be committed --
                # including the depth-peel past anything hidden.
                self.hover = self._pick_surface(context, event).location
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.stage == STAGE_START:
                hit = self._pick_surface(context, event)
                self.start = hit.location
                self.start_normal = hit.normal
                self.stage = STAGE_END

            elif self.stage == STAGE_END:
                hit = self._pick_surface(context, event)
                if (hit.location - self.start).length < 1e-4:
                    self.report({'WARNING'}, "Start and end are the same point")
                    return {'RUNNING_MODAL'}
                self.end = hit.location
                self.end_normal = hit.normal
                # Seed the sag from the remembered shape so a straight
                # click-through reproduces the previous strand.
                self.sag = shape.sag_from_local(self.start, self.end,
                                                self.sag_along, self.sag_v,
                                                self.sag_w)
                self.stage = STAGE_SAG

            else:
                self.sag = self._pick_sag(context, event)
                self._commit(context)
                self._reset()

            self._header(context)
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)


class FESTOON_OT_place_spiral(bpy.types.Operator):
    """Click the base of an object, then the top, to wrap a light string around it.

    The object you click first is the one that gets wrapped. Scroll to change
    how many turns. Right-click or Escape to stop.
    """

    bl_idname = "festoon.place_spiral"
    bl_label = "Wrap Object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def _settings(self, context):
        return context.scene.festoon_settings

    def _viewport(self, context):
        space = context.space_data
        return space if getattr(space, "type", None) == 'VIEW_3D' else None

    def _header(self, context):
        if self.base is None:
            text = "Wrap: click the BASE of the object   |   Esc/RMB to stop"
        elif self.top is None:
            text = "Wrap: click the TOP   |   Esc/RMB to cancel"
        else:
            text = ("Wrap: move up/down to set wraps (%.0f), click to confirm"
                    "   |   Esc/RMB to cancel" % self.turns)
        if self.placed:
            text += "   |   %d placed" % self.placed
        context.area.header_text_set(text)

    def _pick(self, context, event):
        return pick(context, context.region, context.region_data,
                    (event.mouse_region_x, event.mouse_region_y),
                    viewport=self._viewport(context))

    def _set_turns(self, value):
        self.turns = max(MIN_WRAPS, min(MAX_WRAPS, round(value)))

    def _refresh_preview(self):
        if self.base is None or self.top is None:
            self.turns_preview = None
            return
        self.turns_preview = (self.base, self.top, self.preview_radius, self.turns)

    def _finish(self, context):
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.disable()
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()
        if context.area is not None:
            context.area.tag_redraw()
        if self.placed:
            self.report({'INFO'}, "Wrapped %d object%s"
                        % (self.placed, "" if self.placed == 1 else "s"))

    def invoke(self, context, event):
        if context.region_data is None:
            self.report({'ERROR'}, "Needs a 3D viewport")
            return {'CANCELLED'}

        settings = self._settings(context)
        self.placed = 0
        self.turns = max(MIN_WRAPS, min(MAX_WRAPS, settings.spiral_turns))
        self.base = None
        self.top = None
        self.target = None
        self.hover = None
        self.turns_preview = None
        self.preview_radius = 0.5
        self._wrap_anchor_y = 0
        self._wrap_at_anchor = self.turns
        # The overlay reads these off whichever operator owns it. A spiral has
        # no sag stage, so axis_only tells it to draw the axis instead.
        self.start = None
        self.end = None
        self.sag = None
        self.flatness = settings.flatness
        self.bulb_spacing = settings.bulb_spacing
        self.sag_along = settings.sag_along
        self.sag_v = settings.sag_v_ratio
        self.sag_w = settings.sag_w_ratio
        self.axis_only = True

        self.overlay = PlacementOverlay(self)
        self.overlay.enable(context)
        context.window.cursor_modal_set('CROSSHAIR')
        self._header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MIDDLEMOUSE':
            return {'PASS_THROUGH'}
        if event.type in {'WHEELINMOUSE', 'WHEELOUTMOUSE'} and self.base is None:
            return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'FINISHED'} if self.placed else {'CANCELLED'}

        # Scroll still nudges by exactly one, for when the drag lands close.
        if self.top is not None and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            step = 1.0 if event.type == 'WHEELUPMOUSE' else -1.0
            self._set_turns(self.turns + step)
            self._wrap_anchor_y = event.mouse_region_y
            self._wrap_at_anchor = self.turns
            self._header(context)
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self.top is not None:
                # Wrap count from vertical travel, same feel as the sag drag.
                travelled = event.mouse_region_y - self._wrap_anchor_y
                self._set_turns(self._wrap_at_anchor + travelled / PIXELS_PER_WRAP)
                self._refresh_preview()
                self._header(context)
            else:
                self.hover = self._pick(context, event).location
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            hit = self._pick(context, event)
            if self.base is None:
                # Needs a real surface hit: the object under the cursor IS the
                # wrap target, so a fallback point in empty space is useless.
                if hit.object is None:
                    self.report({'WARNING'}, "Click ON the object you want to wrap")
                    return {'RUNNING_MODAL'}
                self.base = hit.location
                self.target = hit.object
                self.start = hit.location

            elif self.top is None:
                if (hit.location - self.base).length < 1e-4:
                    self.report({'WARNING'}, "Base and top are the same point")
                    return {'RUNNING_MODAL'}
                self.top = hit.location
                # Nominal radius for the preview helix, from the object's own
                # girth. The real wrap is raycast onto the surface; this is
                # only here to make turn density readable while dragging.
                if self.target is not None:
                    spread = [d for d in (self.target.dimensions[0],
                                          self.target.dimensions[1]) if d]
                    if spread:
                        self.preview_radius = max(0.02, sum(spread) / len(spread) / 2.0)
                self._wrap_anchor_y = event.mouse_region_y
                self._wrap_at_anchor = self.turns
                self._refresh_preview()

            else:
                settings = self._settings(context)
                rig.create_spiral(context, self.base, self.top, self.target,
                                  bulb_object=settings.bulb_object,
                                  bulb_collection=settings.bulb_collection,
                                  bulb_spacing=settings.bulb_spacing,
                                  turns=self.turns)
                settings.spiral_turns = self.turns
                self.placed += 1
                bpy.ops.ed.undo_push(message="Wrap Object")
                self.base = None
                self.top = None
                self.target = None
                self.start = None
                self.turns_preview = None

            self._header(context)
            self.overlay.tag_redraw(context)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._finish(context)


class FESTOON_OT_select_controls(bpy.types.Operator):
    """Select the start, end and sag empties of the active strand"""

    bl_idname = "festoon.select_controls"
    bl_label = "Select Strand Controls"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("festoon_strand") is not None

    def execute(self, context):
        strand = context.active_object
        controls = [o for o in context.scene.objects if o.parent is strand]
        if not controls:
            self.report({'WARNING'}, "This strand has no control empties")
            return {'CANCELLED'}
        for obj in controls:
            obj.select_set(True)
        self.report({'INFO'}, "Selected %d controls" % len(controls))
        return {'FINISHED'}


classes = (
    FestoonSettings,
    FESTOON_OT_place_strand,
    FESTOON_OT_place_spiral,
    FESTOON_OT_select_controls,
)


def register_properties():
    bpy.types.Scene.festoon_settings = bpy.props.PointerProperty(type=FestoonSettings)


def unregister_properties():
    if hasattr(bpy.types.Scene, "festoon_settings"):
        del bpy.types.Scene.festoon_settings
