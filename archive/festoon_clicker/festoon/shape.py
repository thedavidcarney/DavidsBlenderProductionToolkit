"""Chord-frame maths for strand placement.

Kept free of bpy operator context so it can be tested headlessly, and so the
sag geometry is readable in one place rather than smeared through the modal
operator.

The chord frame for a strand running P0 -> P1:

    u   along the chord
    v   perpendicular to the chord, in the vertical plane containing it,
        pointing up
    w   horizontal, perpendicular to both

Placement constrains the sag point to the u/v plane, so dragging the mouse
during the third click gives depth and asymmetry but never accidental
sideways bow. Bow is still available afterwards by dragging the empty itself,
since the node group takes the full 3D offset.
"""

import math

from mathutils import Vector

WORLD_UP = Vector((0.0, 0.0, 1.0))

# Sag as a fraction of span when a strand is placed with no prior shape to
# inherit. 15% reads as a relaxed festoon rather than a washing line.
DEFAULT_SAG_RATIO = -0.15
DEFAULT_SAG_ALONG = 0.5

# Sag empty scale, which the node group turns into the shape exponent.
# 1.0 lands on a catenary-looking curve.
DEFAULT_FLATNESS = 1.0
MIN_FLATNESS = 0.2
MAX_FLATNESS = 4.0

DEGENERATE = 1e-6

# Sag empty scale -> shape exponent. Scale 1.0 lands on a catenary-ish 2.2.
# Lives here rather than in nodes.py so the viewport preview and the node group
# cannot drift apart -- a preview that lies about the result is worse than no
# preview.
FLATNESS_TO_EXPONENT = 2.2
EXPONENT_MIN = 1.0
EXPONENT_MAX = 8.0


def flatness_to_exponent(flatness):
    return max(EXPONENT_MIN, min(EXPONENT_MAX, flatness * FLATNESS_TO_EXPONENT))


def chord_frame(start, end):
    """Return (u, v, w, span), or None if the endpoints coincide."""
    chord = Vector(end) - Vector(start)
    span = chord.length
    if span < DEGENERATE:
        return None

    u = chord / span

    w = u.cross(WORLD_UP)
    if w.length < DEGENERATE:
        # Vertical chord: the "vertical plane containing it" is ambiguous, so
        # any perpendicular will do.
        w = u.cross(Vector((1.0, 0.0, 0.0)))
        if w.length < DEGENERATE:
            w = u.cross(Vector((0.0, 1.0, 0.0)))
    w.normalize()

    v = w.cross(u).normalized()
    if v.dot(WORLD_UP) < 0.0:
        # Keep v pointing up so a negative sag ratio always means "hangs down",
        # whichever end was clicked first.
        v = -v
        w = -w

    return u, v, w, span


def sag_to_local(start, end, sag_point):
    """Express a world-space sag point in chord-relative terms.

    Returns (along, v_ratio, w_ratio) where `along` is 0..1 down the chord and
    the ratios are offsets as a fraction of span. Storing it this way is what
    lets the next strand inherit the same *shape* rather than the same
    absolute offset, so a 3m strand and a 20m strand both look right.
    """
    frame = chord_frame(start, end)
    if frame is None:
        return DEFAULT_SAG_ALONG, DEFAULT_SAG_RATIO, 0.0

    u, v, w, span = frame
    relative = Vector(sag_point) - Vector(start)
    along = relative.dot(u) / span
    offset = Vector(sag_point) - (Vector(start) + u * (along * span))
    return along, offset.dot(v) / span, offset.dot(w) / span


def sag_from_local(start, end, along, v_ratio, w_ratio=0.0):
    """Rebuild a world-space sag point from chord-relative terms."""
    frame = chord_frame(start, end)
    if frame is None:
        return (Vector(start) + Vector(end)) * 0.5

    u, v, w, span = frame
    base = Vector(start) + u * (along * span)
    return base + v * (v_ratio * span) + w * (w_ratio * span)


def default_sag_point(start, end):
    return sag_from_local(start, end, DEFAULT_SAG_ALONG, DEFAULT_SAG_RATIO)


def sag_plane(start, end):
    """Plane containing the chord and world up, as (point, normal).

    Used during the third click so the mouse drags the sag within the strand's
    own vertical plane.
    """
    frame = chord_frame(start, end)
    if frame is None:
        return Vector(start), WORLD_UP.copy()
    _u, _v, w, _span = frame
    midpoint = (Vector(start) + Vector(end)) * 0.5
    return midpoint, w


def clamp_flatness(value):
    return max(MIN_FLATNESS, min(MAX_FLATNESS, value))


def evaluate_shape(t, along, exponent):
    """The node group's shape function, in Python.

    Duplicated here purely so tests can assert the node tree agrees with the
    intended maths -- the node group is the thing that actually runs. If these
    two ever disagree, the node group is right and this is stale.
    """
    along = max(0.02, min(0.98, along))
    denominator = along if t < along else (1.0 - along)
    ratio = min(1.0, abs(t - along) / max(denominator, 1e-4))
    return 1.0 - math.pow(ratio, exponent)


def sag_along(start, end, sag_point):
    """Where the sag empty sits along the chord, clamped off the ends.

    Matches the clamp inside the node group. Past the ends the shape function
    divides by ~zero and the curve blows up.
    """
    frame = chord_frame(start, end)
    if frame is None:
        return 0.5
    u, _v, _w, span = frame
    raw = (Vector(sag_point) - Vector(start)).dot(u) / span
    return max(0.02, min(0.98, raw))


def curve_points(start, end, sag_point, flatness, segments=64):
    """The strand curve as a polyline, in world space.

    The same maths the node group runs, so the placement preview shows what
    you will actually get rather than an approximation of it.
    """
    start = Vector(start)
    end = Vector(end)
    sag_point = Vector(sag_point)

    frame = chord_frame(start, end)
    if frame is None:
        return [start, end]

    u, _v, _w, span = frame
    along = sag_along(start, end, sag_point)
    offset = sag_point - (start + u * (along * span))
    exponent = flatness_to_exponent(flatness)

    points = []
    for index in range(segments + 1):
        t = index / segments
        points.append(start.lerp(end, t) + offset * evaluate_shape(t, along, exponent))
    return points


def resample_polyline(points, spacing):
    """Evenly spaced points along a polyline.

    Mirrors Blender's resample-by-length closely enough for a preview: the
    requested spacing sets the count, then the points are redistributed evenly
    so both ends land on the curve instead of leaving a stub.
    """
    if len(points) < 2 or spacing <= 0.0:
        return []

    segment_lengths = [(points[i + 1] - points[i]).length
                       for i in range(len(points) - 1)]
    total = sum(segment_lengths)
    if total <= 0.0:
        return []

    count = max(2, int(round(total / spacing)) + 1)
    step = total / (count - 1)

    result = [points[0].copy()]
    target = step
    travelled = 0.0
    index = 0
    while index < len(segment_lengths) and len(result) < count:
        length = segment_lengths[index]
        if length <= 0.0:
            index += 1
            continue
        while target <= travelled + length and len(result) < count:
            factor = (target - travelled) / length
            result.append(points[index].lerp(points[index + 1], factor))
            target += step
        travelled += length
        index += 1

    if len(result) < count:
        result.append(points[-1].copy())
    return result


def helix_points(base, top, radius, turns, segments=None):
    """A plain helix around the base-to-top axis, for the placement preview.

    Deliberately NOT the shrinkwrapped result -- reproducing that would mean
    re-running a raycast per point on every mouse move. What the preview is
    for is judging turn DENSITY while dragging, and a nominal-radius helix
    shows that honestly.
    """
    base = Vector(base)
    top = Vector(top)
    axis = top - base
    height = axis.length
    if height < DEGENERATE or turns <= 0.0:
        return [base, top]

    axis.normalize()
    side = axis.cross(WORLD_UP)
    if side.length < DEGENERATE:
        side = axis.cross(Vector((1.0, 0.0, 0.0)))
    side.normalize()
    up = axis.cross(side)

    if segments is None:
        segments = max(24, min(1200, int(turns * 16)))

    points = []
    for index in range(segments + 1):
        t = index / segments
        angle = t * turns * 2.0 * math.pi
        points.append(base + axis * (t * height)
                      + side * (math.cos(angle) * radius)
                      + up * (math.sin(angle) * radius))
    return points
