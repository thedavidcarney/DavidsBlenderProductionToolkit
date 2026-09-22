"""
Headless tests for the Camera Overlay tool.

Run with tests/run_camera_overlay_test.sh, which sandboxes the scripts dir.

Why this can test the GPU at all
--------------------------------
Festoon's overlay is verified by eye because a background Blender has no GL
context. That stopped being true in 5.2: `gpu.init()` brings up a real
offscreen OpenGL backend, so from 5.2 on the shader can be compiled, run, and
the resulting PIXELS read back and checked. On 4.5/5.0/5.1 there is no
`gpu.init`, so the GPU phases are skipped and the maths and lifecycle phases
still run.

That matters here because the bug this tool exists to avoid -- a reference
image that silently never appears -- is precisely a "the geometry was right
but nothing was drawn" bug. Checking the pixels is the only test that would
have caught it.
"""

import ast
import atexit
import os
import sys

import bpy
import gpu

ADDON = "lightgroup_tools"

FAILURES = []
NOTES = []

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


def close(a, b, tolerance, message):
    return check(abs(a - b) <= tolerance,
                 "%s (got %.4f, expected %.4f +/- %.4f)"
                 % (message, a, b, tolerance))


# --- Setup ------------------------------------------------------------------

bpy.ops.preferences.addon_enable(module=ADDON)

# Stop the updater's load_post handler from phoning GitHub.
for name, module in list(sys.modules.items()):
    if module is not None and hasattr(module, "install_update_on_load"):
        module._auto_check_done_this_session = True

overlay = sys.modules[ADDON + ".camera_overlay.overlay"]

scene = bpy.context.scene
props = scene.cam_overlay


class FakeProps:
    """Stand-in for the PropertyGroup, so quad() can be tested directly.

    Cheaper and clearer than round-tripping every case through a real scene,
    and quad() only ever reads these attributes.
    """

    def __init__(self, **kwargs):
        self.fit = 'FIT'
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.rotation = 0.0
        self.flip_x = False
        self.flip_y = False
        self.__dict__.update(kwargs)


# --- Phase 1: properties ----------------------------------------------------

print("=== phase 1: properties ===")

# The decision the whole tool rests on. A StringProperty here would bring back
# relative-path breakage, packing breakage and the format allow-list.
image_prop = type(props).bl_rna.properties["image"]
check(image_prop.type == 'POINTER',
      "[props] cam_overlay.image must be a PointerProperty, got "
      + image_prop.type)
check(getattr(image_prop, "fixed_type", None) is not None
      and image_prop.fixed_type.identifier == "Image",
      "[props] cam_overlay.image must point at an Image datablock")

close(props.opacity, 0.5, 1e-6, "[props] opacity default")
check(props.mode == 'NORMAL', "[props] mode default should be NORMAL")
check(props.fit == 'FIT', "[props] fit default should be FIT")
check(props.enabled is False, "[props] enabled should default off")

# Nothing in the addon may read image.pixels, at any resolution. Walking the
# AST rather than grepping the text, so the comments in overlay.py explaining
# why we never touch pixels do not themselves trip the check.
source_root = os.path.dirname(overlay.__file__)
for filename in sorted(os.listdir(source_root)):
    if not filename.endswith(".py"):
        continue
    path = os.path.join(source_root, filename)
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=filename)
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute) and node.attr == "pixels"]
    check(not offenders,
          "[props] " + filename + " reads .pixels at line(s) "
          + ", ".join(str(n) for n in offenders)
          + " -- an 8K image is over a gigabyte of Python floats and raises"
            " MemoryError, which a broad except turns into a blank frame")


# --- Phase 2: quad maths ----------------------------------------------------

print("=== phase 2: quad geometry ===")

# A 200x100 frame: twice as wide as it is tall.
RECT = (0.0, 0.0, 200.0, 100.0)


def extents(positions):
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return max(xs) - min(xs), max(ys) - min(ys)


# A square image into a 2:1 frame.
positions, uvs = overlay.quad(FakeProps(fit='FIT'), RECT, 100, 100)
width, height = extents(positions)
close(height, 100.0, 1e-4, "[fit] a square image should fill the frame height")
close(width, 100.0, 1e-4, "[fit] ...and stay square, not stretch to the width")

positions, _ = overlay.quad(FakeProps(fit='FILL'), RECT, 100, 100)
width, height = extents(positions)
close(width, 200.0, 1e-4, "[fill] should cover the frame width")
close(height, 200.0, 1e-4, "[fill] ...overflowing vertically, still square")

positions, _ = overlay.quad(FakeProps(fit='STRETCH'), RECT, 100, 100)
width, height = extents(positions)
close(width, 200.0, 1e-4, "[stretch] should match frame width")
close(height, 100.0, 1e-4, "[stretch] should match frame height")

# A wide image into the same frame takes the other branch of each fit.
positions, _ = overlay.quad(FakeProps(fit='FIT'), RECT, 400, 100)
width, height = extents(positions)
close(width, 200.0, 1e-4, "[fit] a wide image should fill the frame width")
close(height, 50.0, 1e-4, "[fit] ...and letterbox vertically")

# Scale multiplies the fitted size.
positions, _ = overlay.quad(FakeProps(fit='FIT', scale=2.0), RECT, 100, 100)
width, height = extents(positions)
close(height, 200.0, 1e-4, "[scale] 2.0 should double the fitted height")

# Offsets are a fraction of the FRAME, so 0.5 on a 200-wide frame is 100px.
base, _ = overlay.quad(FakeProps(), RECT, 100, 100)
shifted, _ = overlay.quad(FakeProps(offset_x=0.5), RECT, 100, 100)
close(shifted[0][0] - base[0][0], 100.0, 1e-4,
      "[offset] offset_x 0.5 should move by half the frame width")

# Centre must not move when only the rotation changes.
straight, _ = overlay.quad(FakeProps(), RECT, 100, 100)
turned, _ = overlay.quad(FakeProps(rotation=0.7), RECT, 100, 100)


def centre(positions):
    return (sum(p[0] for p in positions) / 4.0,
            sum(p[1] for p in positions) / 4.0)


straight_centre = centre(straight)
turned_centre = centre(turned)
close(turned_centre[0], straight_centre[0], 1e-4,
      "[rotation] must not move the centre in x")
close(turned_centre[1], straight_centre[1], 1e-4,
      "[rotation] must not move the centre in y")

# A quarter turn of a square swaps nothing, so check a real rotation instead:
# 90 degrees on a 2:1 image should swap its extents.
turned, _ = overlay.quad(FakeProps(fit='FIT', rotation=1.5707963),
                         RECT, 400, 100)
width, height = extents(turned)
close(width, 50.0, 1e-3, "[rotation] 90deg should swap the width")
close(height, 200.0, 1e-3, "[rotation] 90deg should swap the height")

# Flip flags swap the UVs, never the positions.
_, plain_uvs = overlay.quad(FakeProps(), RECT, 100, 100)
_, flipped_uvs = overlay.quad(FakeProps(flip_x=True), RECT, 100, 100)
check(plain_uvs[0][0] != flipped_uvs[0][0],
      "[flip] flip_x should change the U coordinate")
_, flipped_uvs = overlay.quad(FakeProps(flip_y=True), RECT, 100, 100)
check(plain_uvs[0][1] != flipped_uvs[0][1],
      "[flip] flip_y should change the V coordinate")

# A degenerate frame must return None rather than divide by zero.
check(overlay.quad(FakeProps(), (0.0, 0.0, 0.0, 0.0), 100, 100) is None,
      "[guard] a zero-area frame should return None")
check(overlay.quad(FakeProps(), RECT, 0, 0) is None,
      "[guard] a zero-size image should return None")


# --- Phase 3: handler lifecycle --------------------------------------------

print("=== phase 3: handler lifecycle ===")

check(not overlay.handler_registered(),
      "[lifecycle] handler should not be registered before enabling")

# The acceptance checklist asks for 20 toggles with no leak. The handler lives
# in a module global precisely so this cannot stack.
for _ in range(20):
    props.enabled = True
    props.enabled = False

check(not overlay.handler_registered(),
      "[lifecycle] handler leaked after 20 enable/disable cycles")

props.enabled = True
check(overlay.handler_registered(),
      "[lifecycle] handler should be registered while enabled")

# Enabling twice must not add a second handler. If it did, disable would
# remove one and leave the other drawing forever.
overlay.enable_handler()
overlay.disable_handler()
check(not overlay.handler_registered(),
      "[lifecycle] a double enable_handler() stacked a second handler")

props.enabled = False
overlay.shutdown()
check(not overlay.handler_registered(),
      "[lifecycle] shutdown() left the handler registered")


# --- Phase 4: status --------------------------------------------------------

print("=== phase 4: status reporting ===")

overlay.clear_status()
check(overlay.get_status() == "",
      "[status] empty means healthy")
overlay.set_status("something went wrong")
check(overlay.get_status() == "something went wrong",
      "[status] set_status should be readable by the panel")
overlay.clear_status()

# "Nothing may swallow a failure silently" was once checked by scanning the
# source for a bare `pass` after `def draw(`. That was both brittle and wrong:
# the draw guard legitimately contains one, restoring GPU state best-effort on
# the error path, where a second exception would be worse than useless.
# Phase 4b replaces it by actually making draw() fail and asserting a status
# comes back -- the behaviour itself rather than a proxy for it.


# --- Phase 4b: the draw handler must never raise ----------------------------

print("=== phase 4b: draw handler containment ===")

# A draw handler that throws does so on EVERY redraw: console spam, a
# stuttering viewport, and GPU state possibly left as we set it. Whatever goes
# wrong inside, nothing may escape into Blender's draw loop.
original_inner = overlay._draw


def _exploding_draw():
    raise RuntimeError("simulated driver fault")


overlay._draw = _exploding_draw
overlay.enable_handler()  # clears any previous failure state
try:
    overlay.draw()
    raised = None
except Exception as exc:
    raised = exc

check(raised is None,
      "[draw guard] an exception escaped the draw handler: " + repr(raised))
check(overlay.get_status() != "",
      "[draw guard] a draw failure must leave a status for the panel")
check("simulated driver fault" in overlay.get_status(),
      "[draw guard] the status should name the underlying error, got: "
      + overlay.get_status())

# ...and it must go quiet rather than failing sixty times a second.
status_after_first = overlay.get_status()
for _ in range(5):
    overlay.draw()
check(overlay.get_status() == status_after_first,
      "[draw guard] repeated draws should stay quiet after the first failure")

# Toggling Enable is the retry, and must clear the failure.
overlay._draw = original_inner
overlay.enable_handler()
check(overlay.get_status() == "",
      "[draw guard] re-enabling should clear the failure state")
overlay.disable_handler()


# --- Phase 5: the diagnostics operator --------------------------------------

print("=== phase 5: diagnostics operator ===")

# Actually RUN it. Every line it prints is an attribute lookup on an Image, a
# gpu.platform function or a property, and a typo in any of them would only
# ever surface when somebody clicks the button -- which is the exact failure
# mode this repo has been bitten by before.
diag_image = bpy.data.images.new("diagnostics_probe", 4, 4)
props.image = diag_image
try:
    result = bpy.ops.camoverlay.diagnostics()
    check(result == {'FINISHED'},
          "[diagnostics] operator returned " + repr(result))
except Exception as exc:
    check(False, "[diagnostics] operator raised "
                 + type(exc).__name__ + ": " + str(exc))

# ...and again with no image at all, which takes the other branch.
props.image = None
try:
    result = bpy.ops.camoverlay.diagnostics()
    check(result == {'FINISHED'},
          "[diagnostics] operator returned " + repr(result) + " with no image")
except Exception as exc:
    check(False, "[diagnostics] operator raised with no image: "
                 + type(exc).__name__ + ": " + str(exc))

bpy.data.images.remove(diag_image)

# Running diagnostics must not have tried to build the shader. It did once:
# get_shader() compiles, and a failure sets a STICKY flag, so pressing the
# button before any viewport draw permanently poisoned the overlay. Reporting
# has to observe, not mutate.
check(overlay.get_status() == "",
      "[diagnostics] running diagnostics set a status ("
      + overlay.get_status() + ") -- it must not attempt a shader compile")
check("not built yet" in overlay.shader_state(),
      "[diagnostics] shader state is '" + overlay.shader_state()
      + "' after diagnostics -- the button triggered a compile")


# --- Phase 6: the GPU path (5.2+) ------------------------------------------

print("=== phase 6: shader and pixels ===")

if not hasattr(gpu, "init"):
    NOTES.append("GPU phases skipped: Blender %s has no gpu.init(), so a "
                 "background run has no GL context. Run on 5.2+ for these."
                 % bpy.app.version_string)
else:
    gpu.init()
    print("    backend:", gpu.platform.backend_type_get())

    shader = overlay.get_shader()
    if check(shader is not None,
             "[gpu] shader failed to compile: " + overlay.get_status()):

        # A known image: pure red, Non-Color so the readback is not reshaped
        # by a colour transform we are not testing here.
        image = bpy.data.images.new("overlay_test", 8, 8, alpha=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels.foreach_set([1.0, 0.0, 0.0, 1.0] * 64)
        image.update()

        texture = overlay._get_texture(image)
        check(texture is not None,
              "[gpu] could not build a texture: " + overlay.get_status())

        # Same image twice must reuse the cached handle rather than refetch.
        check(overlay._get_texture(image) is texture,
              "[gpu] texture cache missed on an unchanged image")

        from gpu_extras.batch import batch_for_shader
        from mathutils import Matrix

        def render(mode_is_mask, opacity, threshold=0.5, invert=False,
                   tint=(1.0, 1.0, 1.0), channel=0):
            """Draw the quad over black and read the centre pixel back."""
            offscreen = gpu.types.GPUOffScreen(16, 16)
            try:
                with offscreen.bind():
                    fb = gpu.state.active_framebuffer_get()
                    fb.clear(color=(0.0, 0.0, 0.0, 1.0))
                    with gpu.matrix.push_pop():
                        gpu.matrix.load_matrix(Matrix.Identity(4))
                        gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                        gpu.state.blend_set('ALPHA')
                        batch = batch_for_shader(
                            shader, 'TRIS',
                            {"pos": [(-1, -1), (1, -1), (1, 1), (-1, 1)],
                             "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]},
                            indices=[(0, 1, 2), (0, 2, 3)])
                        shader.bind()
                        shader.uniform_sampler("image", texture)
                        shader.uniform_float("opacity", opacity)
                        shader.uniform_float("threshold", threshold)
                        shader.uniform_float("tint", tint)
                        shader.uniform_int("channel", channel)
                        shader.uniform_int("invert", 1 if invert else 0)
                        shader.uniform_int("maskMode", 1 if mode_is_mask else 0)
                        batch.draw(shader)
                        gpu.state.blend_set('NONE')
                    buffer = fb.read_color(8, 8, 1, 1, 4, 0, 'FLOAT')
                return tuple(buffer.to_list()[0][0])
            finally:
                offscreen.free()

        # NORMAL at full opacity: the image, unchanged.
        pixel = render(False, 1.0)
        close(pixel[0], 1.0, 0.02, "[gpu] normal/opaque red channel")
        close(pixel[1], 0.0, 0.02, "[gpu] normal/opaque green channel")

        # NORMAL at half opacity over black: half-strength red. This is the
        # one behaviour the tool actually gets used for.
        pixel = render(False, 0.5)
        close(pixel[0], 0.5, 0.02, "[gpu] opacity 0.5 should halve the red")
        close(pixel[1], 0.0, 0.02, "[gpu] opacity 0.5 should leave green at 0")

        pixel = render(False, 0.0)
        close(pixel[0], 0.0, 0.02, "[gpu] opacity 0 should draw nothing")

        # MASK: luminance of pure red is 0.299, so a 0.2 threshold passes it
        # and a 0.5 threshold rejects it.
        luminance = 0.299
        pixel = render(True, 1.0, threshold=0.2)
        close(pixel[0], luminance, 0.02,
              "[gpu] mask above threshold should show tint * intensity")
        pixel = render(True, 1.0, threshold=0.5)
        close(pixel[0], 0.0, 0.02,
              "[gpu] mask below threshold should draw nothing")

        # Invert flips which side of the threshold survives.
        pixel = render(True, 1.0, threshold=0.5, invert=True)
        close(pixel[0], 1.0 - luminance, 0.02,
              "[gpu] inverted mask should show 1 - intensity")

        # Channel selection: the red channel of pure red is 1.0.
        pixel = render(True, 1.0, threshold=0.5, channel=1)
        close(pixel[0], 1.0, 0.02, "[gpu] channel R should read 1.0")
        # ...and the green channel is 0, which falls below the threshold.
        pixel = render(True, 1.0, threshold=0.5, channel=2)
        close(pixel[0], 0.0, 0.02, "[gpu] channel G should be below threshold")

        # Tint colours the mask.
        pixel = render(True, 1.0, threshold=0.2, tint=(0.0, 1.0, 0.0))
        close(pixel[1], luminance, 0.02, "[gpu] tint should colour the mask")
        close(pixel[0], 0.0, 0.02, "[gpu] tint should suppress other channels")

        # A large image must cost nothing to set up, because we never read its
        # pixels. 4K here rather than 8K to keep the test's own memory sane --
        # the Python-pixel-read failure mode would already be fatal at 4K.
        import time

        big = bpy.data.images.new("overlay_big", 4096, 4096)
        big.colorspace_settings.name = 'Non-Color'
        overlay.clear_cache()
        started = time.time()
        big_texture = overlay._get_texture(big)
        elapsed = time.time() - started
        check(big_texture is not None, "[gpu] 4K image produced no texture")
        check(elapsed < 5.0,
              "[gpu] 4K texture setup took %.1fs -- something is reading "
              "pixels in Python" % elapsed)
        print("    4K texture setup: %.3fs" % elapsed)

        overlay.clear_cache()
        bpy.data.images.remove(big)
        bpy.data.images.remove(image)

    overlay.shutdown()


# --- Verdict ----------------------------------------------------------------

print()
print("=" * 60)
for note in NOTES:
    print("  NOTE  " + note)
if FAILURES:
    print("CAMERA OVERLAY TEST: FAILED (%d problem(s))" % len(FAILURES))
    for failure in FAILURES:
        print("  FAIL  " + failure)
    print("=" * 60)
    _VERDICT_REACHED.append(True)
    sys.stdout.flush()
    os._exit(1)

print("CAMERA OVERLAY TEST: PASSED")
print("=" * 60)
_VERDICT_REACHED.append(True)
sys.stdout.flush()
os._exit(0)
