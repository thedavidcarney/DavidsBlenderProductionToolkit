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
