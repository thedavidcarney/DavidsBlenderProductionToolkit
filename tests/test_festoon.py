"""Headless tests for the Festoon Clicker rig.

Run with tests/run_festoon_test.sh.

Covers the two things that carry real risk:

  * the raycast actually skipping objects the user can't see -- Blender's
    scene.ray_cast has no skip_hidden, and getting this wrong means snapping
    to the inside of a hidden wall

  * the sag maths -- specifically that the curve passes through the sag empty
    regardless of the flatness exponent, which is the property that makes
    position and flatness independent controls instead of two knobs fighting

Everything else here is scaffolding checks: geometry gets generated, bulbs get
instanced, parenting moves the strand rigidly.
"""

import functools
import math
import sys

import bmesh
import bpy
from mathutils import Vector

# Blender fully buffers stdout when it's redirected, so a hang or a hard crash
# loses every print that came before it -- exactly when the trace matters most.
print = functools.partial(print, flush=True)

ADDON = "lightgroup_tools"

FAILURES = []


def check(condition, message):
    if not condition:
        FAILURES.append(message)
    return bool(condition)


bpy.ops.preferences.addon_enable(module=ADDON)
for name, module in list(sys.modules.items()):
    if name.endswith(".updater") and hasattr(module, "_auto_check_done_this_session"):
        module._auto_check_done_this_session = True

from lightgroup_tools.festoon import nodes, picking, rig, shape  # noqa: E402


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_cube(name, location, size=1.0):
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def evaluated_vertices(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    data = evaluated.data
    if data is None:
        return []
    matrix = evaluated.matrix_world
    return [matrix @ v.co for v in data.vertices]


def bulb_positions(obj):
    """How many BULBS a strand produces, not how many instances.

    A real bulb asset is a collection -- the bundled marquee bulb is five
    objects -- so one bulb position emits five depsgraph instances. Counting
    raw instances would make bulb counts depend on how the asset happens to be
    modelled. Distinct instance positions is the number that actually means
    "bulbs on the cable".
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    seen = set()
    for instance in depsgraph.object_instances:
        if instance.is_instance and instance.parent == evaluated:
            location = instance.matrix_world.translation
            seen.add((round(location.x, 4), round(location.y, 4), round(location.z, 4)))
    return len(seen)


# --- 1. Raycast skips objects the user can't see ----------------------------

print("\n=== 1. picking: hidden objects must not intercept ===")
reset_scene()

near = make_cube("Near", (0.0, 0.0, 0.0), size=1.0)
far = make_cube("Far", (0.0, 0.0, -5.0), size=1.0)

origin = Vector((0.0, 0.0, 10.0))
direction = Vector((0.0, 0.0, -1.0))

hit = picking.ray_cast_visible(bpy.context, origin, direction)
if check(hit is not None, "[picking] baseline cast hit nothing"):
    check(hit.object is near,
          "[picking] baseline should hit Near, got " + str(hit.object))
    print("    baseline hit: " + repr(hit))

# H-key hide. This is the case scene.ray_cast gets wrong on its own: the object
# stays in the depsgraph and keeps intercepting rays.
near.hide_set(True)
hit = picking.ray_cast_visible(bpy.context, origin, direction)
if check(hit is not None, "[picking] cast hit nothing after hiding Near"):
    check(hit.object is far,
          "[picking] hidden Near still intercepted the ray -- got "
          + str(hit.object) + " (depth peel not working)")
    print("    after hiding Near: " + repr(hit))

# Confirm the peel is genuinely needed, i.e. raw ray_cast still hits the
# hidden object. If Blender ever fixes this the peel becomes redundant and we
# should know rather than carry dead complexity.
raw_hit, _loc, _n, _i, raw_obj, _m = bpy.context.scene.ray_cast(
    bpy.context.evaluated_depsgraph_get(), origin, direction)
# Informational, not a failure. On 5.2 raw ray_cast turns out to already skip
# H-hidden objects, so the peel is not carrying that case. It still earns its
# keep for local view / isolate, the viewport's own object-type toggles, and
# making festoon strands click-through -- all checked below.
print("    raw ray_cast hits H-hidden object: "
      + str(bool(raw_hit and raw_obj is not None and raw_obj.original is near)))

# hide_viewport (monitor icon) leaves the depsgraph entirely.
near.hide_set(False)
far.hide_viewport = True
hit = picking.ray_cast_visible(bpy.context, origin, direction)
check(hit is not None and hit.object is near,
      "[picking] unexpected result with far object hide_viewport'd")
far.hide_viewport = False

# Festoon's own geometry must be transparent to picking, or you can't click
# through a hanging strand to place the next one behind it.
near.hide_set(False)
near[picking.STRAND_PROP] = True
hit = picking.ray_cast_visible(bpy.context, origin, direction)
check(hit is not None and hit.object is far,
      "[picking] a festoon strand intercepted the ray; should be click-through")
del near[picking.STRAND_PROP]

# Nothing in the way at all.
near.hide_set(True)
far.hide_set(True)
check(picking.ray_cast_visible(bpy.context, origin, direction) is None,
      "[picking] expected a miss when everything is hidden")


# --- 2. Chord frame and sticky sag ------------------------------------------

print("=== 2. chord frame + sticky sag ===")

start, end = Vector((-5.0, 0.0, 4.0)), Vector((5.0, 0.0, 4.0))
frame = shape.chord_frame(start, end)
if check(frame is not None, "[shape] horizontal chord produced no frame"):
    u, v, w, span = frame
    check(abs(span - 10.0) < 1e-5, "[shape] span wrong: " + str(span))
    check(v.dot(shape.WORLD_UP) > 0.99, "[shape] v should point up, got " + str(v))
    check(abs(u.dot(v)) < 1e-5 and abs(u.dot(w)) < 1e-5,
          "[shape] frame axes not orthogonal")

# A vertical chord has no unique vertical plane; it must still yield a frame
# rather than dividing by zero.
check(shape.chord_frame(Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 5.0))) is not None,
      "[shape] vertical chord produced no frame")
check(shape.chord_frame(start, start) is None,
      "[shape] coincident endpoints should produce no frame")

# Round-tripping a sag point through chord-relative form must be lossless --
# that conversion is what carries the shape to the next strand.
sag = shape.default_sag_point(start, end)
along, v_ratio, w_ratio = shape.sag_to_local(start, end, sag)
restored = shape.sag_from_local(start, end, along, v_ratio, w_ratio)
check((restored - sag).length < 1e-5,
      "[shape] sag round-trip drifted: " + str(sag) + " -> " + str(restored))
check(abs(along - 0.5) < 1e-5, "[shape] default sag should sit mid-span")
check(sag.z < start.z, "[shape] default sag should hang below the chord")

# The same relative shape on a much longer span should scale with it, which is
# the whole reason sticky sag is stored as ratios.
long_start, long_end = Vector((-20.0, 0.0, 4.0)), Vector((20.0, 0.0, 4.0))
long_sag = shape.sag_from_local(long_start, long_end, along, v_ratio, w_ratio)
drop_short = start.z - sag.z
drop_long = long_start.z - long_sag.z
check(abs(drop_long / drop_short - 4.0) < 1e-4,
      "[shape] sticky sag did not scale with span: "
      + str(drop_short) + " vs " + str(drop_long))

# shape() must be 0 at both ends and exactly 1 at the low point, for ANY
# exponent. That's what keeps position and flatness independent.
for exponent in (1.0, 2.2, 6.0):
    for along_test in (0.2, 0.5, 0.8):
        check(abs(shape.evaluate_shape(0.0, along_test, exponent)) < 1e-6,
              "[shape] not 0 at t=0 (p=%s, tc=%s)" % (exponent, along_test))
        check(abs(shape.evaluate_shape(1.0, along_test, exponent)) < 1e-6,
              "[shape] not 0 at t=1 (p=%s, tc=%s)" % (exponent, along_test))
        check(abs(shape.evaluate_shape(along_test, along_test, exponent) - 1.0) < 1e-6,
              "[shape] not 1 at the low point (p=%s, tc=%s)" % (exponent, along_test))

# Higher exponent = flatter bottom: at a quarter span from the low point, a
# high-p curve should still be closer to full depth than a low-p one.
near_bottom_sharp = shape.evaluate_shape(0.375, 0.5, 1.0)
near_bottom_flat = shape.evaluate_shape(0.375, 0.5, 6.0)
check(near_bottom_flat > near_bottom_sharp,
      "[shape] higher exponent should flatten the bottom: "
      + str(near_bottom_sharp) + " vs " + str(near_bottom_flat))


# --- 3. The rig generates real geometry -------------------------------------

print("=== 3. strand generation ===")
reset_scene()

start = Vector((-5.0, 0.0, 4.0))
end = Vector((5.0, 0.0, 4.0))
sag = shape.default_sag_point(start, end)

strand = rig.create_strand(bpy.context, start, end, sag, flatness=1.0)
bpy.context.view_layer.update()

check(strand.get(picking.STRAND_PROP) is not None,
      "[rig] strand not tagged -- create_for_each_light will never find it")
check(len(strand.modifiers) == 1 and strand.modifiers[0].type == 'NODES',
      "[rig] strand has no geometry nodes modifier")

collection = bpy.data.collections.get(rig.COLLECTION_NAME)
check(collection is not None, "[rig] Festoons collection not created")

children = [o for o in bpy.data.objects if o.parent is strand]
check(len(children) == 3,
      "[rig] expected 3 control empties parented to the strand, got "
      + str(len(children)))

vertices = evaluated_vertices(strand)
check(len(vertices) > 0, "[rig] strand generated no geometry at all")
print("    cable vertices: " + str(len(vertices)))

bulbs = bulb_positions(strand)
print("    bulb instances: " + str(bulbs))
check(bulbs > 0, "[rig] no bulbs instanced")


# --- 4. The curve actually passes through the sag empty ---------------------

print("=== 4. curve honours the sag empty at every flatness ===")

sag_empty = next(o for o in children if o.name.endswith("_Sag"))

for flatness in (0.3, 1.0, 3.0):
    sag_empty.scale = (flatness, flatness, flatness)
    bpy.context.view_layer.update()
    vertices = evaluated_vertices(strand)
    if not vertices:
        FAILURES.append("[rig] no geometry at flatness " + str(flatness))
        continue

    lowest = min(v.z for v in vertices)
    # Geometry is a tube around the curve, so the lowest vertex sits a cable
    # radius below the curve itself.
    expected = sag.z - 0.008
    print("    flatness %-4s lowest z=%.4f (sag z=%.4f)"
          % (flatness, lowest, sag.z))
    check(abs(lowest - expected) < 0.05,
          "[rig] curve missed the sag empty at flatness " + str(flatness)
          + ": lowest z " + str(round(lowest, 4)) + ", expected near "
          + str(round(expected, 4)))

sag_empty.scale = (1.0, 1.0, 1.0)

# Flatness must change the curve's shape without moving its low point. Compare
# the curve's depth a quarter-span from the middle.
def quarter_depth(flatness):
    sag_empty.scale = (flatness,) * 3
    bpy.context.view_layer.update()
    verts = evaluated_vertices(strand)
    near_quarter = [v for v in verts if abs(v.x - (-2.5)) < 0.15]
    return min(v.z for v in near_quarter) if near_quarter else None

sharp = quarter_depth(0.3)
flat = quarter_depth(3.0)
if check(sharp is not None and flat is not None,
         "[rig] could not sample the curve at quarter span"):
    print("    quarter-span depth: sharp=%.4f flat=%.4f" % (sharp, flat))
    check(flat < sharp,
          "[rig] flatness did not broaden the curve: sharp=" + str(round(sharp, 4))
          + " flat=" + str(round(flat, 4)))
sag_empty.scale = (1.0, 1.0, 1.0)
bpy.context.view_layer.update()


# --- 5. Bulb spacing ---------------------------------------------------------

print("=== 5. bulb spacing responds to the modifier input ===")

modifier = strand.modifiers[0]
tree = modifier.node_group

counts = {}
for spacing in (1.0, 0.25):
    rig.set_parameter(tree, modifier, "Bulb Spacing", spacing)
    bpy.context.view_layer.update()
    counts[spacing] = bulb_positions(strand)
    print("    spacing %-5s -> %d bulbs" % (spacing, counts[spacing]))

check(counts[0.25] > counts[1.0] * 2,
      "[rig] tightening spacing did not add bulbs: "
      + str(counts[1.0]) + " -> " + str(counts[0.25]))

# Roughly length / spacing. Loose bounds -- resample-by-length redistributes to
# come out even, so the count is approximate by design.
check(3 <= counts[1.0] <= 16,
      "[rig] implausible bulb count at 1.0m spacing on a ~10m strand: "
      + str(counts[1.0]))

rig.set_parameter(tree, modifier, "Bulb Spacing", 0.5)


# --- 6. Moving the strand moves everything rigidly --------------------------

print("=== 6. rigid parent move ===")

bpy.context.view_layer.update()
before = evaluated_vertices(strand)
before_low = min(v.z for v in before)

strand.location = (10.0, 5.0, 0.0)
bpy.context.view_layer.update()
after = evaluated_vertices(strand)

check(len(after) == len(before),
      "[rig] vertex count changed on a pure translation")
if after and before:
    after_low = min(v.z for v in after)
    check(abs(after_low - before_low) < 1e-4,
          "[rig] strand deformed instead of translating: z " + str(before_low)
          + " -> " + str(after_low))
    shifted = min(v.x for v in after) - min(v.x for v in before)
    check(abs(shifted - 10.0) < 1e-4,
          "[rig] strand did not follow its parent in x, moved " + str(shifted))

strand.location = (0.0, 0.0, 0.0)


# --- 7. Node group reuse ----------------------------------------------------

print("=== 7. each strand gets its own node group ===")

second = rig.create_strand(bpy.context, Vector((0.0, 5.0, 3.0)),
                           Vector((6.0, 5.0, 3.0)),
                           shape.default_sag_point(Vector((0.0, 5.0, 3.0)),
                                                   Vector((6.0, 5.0, 3.0))))
bpy.context.view_layer.update()

# Per strand, NOT shared. Forced by a Blender 5.2 bug: an Object assigned to
# a geometry nodes MODIFIER input hangs evaluation outright, so the objects
# live on nodes instead, and node datablocks are per-tree.
groups = [g for g in bpy.data.node_groups if g.name.startswith("Festoon Strand")]
check(len(groups) == 2,
      "[rig] expected one node group per strand, found "
      + str([g.name for g in groups]))
check(second.modifiers[0].node_group is not strand.modifiers[0].node_group,
      "[rig] strands are sharing a node group -- they would fight over the "
      "Object Info datablocks and both point at the same empties")
check(len(evaluated_vertices(second)) > 0, "[rig] second strand generated nothing")

# The two strands must resolve to different places in space.
first_x = sorted(v.x for v in evaluated_vertices(strand))
second_x = sorted(v.x for v in evaluated_vertices(second))
check(abs(min(first_x) - min(second_x)) > 1.0,
      "[rig] both strands generated at the same place -- node datablocks "
      "were not set per strand")


# --- 8. The placement preview must match what actually gets built -----------
#
# The overlay draws shape.curve_points(). The strand is built by the node
# group. Those are two separate implementations of the same maths, and a
# preview that quietly disagrees with the result is worse than no preview --
# you would trust it and be wrong. This pins them together.
#
# (The GPU drawing itself can't be tested headlessly -- no GL context in
# background mode -- so this checks the geometry the overlay would draw.)

print("=== 8. preview curve matches generated geometry ===")
reset_scene()

start = Vector((-6.0, 1.0, 5.0))
end = Vector((4.0, -2.0, 3.5))          # deliberately not axis-aligned
sag = shape.default_sag_point(start, end)

strand = rig.create_strand(bpy.context, start, end, sag, flatness=1.0)

# Crank the cable resolution up for this comparison. The measurement is
# "distance from a preview point to the nearest generated VERTEX", so at the
# default 64 rings over an 11m curve, half a ring spacing (~0.09m) swamps any
# real disagreement and the test would pass no matter how wrong the maths was.
# At 256 the sampling floor drops to ~0.02m and the tolerance below actually
# bites.
_modifier = strand.modifiers[0]
rig.set_parameter(_modifier.node_group, _modifier, "Curve Resolution", 256)
bpy.context.view_layer.update()

preview = shape.curve_points(start, end, sag, 1.0)
check(len(preview) > 2, "[preview] curve_points returned nothing usable")
check((preview[0] - start).length < 1e-5,
      "[preview] curve does not start at the start point")
check((preview[-1] - end).length < 1e-5,
      "[preview] curve does not end at the end point")

# The low point of the preview must sit on the sag empty, same property the
# node group guarantees.
closest = min(preview, key=lambda p: (p - sag).length)
check((closest - sag).length < 0.15,
      "[preview] curve does not pass through the sag point, nearest was "
      + str(round((closest - sag).length, 4)) + "m away")

# Now the real comparison: every sampled preview point should lie on the
# generated cable, within a cable radius plus a little slack for the tube's
# faceting.
actual = evaluated_vertices(strand)
if check(len(actual) > 0, "[preview] strand generated no geometry to compare"):
    worst = 0.0
    for index in range(0, len(preview), 4):
        point = preview[index]
        nearest = min((point - v).length for v in actual)
        worst = max(worst, nearest)
    print("    worst preview-to-geometry distance: %.4f m" % worst)
    check(worst < 0.03,
          "[preview] preview curve drifts from the built strand by "
          + str(round(worst, 4)) + "m -- the overlay is lying about the result")

# Flatness must move the preview the same way it moves the real curve.
sag_empty = next(o for o in bpy.data.objects if o.name.endswith("_Sag"))
for flatness in (0.3, 3.0):
    sag_empty.scale = (flatness,) * 3
    bpy.context.view_layer.update()
    built = evaluated_vertices(strand)
    predicted = shape.curve_points(start, end, sag, flatness)
    worst = 0.0
    for index in range(0, len(predicted), 4):
        point = predicted[index]
        worst = max(worst, min((point - v).length for v in built))
    print("    flatness %-4s worst distance: %.4f m" % (flatness, worst))
    check(worst < 0.03,
          "[preview] preview and geometry disagree at flatness "
          + str(flatness) + ": " + str(round(worst, 4)) + "m")
sag_empty.scale = (1.0, 1.0, 1.0)


# --- 9. Preview bulb spacing ------------------------------------------------

print("=== 9. preview bulb spacing ===")

curve = shape.curve_points(start, end, sag, 1.0)
length = sum((curve[i + 1] - curve[i]).length for i in range(len(curve) - 1))

for spacing in (1.0, 0.4):
    points = shape.resample_polyline(curve, spacing)
    expected = round(length / spacing) + 1
    print("    spacing %-4s -> %d points (curve %.2fm, expected ~%d)"
          % (spacing, len(points), length, expected))
    check(abs(len(points) - expected) <= 1,
          "[preview] resample count off for spacing " + str(spacing)
          + ": got " + str(len(points)) + ", expected ~" + str(expected))
    if len(points) > 2:
        gaps = [(points[i + 1] - points[i]).length for i in range(len(points) - 1)]
        spread = max(gaps) - min(gaps)
        check(spread < spacing * 0.25,
              "[preview] resampled points are unevenly spaced, spread "
              + str(round(spread, 4)))
        # Both ends must land on the curve -- no stub at one end.
        check((points[0] - curve[0]).length < 1e-5,
              "[preview] first resampled point is not at the curve start")
        check((points[-1] - curve[-1]).length < 0.05,
              "[preview] last resampled point is not at the curve end")

check(shape.resample_polyline(curve, 0.0) == [],
      "[preview] zero spacing should yield no points, not a hang")
check(shape.resample_polyline([], 0.5) == [],
      "[preview] empty polyline should yield no points")


# --- 10. Bundled marquee bulb + bulb source collection ----------------------

print("=== 10. bundled bulb asset ===")
reset_scene()

start = Vector((-4.0, 0.0, 3.0))
end = Vector((4.0, 0.0, 3.0))
strand = rig.create_strand(bpy.context, start, end,
                           shape.default_sag_point(start, end))
bpy.context.view_layer.update()

# The bundled asset must actually load, not silently fall back to the sphere.
marquee = bpy.data.collections.get(rig.BULB_ASSET_COLLECTION)
if check(marquee is not None,
         "[bulb] bundled '" + rig.BULB_ASSET_COLLECTION
         + "' collection did not load from the addon assets folder"):
    names = sorted(o.name for o in marquee.all_objects)
    print("    bulb objects: " + str(names))
    check(len(names) >= 4,
          "[bulb] marquee bulb should be a multi-object collection, got " + str(names))

# Sources belong in their own collection, NOT mixed in with the strands.
bulb_collection = bpy.data.collections.get(rig.BULB_COLLECTION_NAME)
if check(bulb_collection is not None,
         "[bulb] '" + rig.BULB_COLLECTION_NAME + "' collection was not created"):
    check(any(c is marquee for c in bulb_collection.children),
          "[bulb] marquee bulb is not parented under " + rig.BULB_COLLECTION_NAME)

festoons = bpy.data.collections.get(rig.COLLECTION_NAME)
if festoons is not None:
    stray = [o.name for o in festoons.objects if "Bulb" in o.name]
    check(not stray,
          "[bulb] bulb sources are polluting the Festoons collection: " + str(stray))
    check(not any(c is marquee for c in festoons.children),
          "[bulb] marquee bulb collection is nested under Festoons")

# The load-bearing part: the source collection is HIDDEN (eye off) and must
# still instance. If hiding dropped it out of the depsgraph every strand in
# the scene would silently lose its bulbs.
bulbs = bulb_positions(strand)
print("    bulb instances from hidden collection: " + str(bulbs))
check(bulbs > 0,
      "[bulb] no instances -- hiding the bulb source collection killed them")

def layer_collection_hidden(name):
    def walk(layer):
        if layer.collection.name == name:
            return layer.hide_viewport
        for child in layer.children:
            found = walk(child)
            if found is not None:
                return found
        return None
    return walk(bpy.context.view_layer.layer_collection)

check(layer_collection_hidden(rig.BULB_COLLECTION_NAME) is True,
      "[bulb] bulb source collection should be hidden (eye off) in the view layer")

# Instanced geometry should be the real bulb, not the fallback sphere. The
# marquee bulb is ~0.14m across; the stand-in is a 0.06m sphere.
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated_strand = strand.evaluated_get(depsgraph)
widest = 0.0
for instance in depsgraph.object_instances:
    if instance.is_instance and instance.parent == evaluated_strand:
        source = instance.object
        if source and source.type == 'MESH':
            widest = max(widest, max(source.dimensions))
print("    largest instanced object dimension: %.4f m" % widest)
check(widest > 0.1,
      "[bulb] instanced geometry looks like the fallback sphere, not the "
      "marquee bulb (largest dimension " + str(round(widest, 4)) + "m)")

# A user-supplied collection must win over the bundled default.
custom = bpy.data.collections.new("My Custom Bulb")
bpy.context.scene.collection.children.link(custom)
custom_strand = rig.create_strand(
    bpy.context, Vector((-4.0, 6.0, 3.0)), Vector((4.0, 6.0, 3.0)),
    shape.default_sag_point(Vector((-4.0, 6.0, 3.0)), Vector((4.0, 6.0, 3.0))),
    bulb_collection=custom)
node = rig.strand_node(custom_strand, nodes.NODE_BULB_COLLECTION)
if check(node is not None, "[bulb] strand has no bulb collection node"):
    check(node.inputs["Collection"].default_value is custom,
          "[bulb] explicit bulb collection was overridden by the default")

# Calling again must not append a second copy of the asset.
before = len([c for c in bpy.data.collections
              if c.name.startswith(rig.BULB_ASSET_COLLECTION)])
rig.ensure_marquee_bulb(bpy.context)
after = len([c for c in bpy.data.collections
             if c.name.startswith(rig.BULB_ASSET_COLLECTION)])
check(before == after,
      "[bulb] ensure_marquee_bulb appended a duplicate on the second call: "
      + str(before) + " -> " + str(after))


# --- Result -----------------------------------------------------------------

print("\n" + "=" * 60)
if FAILURES:
    print("FESTOON TEST: FAILED (" + str(len(FAILURES)) + " problem(s))")
    for failure in FAILURES:
        print("  FAIL  " + failure)
    print("=" * 60)
    sys.exit(1)

print("FESTOON TEST: PASSED")
print("=" * 60)
