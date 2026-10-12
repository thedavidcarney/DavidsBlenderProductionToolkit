"""Headless tests for Solo Light mode (lightgroups/solo.py).

Run via tests/run_solo_test.sh, never directly against a real install.

What is under test:
  - mode on: the selected light stays lit, every other light is muted by ray
    visibility but stays VISIBLE (so it can still be clicked), World off in
    every 3D viewport
  - the solo follows the selection: selecting another light moves it,
    selecting a non-light keeps it, a light added mid-mode is muted
  - F12 during the mode is pixel-identical to an unsoloed render, and a file
    saved mid-mode has no muted light in it -- proven against the renderer and
    the file on disk, not inferred from which handlers exist
  - mode off restores each light's OWN switches, and each viewport's own
    World settings

Selection is driven by select_set + view_layer.update(), which fires the same
depsgraph_update_post a viewport or outliner click does. How the live viewport
LOOKS is checked separately, in a GUI run -- there is no viewport headless.
"""

import atexit
import os
import sys
import tempfile

import bpy

ADDON = "lightgroup_tools"

FAILURES = []

# An uncaught exception aborts this script, but Blender still exits 0 -- so a
# crashed run would look identical to a clean one. Insist on a verdict.
_VERDICT_REACHED = []


def _abort_guard():
    if not _VERDICT_REACHED:
        print("TEST ABORTED before reaching a verdict -- see traceback above")
        sys.stdout.flush()
        os._exit(1)


atexit.register(_abort_guard)


def check(condition, message):
    if not condition:
        FAILURES.append(message)
    return bool(condition)


TMP = tempfile.mkdtemp(prefix="solo_test_")
RAY_FLAGS = ("visible_camera", "visible_diffuse", "visible_glossy",
             "visible_transmission", "visible_volume_scatter")


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    # read_factory_settings resets preferences too, which disables the addon.
    bpy.ops.preferences.addon_enable(module=ADDON)

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 4
    scene.cycles.use_denoising = False
    scene.render.resolution_x = 32
    scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 2.0

    bpy.data.objects["Light"].data.energy = 1000

    def add_light(name, kind, location, energy):
        data = bpy.data.lights.new(name, kind)
        data.energy = energy
        obj = bpy.data.objects.new(name, data)
        obj.location = location
        scene.collection.objects.link(obj)
        return obj

    add_light("Fill", 'AREA', (-4, -2, 3), 800)
    add_light("Rim", 'SPOT', (0, 4, 4), 1500)
    # A light the artist set up deliberately: no glossy. Must come back so.
    bpy.data.objects["Fill"].visible_glossy = False

    # One viewport with non-default World settings, to prove each viewport
    # gets its OWN values back rather than a blanket default.
    spaces = [a.spaces.active for s in bpy.data.screens for a in s.areas
              if a.type == 'VIEW_3D']
    spaces[0].shading.use_scene_world_render = False
    spaces[0].shading.studiolight_intensity = 0.7

    select("Light")


def select(*names):
    """What a click does: change the selection, let the depsgraph update."""
    view_layer = bpy.context.view_layer
    for obj in view_layer.objects:
        obj.select_set(obj.name in names)
    view_layer.objects.active = bpy.data.objects[names[0]] if names else None
    view_layer.update()


def flags(name):
    obj = bpy.data.objects[name]
    return tuple(getattr(obj, f) for f in RAY_FLAGS)


def lit(name):
    return any(flags(name))


def view3d_shading():
    return [(a.spaces.active.shading.use_scene_world_render,
             round(a.spaces.active.shading.studiolight_intensity, 4))
            for s in bpy.data.screens for a in s.areas if a.type == 'VIEW_3D']


def render_pixels(tag):
    path = os.path.join(TMP, tag + ".exr")
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path)
    pixels = list(image.pixels)
    bpy.data.images.remove(image)
    return pixels


def mean(pixels):
    return sum(pixels) / len(pixels)


build_scene()
scene = bpy.context.scene
settings = scene.lightgroup_solo
world_strength = scene.world.node_tree.nodes["Background"].inputs["Strength"]
shading_before = view3d_shading()
flags_before = {n: flags(n) for n in ("Light", "Fill", "Rim")}
baseline = render_pixels("baseline")

# --- 1. Mode on -----------------------------------------------------------------

print("\n=== mode on ===")
check(bpy.ops.lightgroup.solo_light() == {'FINISHED'}, "mode on failed")
check(settings.active, "mode not marked active")
check(lit("Light"), "the selected light was muted")
check(not lit("Fill") and not lit("Rim"), "other lights still lit: Fill %s Rim %s"
      % (flags("Fill"), flags("Rim")))
check(all(bpy.data.objects[n].visible_get() for n in ("Light", "Fill", "Rim")),
      "a muted light was hidden -- it must stay clickable in the viewport")
check(all(s == (False, 0.0) for s in view3d_shading()),
      "a 3D viewport still has the World on: %s" % view3d_shading())
check(world_strength.default_value == 2.0, "World Strength was edited")

# --- 2. The solo follows the selection ------------------------------------------

print("=== click another light ===")
select("Rim")
check(lit("Rim") and not lit("Light") and not lit("Fill"),
      "solo did not follow the selection to Rim: Light %s Fill %s Rim %s"
      % (lit("Light"), lit("Fill"), lit("Rim")))
check(flags("Light") == flags_before["Light"] or not lit("Light"),
      "Light in an odd state")

print("=== shift-click a second light ===")
select("Rim", "Fill")
check(lit("Rim") and lit("Fill") and not lit("Light"), "multi-solo wrong")
check(flags("Fill") == flags_before["Fill"],
      "Fill's own switches not restored when soloed: %s vs %s"
      % (flags("Fill"), flags_before["Fill"]))

print("=== click a non-light ===")
select("Cube")
check(lit("Rim") and lit("Fill") and not lit("Light"),
      "clicking a mesh changed the solo")

print("=== deselect all ===")
select()
check(lit("Rim") and lit("Fill") and not lit("Light"),
      "deselecting everything changed the solo")

print("=== light added mid-mode ===")
data = bpy.data.lights.new("Late", 'POINT')
late = bpy.data.objects.new("Late", data)
scene.collection.objects.link(late)
bpy.context.view_layer.update()
check(not lit("Late"), "a light added mid-mode was not muted")
select("Rim")
check(lit("Rim") and not lit("Fill") and not lit("Late"), "solo back to Rim failed")

# --- 3. F12 sees every light ------------------------------------------------------

print("=== F12 during the mode ===")
bpy.data.objects["Late"].hide_render = True  # not in the baseline
soloed = render_pixels("soloed")
check(soloed == baseline,
      "F12 render changed during solo (mean %.5f vs %.5f) -- solo leaked "
      "into the render" % (mean(soloed), mean(baseline)))
check(not lit("Light") and not lit("Fill"), "lights not re-muted after F12")

# Sensitivity: the comparison above must be able to fail.
for name in ("Light", "Fill"):
    bpy.data.objects[name].hide_render = True
really_off = render_pixels("really_off")
for name in ("Light", "Fill"):
    bpy.data.objects[name].hide_render = False
check(abs(mean(really_off) - mean(baseline)) > 1e-3,
      "render comparison is insensitive")

# --- 4. A file saved mid-mode has every light on ---------------------------------

print("=== save mid-mode ===")
path = os.path.join(TMP, "mid_solo.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
check(not lit("Light") and not lit("Fill"), "lights not re-muted after save")
check(not bpy.data.is_dirty, "re-muting after save marked the file dirty")

# Blender refuses to load from the open file, so inspect a copy -- saved
# through the same save_pre/save_post path.
copy_path = os.path.join(TMP, "mid_solo_copy.blend")
bpy.ops.wm.save_as_mainfile(filepath=copy_path, copy=True)
with bpy.data.libraries.load(copy_path) as (source, target):
    target.objects = ["Light", "Fill"]
on_disk = {obj.name: tuple(getattr(obj, f) for f in RAY_FLAGS)
           for obj in target.objects}
for obj in target.objects:
    bpy.data.objects.remove(obj)
check(on_disk.get("Light.001") == flags_before["Light"],
      "saved file has Light muted: %s" % on_disk)
check(on_disk.get("Fill.001") == flags_before["Fill"],
      "saved file has Fill's switches wrong: %s" % on_disk)

# --- 5. Mode off -----------------------------------------------------------------

print("=== rename mid-mode, then mode off ===")
bpy.data.objects["Light"].name = "Key_renamed"
check(bpy.ops.lightgroup.solo_light() == {'FINISHED'}, "mode off failed")
check(not settings.active, "mode still active")
check(flags("Key_renamed") == flags_before["Light"], "renamed light not restored")
check(flags("Fill") == flags_before["Fill"],
      "Fill's no-glossy not restored verbatim: %s" % (flags("Fill"),))
check(flags("Rim") == flags_before["Rim"], "Rim not restored")
check(lit("Late"), "light added mid-mode left muted")
check(view3d_shading() == shading_before,
      "viewport World settings not restored: %s vs %s"
      % (view3d_shading(), shading_before))

select("Fill")
check(flags("Key_renamed") == flags_before["Light"],
      "selection changes still mute lights after mode off")


# --- Verdict ----------------------------------------------------------------

print()
print("=" * 60)
if FAILURES:
    print("SOLO TEST: FAILED (%d problem(s))" % len(FAILURES))
    for failure in FAILURES:
        print("  FAIL  " + failure)
    print("=" * 60)
    _VERDICT_REACHED.append(True)
    sys.stdout.flush()
    os._exit(1)

print("SOLO TEST: PASSED")
print("=" * 60)
_VERDICT_REACHED.append(True)
sys.stdout.flush()
os._exit(0)
