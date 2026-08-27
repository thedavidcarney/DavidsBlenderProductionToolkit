"""Viewport drawing for the placement operator.

Without this you click three times into empty space and only find out what you
made after it exists. The overlay shows where each click will land, the chord
once the first point is down, and a live preview of the actual curve -- using
the same maths the node group runs, so it isn't a stylised approximation.

Drawing is best-effort by design. A GPU error must never take the placement
operator down with it: on failure the overlay switches itself off and
placement carries on blind, which is strictly better than losing the strand
you were halfway through.
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import shape

# Shader names changed in 3.4 (the '3D_' prefix was dropped) and older names
# still work on some builds. Try in order and keep the first that exists.
_LINE_SHADER_NAMES = ('POLYLINE_UNIFORM_COLOR', 'UNIFORM_COLOR', '3D_UNIFORM_COLOR')
_POINT_SHADER_NAMES = ('UNIFORM_COLOR', '3D_UNIFORM_COLOR')

COLOR_CURVE = (1.0, 0.62, 0.22, 1.0)      # warm orange, reads as cable
COLOR_CHORD = (0.45, 0.45, 0.5, 0.55)     # dim straight reference line
COLOR_ANCHOR = (0.25, 1.0, 0.45, 1.0)     # placed start/end points
COLOR_CURSOR = (1.0, 1.0, 1.0, 0.9)       # where the next click would land
COLOR_SAG = (0.35, 0.7, 1.0, 1.0)         # the sag handle
COLOR_BULB = (1.0, 0.93, 0.7, 1.0)        # preview bulb positions

CURVE_WIDTH = 2.5
CHORD_WIDTH = 1.0
ANCHOR_SIZE = 11.0
CURSOR_SIZE = 9.0
BULB_SIZE = 6.0

# Bulbs are drawn as points, and a 40m strand at 10cm spacing would be 400 of
# them fighting for the same pixels. Past this the preview stops being useful
# and starts being soup, so cap it.
MAX_PREVIEW_BULBS = 400


def _first_shader(names):
    for name in names:
        try:
            return gpu.shader.from_builtin(name), name
        except (SystemError, ValueError, TypeError):
            continue
    return None, None


class PlacementOverlay:
    """Draw handler tied to one run of the placement operator."""

    def __init__(self, operator):
        self.operator = operator
        self._handle = None
        self._line_shader = None
        self._line_shader_name = None
        self._point_shader = None
        self.failed = False

    # -- lifecycle --------------------------------------------------------

    def enable(self, context):
        self._line_shader, self._line_shader_name = _first_shader(_LINE_SHADER_NAMES)
        self._point_shader, _ = _first_shader(_POINT_SHADER_NAMES)
        if self._line_shader is None and self._point_shader is None:
            self.failed = True
            return False

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_safely, (context,), 'WINDOW', 'POST_VIEW')
        return True

    def disable(self):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

    def tag_redraw(self, context):
        if context.area is not None:
            context.area.tag_redraw()

    # -- drawing ----------------------------------------------------------

    def _draw_safely(self, context):
        if self.failed:
            return
        try:
            self._draw(context)
        except Exception:
            # Never let a draw error kill the modal operator mid-placement.
            self.failed = True
            self.disable()

    def _polyline(self, points, color, width):
        if len(points) < 2 or self._line_shader is None:
            return
        coords = [tuple(p) for p in points]
        shader = self._line_shader
        shader.bind()
        if self._line_shader_name == 'POLYLINE_UNIFORM_COLOR':
            region = gpu.state.viewport_get()
            shader.uniform_float("viewportSize", (region[2], region[3]))
            shader.uniform_float("lineWidth", width)
            batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
        else:
            gpu.state.line_width_set(width)
            batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _points(self, points, color, size):
        if not points or self._point_shader is None:
            return
        shader = self._point_shader
        gpu.state.point_size_set(size)
        shader.bind()
        shader.uniform_float("color", color)
        batch = batch_for_shader(shader, 'POINTS', {"pos": [tuple(p) for p in points]})
        batch.draw(shader)

    def _draw(self, context):
        operator = self.operator
        gpu.state.blend_set('ALPHA')
        # Drawn on top of the scene: a preview hidden behind the truss you're
        # hanging from would be useless exactly when it matters.
        gpu.state.depth_test_set('NONE')

        try:
            start = operator.start
            end = operator.end
            hover = operator.hover

            # Stage 1: just a cursor marker, so you can see where a click lands
            # before committing to it.
            if start is None:
                if hover is not None:
                    self._points([hover], COLOR_CURSOR, CURSOR_SIZE)
                return

            # Stage 2: start is down, the end follows the mouse. Preview the
            # strand using the sag shape that will be inherited, so the shape
            # is visible before the second click rather than after.
            if end is None:
                if hover is None:
                    self._points([start], COLOR_ANCHOR, ANCHOR_SIZE)
                    return
                provisional_sag = shape.sag_from_local(
                    start, hover, operator.sag_along, operator.sag_v, operator.sag_w)
                self._draw_strand(context, start, hover, provisional_sag,
                                  operator.flatness, sag_marker=False)
                self._points([start, hover], COLOR_ANCHOR, ANCHOR_SIZE)
                return

            # Stage 3: both ends down, sag tracking the mouse.
            sag_point = operator.sag
            if sag_point is None:
                sag_point = shape.default_sag_point(start, end)
            self._draw_strand(context, start, end, sag_point, operator.flatness,
                              sag_marker=True)
            self._points([start, end], COLOR_ANCHOR, ANCHOR_SIZE)

        finally:
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.line_width_set(1.0)

    def _draw_strand(self, context, start, end, sag_point, flatness, sag_marker):
        self._polyline([start, end], COLOR_CHORD, CHORD_WIDTH)

        curve = shape.curve_points(start, end, sag_point, flatness)
        self._polyline(curve, COLOR_CURVE, CURVE_WIDTH)

        spacing = getattr(self.operator, "bulb_spacing", 0.0)
        if spacing > 0.0:
            bulbs = shape.resample_polyline(curve, spacing)
            if bulbs and len(bulbs) <= MAX_PREVIEW_BULBS:
                self._points(bulbs, COLOR_BULB, BULB_SIZE)

        if sag_marker:
            self._points([sag_point], COLOR_SAG, ANCHOR_SIZE)
