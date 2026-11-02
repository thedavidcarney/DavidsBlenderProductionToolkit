"""Headless tests for the single-EXR denoise setup (lightgroups/operators.py)
and the post-render output check (lightgroups/output_check.py).

Run via tests/run_single_exr_test.sh, never directly against a real install.

What is under test, on 5.2+:
  - one animation frame writes one EXR, and only that, into 01_Components
  - the layers: lightgroups first, then Image, then the rest; no Alpha, no
    Denoising passes, every item still RGBA (see setup_single_exr for why)
  - against a lossless render output from the SAME render: Crypto is bit-exact
    and Image.A is exact, even denoised
  - Image gets a Denoise node unless scene AND view layer render denoising are on
  - clicking twice doesn't duplicate anything
  - the output check passes a good file, and catches a missing, stale, cut-off
    or short file, proven on real render files

On 5.0/5.1 only the two-file setup is pinned, plus the output check.

The Group Output and the panel can't be seen headless; check those in a GUI run.
"""

import atexit
import glob
import os
import shutil
import struct
import sys
import tempfile
import time

import bpy

ADDON = "lightgroup_tools"
SINGLE_EXR = bpy.app.version >= (5, 2, 0)

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


TMP = tempfile.mkdtemp(prefix="single_exr_test_")
LIGHTGROUPS = ["Key", "World", "Sphere"]


def build_scene(job, render_denoise=False):
    """A scene saved as <TMP>/<job>/scenes/shot/LGT.blend, with the button run."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    # read_factory_settings resets preferences too, which disables the addon.
    bpy.ops.preferences.addon_enable(module=ADDON)

    scene = bpy.context.scene
    layer = bpy.context.view_layer
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)

    bpy.ops.mesh.primitive_plane_add(size=20)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(-2, 0, 1))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(2, 0, 1))
    sphere = bpy.context.object
    sphere.name = "Sphere"
    material = bpy.data.materials.new("Glow")
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Emission Color"].default_value = (1, 0.3, 0.1, 1)
    bsdf.inputs["Emission Strength"].default_value = 8
    sphere.data.materials.append(material)
    bpy.ops.object.light_add(type='AREA', location=(0, -2, 6))
    bpy.context.object.name = "Key"
    bpy.context.object.data.energy = 800
    bpy.ops.object.camera_add(location=(0, -9, 4), rotation=(1.2, 0, 0))
    scene.camera = bpy.context.object

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.3, 0.4, 0.6, 1)
    scene.world = world

    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.cycles.use_denoising = render_denoise
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Filmic'
    scene.frame_start = 1
    scene.frame_end = 2
    scene.render.filepath = "//renderout_"

    layer.use_pass_z = True
    layer.use_pass_mist = True
    layer.use_pass_normal = True
    layer.use_pass_cryptomatte_object = True
    layer.use_pass_cryptomatte_material = True
    layer.cycles.denoising_store_passes = True

    path = os.path.join(TMP, job, "scenes", "shot", "LGT.blend")
    os.makedirs(os.path.dirname(path))
    bpy.ops.lightgroup.create_for_each_light()
    bpy.ops.lightgroup.denoise_all_cycles()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return scene, os.path.join(TMP, job)


def file_output(scene):
    nodes = [n for n in scene.compositing_node_group.nodes
             if n.bl_idname == 'CompositorNodeOutputFile']
    check(len(nodes) == 1, "%d File Output nodes, expected 1" % len(nodes))
    return nodes[0]


def exrs_under(root):
    return sorted(os.path.relpath(p, root).replace("\\", "/")
                  for p in glob.glob(root + "/**/*.exr", recursive=True))


def read_layers(path):
    import OpenImageIO as oiio
    image = oiio.ImageInput.open(path)
    layers = {}
    part = 0
    while image.seek_subimage(part, 0):
        spec = image.spec()
        layers[spec.get_string_attribute("name")] = image.read_image(
            part, 0, 0, spec.nchannels, oiio.FLOAT)
        part += 1
    image.close()
    return layers


def test_layers_and_files():
    scene, job = build_scene("layers")
    node = file_output(scene)
    names = [item.name for item in node.file_output_items]

    check(names[:4] == LIGHTGROUPS + ["Image"],
          "lightgroups then Image must come first, got %s" % names[:4])
    for name in ("Depth", "Mist", "Normal", "CryptoObject00", "CryptoMaterial00"):
        check(name in names, "%s is missing from the File Output" % name)
    for name in names:
        check(name != "Alpha" and name != "Noisy Image" and not name.startswith("Denoising "),
              "%s must not be in the File Output" % name)
    # EXRDemux reads R/G/B/A only. If this changes, EXRDemux has to change first.
    for item in node.file_output_items:
        check(item.socket_type == 'RGBA', "%s is %s, not RGBA" % (item.name, item.socket_type))

    check(not scene.render.save_output, "render output was left on")
    check(scene.render.use_compositing, "compositing was left off")
    fmt = node.format
    check(fmt.file_format == 'OPEN_EXR_MULTILAYER', "format %s" % fmt.file_format)
    check(fmt.color_depth == '16', "depth %s" % fmt.color_depth)
    check(fmt.exr_codec == 'DWAB', "codec %s" % fmt.exr_codec)
    check(fmt.quality == 15, "quality %s" % fmt.quality)
    check(fmt.linear_colorspace_settings.name == 'Filmic sRGB',
          "colour space %s" % fmt.linear_colorspace_settings.name)

    # Second click rebuilds rather than adds.
    tree = scene.compositing_node_group
    before = len(tree.nodes)
    sockets = len(tree.interface.items_tree)
    bpy.ops.lightgroup.denoise_all_cycles()
    check(len(tree.nodes) == before, "second click: %d nodes, was %d" % (len(tree.nodes), before))
    check(len(tree.interface.items_tree) == sockets, "second click added a group socket")
    group_outputs = [n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput']
    check(len(group_outputs) == 1 and group_outputs[0].inputs[0].is_linked,
          "the beauty isn't wired to one Group Output")

    bpy.ops.wm.save_mainfile()
    bpy.ops.render.render(animation=True)
    found = exrs_under(job)
    expected = ["04_Renders/01_Components/LGT_0001.exr", "04_Renders/01_Components/LGT_0002.exr"]
    check(found == expected, "wrote %s, expected only %s" % (found, expected))

    layers = read_layers(os.path.join(job, expected[0]))
    check(list(layers) == names, "parts %s don't match items %s" % (list(layers), names))
    check(layers["Key"].shape[2] == 4, "lightgroup layer isn't RGBA")

    # A plain F12 and a saved still must not raise a false alarm.
    output_check = sys.modules[ADDON].lightgroups.output_check
    check(output_check.problems()[1] == 0, "good animation: %s" % (output_check.problems(),))
    scene.frame_set(1)
    bpy.ops.render.render()
    check(output_check.problems()[1] == 0, "plain F12: %s" % (output_check.problems(),))
    bpy.ops.render.render(write_still=True)
    check(output_check.problems()[1] == 0, "saved still: %s" % (output_check.problems(),))
    print("NOTE: after stills, files are", exrs_under(job))


def test_data_against_lossless():
    """Same render written twice, so differences can only come from the File Output."""
    scene, job = build_scene("lossless")
    settings = scene.render.image_settings
    settings.media_type = 'MULTI_LAYER_IMAGE'
    settings.file_format = 'OPEN_EXR_MULTILAYER'
    settings.color_depth = '32'
    settings.exr_codec = 'ZIP'
    scene.render.save_output = True
    scene.frame_end = 1
    bpy.ops.wm.save_mainfile()
    bpy.ops.render.render(animation=True)

    written = read_layers(os.path.join(job, "04_Renders", "01_Components", "LGT_0001.exr"))
    truth = read_layers(os.path.join(job, "scenes", "shot", "renderout_0001.exr"))
    for name in written:
        if name.startswith("Crypto"):
            differing = int((written[name] != truth["ViewLayer." + name]).any(axis=2).sum())
            check(differing == 0, "%s: %d pixels differ from lossless" % (name, differing))
    worst = abs(written["Image"][..., 3] - truth["ViewLayer.Combined"][..., 3]).max()
    check(worst == 0.0, "denoised Image.A differs from the render's alpha by %s" % worst)


def image_is_denoised(scene):
    node = file_output(scene)
    index = [item.name for item in node.file_output_items].index("Image")
    return node.inputs[index].links[0].from_node.bl_idname == 'CompositorNodeDenoise'


def test_beauty_denoising():
    scene, _job = build_scene("denoise_off")
    check(image_is_denoised(scene), "render denoising off: Image wasn't denoised")

    scene, _job = build_scene("denoise_on", render_denoise=True)
    check(not image_is_denoised(scene), "render denoising on: Image was denoised twice")

    bpy.context.view_layer.cycles.use_denoising = False
    bpy.ops.lightgroup.denoise_all_cycles()
    check(image_is_denoised(scene), "view layer denoising off: Image wasn't denoised")


def test_output_check():
    package = sys.modules[ADDON]
    output_check = package.lightgroups.output_check

    scene, job = build_scene("check")
    if not SINGLE_EXR:
        scene.render.filepath = os.path.join(job, "scenes", "shot", "renderout_")
    scene.frame_end = 1
    bpy.ops.wm.save_mainfile()
    bpy.ops.render.render(animation=True)
    scene.frame_set(1)

    path = os.path.join(job, "04_Renders", "01_Components", "LGT_0001.exr")
    good = open(path, "rb").read()
    node = file_output(scene)
    expected_parts = sum(1 for s in node.inputs if s.is_linked)

    parts, problem = output_check.read_exr_parts(path)
    check(parts == expected_parts, "read %s parts, expected %d" % (parts, expected_parts))
    check(problem is None, "good file reported as: %s" % problem)
    check(output_check.problems()[1] == 0, "a good render reported %s" % (output_check.problems(),))
    check(output_check.check_scene(scene) == [], "good file failed the check")

    def lines_for(data):
        with open(path, "wb") as handle:
            handle.write(data)
        return output_check.check_scene(scene)

    # What running out of memory actually leaves behind.
    for keep in (0.5, 0.02):
        found = lines_for(good[:int(len(good) * keep)])
        check(len(found) == 1 and "cut off" in found[0],
              "kept %d%% of the file: %s" % (keep * 100, found))
    check(len(lines_for(b"not an exr at all")) == 1, "garbage file passed")

    # Every part present and the right size, but the offset table never filled in.
    with open(path, "wb") as handle:
        handle.write(good)
    table_start = _offset_table_start(good)
    blanked = good[:table_start] + b"\0" * 8 + good[table_start + 8:]
    found = lines_for(blanked)
    check(len(found) == 1 and "cut off" in found[0], "blank offset passed: %s" % found)

    with open(path, "wb") as handle:
        handle.write(good)
    # A leftover from an earlier render must not pass for this frame's output.
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    found = output_check.check_scene(scene, since=time.time() - 60)
    check(len(found) == 1 and "not written" in found[0], "stale file passed: %s" % found)

    os.remove(path)
    found = output_check.check_scene(scene)
    check(len(found) == 1 and "not written" in found[0], "missing file passed: %s" % found)

    # Fewer layers on disk than the node asks for.
    with open(path, "wb") as handle:
        handle.write(good)
    node.file_output_items.new('RGBA', name="Extra")
    scene.compositing_node_group.links.new(
        [n for n in scene.compositing_node_group.nodes
         if n.bl_idname == 'CompositorNodeRLayers'][0].outputs["Image"], node.inputs[-1])
    found = output_check.check_scene(scene)
    check(len(found) == 1 and "layers" in found[0], "short file passed: %s" % found)

    # A real render through the handlers, with the file blocked from being written.
    node.mute = False
    os.remove(path)
    os.rmdir(os.path.dirname(path))
    with open(os.path.dirname(path), "w") as handle:
        handle.write("a file where the folder should be")
    bpy.ops.render.render(animation=True)
    shown, total = output_check.problems()
    check(total == 1 and "not written" in shown[0],
          "unwritable output wasn't reported: %s" % (shown,))

    # Nothing to check, nothing to report.
    node.mute = True
    check(output_check.check_scene(scene) == [], "a muted node was checked")


def _offset_table_start(data):
    """Where a multi-part EXR's offset tables begin: after the empty last header."""
    position = 8
    while data[position] != 0:
        while data[position] != 0:
            position = data.index(b"\0", position) + 1  # attribute name
            position = data.index(b"\0", position) + 1  # attribute type
            position += 4 + struct.unpack("<i", data[position:position + 4])[0]
        position += 1
    return position + 1


def test_older_setup_kept():
    scene, job = build_scene("legacy")
    names = [item.name for item in file_output(scene).file_output_items]
    check("Alpha" in names, "5.0/5.1 must keep the original setup, got %s" % names)
    check(not hasattr(scene.render, "save_output"), "save_output exists here after all")


if SINGLE_EXR:
    test_layers_and_files()
    test_data_against_lossless()
    test_beauty_denoising()
else:
    test_older_setup_kept()
    print("NOTE: single-EXR tests skipped; this Blender keeps the two-file setup")
test_output_check()

shutil.rmtree(TMP, ignore_errors=True)

_VERDICT_REACHED.append(True)
if FAILURES:
    print("SINGLE EXR TEST FAILED")
    for failure in FAILURES:
        print("  - " + failure)
    sys.stdout.flush()
    os._exit(1)
print("SINGLE EXR TEST PASSED")
