"""Viewport picking that respects what you can actually see.

`scene.ray_cast` hits geometry regardless of viewport visibility. Objects
hidden with H, or hidden by local view / isolate, are still in the depsgraph
and still get hit -- there is no `skip_hidden` argument. Objects hidden with
the monitor icon (`hide_viewport`) ARE excluded, because those leave the
depsgraph entirely, which is why this looks like it works until someone
presses H.

For a click-to-place tool that's unusable: you'd snap to the inside of a
hidden wall you can't see. So we depth-peel -- cast, test the hit for real
visibility, and if it fails, cast again from just past it.

Festoon's own geometry is skipped too. Without that you can't click "through"
a hanging strand to place the next one behind it, which comes up immediately
once a scene has a few of them.
"""

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_line_plane

from ..core.tags import FESTOON_CONTROL, FESTOON_STRAND

# Defined in core.tags, not here: lightgroups/ has to recognise a strand too,
# and importing festoon from lightgroups would couple two tools that are
# otherwise independent. Re-exported under the local names the rest of this
# package already uses.
STRAND_PROP = FESTOON_STRAND
CONTROL_PROP = FESTOON_CONTROL

# How far to step past a rejected hit before casting again. Small enough to be
# invisible at any sane scene scale, large enough to clear the face we just hit
# rather than immediately re-hitting it on a float rounding error.
PEEL_STEP = 1e-4

# Cap on peel iterations. A ray through a dense hidden crowd should give up
# rather than stall the modal loop.
MAX_PEEL = 64


class Hit:
    """Where a click landed."""

    __slots__ = ("location", "normal", "object")

    def __init__(self, location, normal, obj):
        self.location = location
        self.normal = normal
        self.object = obj

    def __repr__(self):
        name = self.object.name if self.object else "None"
        return "Hit(%s at %s)" % (name, tuple(round(c, 3) for c in self.location))


def is_festoon_object(obj):
    """True for geometry this tool created."""
    if obj is None:
        return False
    original = getattr(obj, "original", obj)
    return bool(original.get(STRAND_PROP) or original.get(CONTROL_PROP))


def is_pickable(obj, view_layer, viewport=None):
    """Can the user actually see this object right now?

    `viewport` is a SpaceView3D. Passing it catches local view / isolate and
    the viewport's own object-type toggles, which a view-layer-only check
    misses. It's optional so this stays callable (and testable) with no
    viewport, e.g. headless.
    """
    if obj is None:
        return False

    original = getattr(obj, "original", obj)

    if is_festoon_object(original):
        return False

    try:
        if viewport is not None:
            return bool(original.visible_get(view_layer=view_layer, viewport=viewport))
        return bool(original.visible_get(view_layer=view_layer))
    except (RuntimeError, TypeError):
        # visible_get rejects a viewport that doesn't belong to this view
        # layer. Fall back rather than abandoning the click.
        try:
            return bool(original.visible_get())
        except RuntimeError:
            return False


def ray_cast_visible(context, origin, direction, viewport=None):
    """Cast a ray, returning the first hit the user can actually see."""
    depsgraph = context.evaluated_depsgraph_get()
    scene = context.scene
    view_layer = context.view_layer

    position = Vector(origin)
    direction = Vector(direction).normalized()

    for _ in range(MAX_PEEL):
        hit, location, normal, _index, obj, _matrix = scene.ray_cast(
            depsgraph, position, direction)
        if not hit:
            return None
        if is_pickable(obj, view_layer, viewport):
            original = getattr(obj, "original", obj)
            return Hit(location.copy(), normal.copy(), original)
        # Step just past this surface and keep going.
        position = location + direction * PEEL_STEP

    return None


def ray_from_mouse(region, region_data, coord):
    """Build a world-space ray from a mouse position in a 3D viewport."""
    origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coord)
    return origin, direction


def point_on_plane(region, region_data, coord, plane_co, plane_no):
    """Where the mouse ray crosses a plane. None if it runs parallel."""
    origin, direction = ray_from_mouse(region, region_data, coord)
    return intersect_line_plane(origin, origin + direction, plane_co, plane_no)


def pick(context, region, region_data, coord, viewport=None):
    """Pick a point under the mouse, falling back when nothing is hit.

    Clicking empty space mid-flow shouldn't abort the placement, so the
    fallback puts the point on a view-facing plane through the 3D cursor. It's
    a guess, but the user can drag the empty afterwards -- refusing the click
    would be worse.
    """
    origin, direction = ray_from_mouse(region, region_data, coord)
    result = ray_cast_visible(context, origin, direction, viewport=viewport)
    if result is not None:
        return result

    plane_co = context.scene.cursor.location
    plane_no = region_data.view_rotation @ Vector((0.0, 0.0, 1.0))
    point = intersect_line_plane(origin, origin + direction, plane_co, plane_no)
    if point is None:
        point = plane_co.copy()
    # No surface, so no meaningful normal -- report straight up.
    return Hit(point, Vector((0.0, 0.0, 1.0)), None)
