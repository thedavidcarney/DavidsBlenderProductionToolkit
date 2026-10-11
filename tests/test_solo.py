"""Headless tests for Solo Light (lightgroups/solo.py).

Run via tests/run_solo_test.sh, never directly against a real install.

What is under test:
  - the selected lights stay, every other visible light is hidden, the World
    is switched off in every 3D viewport
  - render settings are NOT touched, and a real Cycles F12 render of the
    soloed file is pixel-identical to the unsoloed one -- "viewport only" is
    proven against the renderer, not inferred from which flags we set
  - toggling off restores exactly what was changed: a pre-hidden light stays
    hidden, each viewport gets its own World settings back
  - survives a rename and a save/reopen mid-solo

What is NOT under test: how the viewport actually looks. There is no viewport
render headless; the viewport depsgraph dropping the muted lights is checked
instead, and the World mute is checked as the shading values Cycles reads.
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

    # A World that clearly lights the scene, so muting it would show.
    world = scene.world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 2.0

    key = bpy.data.objects["Light"]
    key.data.energy = 1000

    def add_light(name, kind, location, energy):
        data = bpy.data.lights.new(name, kind)
        data.energy = energy
        obj = bpy.data.objects.new(name, data)
        obj.location = location
        scene.collection.objects.link(obj)
        return obj

    fill = add_light("Fill", 'AREA', (-4, -2, 3), 800)
    rim = add_light("Rim", 'SPOT', (0, 4, 4), 1500)
    already_hidden = add_light("AlreadyHidden", 'POINT', (2, 2, 2), 500)
    already_hidden.hide_set(True)

    # One viewport with non-default World settings, to prove each viewport
    # gets its OWN values back rather than a blanket default.
    spaces = [a.spaces.active for s in bpy.data.screens for a in s.areas
              if a.type == 'VIEW_3D']
    spaces[0].shading.use_scene_world_render = False
    spaces[0].shading.studiolight_intensity = 0.7

    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    key.select_set(True)
    bpy.context.view_layer.objects.active = key
    return key, fill, rim, already_hidden


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


# --- 1. Solo on ---------------------------------------------------------------

print("\n=== solo on ===")
key, fill, rim, already_hidden = build_scene()
scene = bpy.context.scene
world_strength = scene.world.node_tree.nodes["Background"].inputs["Strength"]
shading_before = view3d_shading()
render_flags_before = {o.name: o.hide_render for o in scene.objects}

baseline = render_pixels("baseline")

result = bpy.ops.lightgroup.solo_light()
check(result == {'FINISHED'}, "solo on returned %s" % result)
settings = scene.lightgroup_solo
check(settings.active, "solo not marked active")

check(key.visible_get(), "the soloed light was hidden")
check(not fill.visible_get(), "Fill still visible during solo")
check(not rim.visible_get(), "Rim still visible during solo")
check(sorted(r.obj.name for r in settings.muted) == ["Fill", "Rim"],
      "muted list is %s; a pre-hidden light must not be recorded"
      % sorted(r.obj.name for r in settings.muted))
check(all(shading == (False, 0.0) for shading in view3d_shading()),
      "a 3D viewport still has the World on: %s" % view3d_shading())
check(world_strength.default_value == 2.0,
      "World Strength was edited (%s)" % world_strength.default_value)
check({o.name: o.hide_render for o in scene.objects} == render_flags_before,
      "hide_render changed during solo")

# The viewport depsgraph is what the rendered viewport draws from.
viewport_objects = {o.name for o in bpy.context.evaluated_depsgraph_get().objects}
check("Light" in viewport_objects, "soloed light missing from viewport depsgraph")
check("Fill" not in viewport_objects and "Rim" not in viewport_objects,
      "muted lights still in the viewport depsgraph")

# --- 2. F12 is untouched ------------------------------------------------------

print("=== F12 render during solo ===")
soloed = render_pixels("soloed")
check(soloed == baseline,
      "F12 render changed during solo (mean %.5f vs %.5f) -- solo leaked "
      "into the render" % (mean(soloed), mean(baseline)))

# Sensitivity check: really removing Fill and Rim from the render must change
# the image, or the comparison above proves nothing.
fill.hide_render = rim.hide_render = True
really_off = render_pixels("really_off")
fill.hide_render = rim.hide_render = False
check(abs(mean(really_off) - mean(baseline)) > 1e-3,
      "render comparison is insensitive (%.5f vs %.5f)"
      % (mean(really_off), mean(baseline)))

# --- 3. Rename mid-solo, then off --------------------------------------------

print("=== solo off ===")
fill.name = "Fill_renamed"
result = bpy.ops.lightgroup.solo_light()
check(result == {'FINISHED'}, "solo off returned %s" % result)
check(not settings.active, "solo still active after toggling off")
check(fill.visible_get(), "light renamed mid-solo was left hidden")
check(rim.visible_get(), "Rim left hidden after solo off")
check(not already_hidden.visible_get(), "pre-hidden light was unhidden")
check(view3d_shading() == shading_before,
      "viewport World settings not restored: %s vs %s"
      % (view3d_shading(), shading_before))
check(len(settings.muted) == 0 and len(settings.spaces) == 0,
      "solo state not cleared")

# --- 4. Nothing selected ------------------------------------------------------

print("=== nothing selected ===")
for obj in bpy.context.view_layer.objects:
    obj.select_set(False)
bpy.data.objects["Cube"].select_set(True)  # a non-light selection
try:
    result = bpy.ops.lightgroup.solo_light()
except RuntimeError:
    result = {'CANCELLED'}  # the ERROR report raises in background mode
check(result == {'CANCELLED'}, "solo with no light selected returned %s" % result)
check(not settings.active, "solo went active with no light selected")
check(rim.visible_get() and fill.visible_get(),
      "a failed solo hid lights anyway")

# --- 5. Save and reopen mid-solo ---------------------------------------------

print("=== save / reopen mid-solo ===")
rim.select_set(True)
bpy.ops.lightgroup.solo_light()
path = os.path.join(TMP, "mid_solo.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
bpy.ops.wm.open_mainfile(filepath=path)
scene = bpy.context.scene
check(scene.lightgroup_solo.active, "solo state lost on reopen")
check(not bpy.data.objects["Light"].visible_get(), "muted light visible after reopen")
bpy.ops.lightgroup.solo_light()
check(bpy.data.objects["Light"].visible_get() and bpy.data.objects["Fill_renamed"].visible_get(),
      "unsolo after reopen did not restore the lights")
check(not bpy.data.objects["AlreadyHidden"].visible_get(),
      "pre-hidden light unhidden after reopen")


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
