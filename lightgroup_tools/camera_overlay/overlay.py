"""GPU drawing for the camera reference overlay.

Everything that touches the GPU lives here: the shader, the texture cache, the
draw handler, and the status string the panel reads back.

Three rules shape this module, each one a bug in the commercial addon this
replaces:

1. The image is an Image DATABLOCK, never a path string. Blender resolves
   relative paths, packing and reloads for us, so there is no existence check
   to get wrong and no format allow-list to fall out of date.
2. Nothing here ever reads `image.pixels`. A 4K RGBA image is ~33M Python
   floats; 8K raises MemoryError, which a broad `except` then turns into a
   silent blank frame. All per-pixel work happens in the fragment shader, so
   loading is instant at any resolution.
3. Every bail-out sets `_status`, which the panel renders in red. A failure
   that produces no output anywhere is a failure nobody can report.
"""

import math

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

# Module state. The handler lives in a global so `enabled` can toggle it
# without double-registering, and so unregister() can always find it again.
_handle = None
_shader = None
_shader_failed = False
_texture = None
_texture_key = None
_status = ""
# Set when the draw handler has thrown. Sticky, so one bad frame does not
# become an error every redraw; cleared by toggling Enable.
_draw_failed = False


# --- Status -----------------------------------------------------------------
#
# "" means healthy. Anything else is drawn in the panel with an ERROR icon.

def get_status():
    return _status


def set_status(message):
    global _status
    _status = message


def clear_status():
    global _status
    _status = ""


# --- Shader -----------------------------------------------------------------

_VERTEX_SOURCE = """
void main()
{
  gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
  uvInterp = texCoord;
}
"""

# One shader serves both modes. The mask branch is a per-pixel operation and
# belongs here rather than in a Python pixel loop.
# `maskMode` and `invert` are INT, not BOOL, on purpose. A bool inside a
# push-constant block has genuinely ambiguous size (1 byte or 4 depending on
# the layout rules applied), and Metal emulates push constants differently
# again -- and Metal is the one backend that cannot be tested from here.
# An int is 4 bytes with well-defined layout on OpenGL, Vulkan and Metal
# alike, and `uniform_int` has none of `uniform_bool`'s scalar-vs-sequence
# arity history. Same behaviour, one less untestable assumption.
_FRAGMENT_SOURCE = """
void main()
{
  vec4 t = texture(image, uvInterp);
  if (maskMode == 0) {
    fragColor = vec4(t.rgb, t.a * opacity);
  } else {
    float v = channel == 0 ? dot(t.rgb, vec3(0.299, 0.587, 0.114))
            : channel == 1 ? t.r
            : channel == 2 ? t.g
            : channel == 3 ? t.b
            : t.a;
    bool inverted = invert != 0;
    bool vis = inverted ? (v < threshold) : (v > threshold);
    float intensity = inverted ? (1.0 - v) : v;
    fragColor = vis ? vec4(tint * intensity, opacity) : vec4(0.0);
  }
}
"""


def get_shader():
    """Build the shader on first draw and keep it.

    Deliberately lazy: register() has no guaranteed GPU context, so compiling
    there would fail on startup. `GPUShaderCreateInfo` is used unconditionally
    -- it is correct on OpenGL, Vulkan and Metal from 4.5 on, so there is no
    backend sniffing to get wrong. A failed compile is sticky (we do not retry
    every redraw) and visible in the panel.
    """
    global _shader, _shader_failed

    if _shader is not None or _shader_failed:
        return _shader

    try:
        interface = gpu.types.GPUStageInterfaceInfo("camera_overlay_interface")
        interface.smooth('VEC2', "uvInterp")

        info = gpu.types.GPUShaderCreateInfo()
        info.push_constant('MAT4', "ModelViewProjectionMatrix")
        info.push_constant('FLOAT', "opacity")
        info.push_constant('FLOAT', "threshold")
        info.push_constant('VEC3', "tint")
        info.push_constant('INT', "channel")
        info.push_constant('INT', "invert")
        info.push_constant('INT', "maskMode")
        info.sampler(0, 'FLOAT_2D', "image")
        info.vertex_in(0, 'VEC2', "pos")
        info.vertex_in(1, 'VEC2', "texCoord")
        info.vertex_out(interface)
        info.fragment_out(0, 'VEC4', "fragColor")
        info.vertex_source(_VERTEX_SOURCE)
        info.fragment_source(_FRAGMENT_SOURCE)

        _shader = gpu.shader.create_from_info(info)
    except Exception as exc:
        _shader_failed = True
        set_status("Shader compile failed: %s" % exc)
        return None

    return _shader


def shader_state():
    """Describe the shader WITHOUT building it.

    Diagnostics has to observe, never mutate. Calling `get_shader` from the
    diagnostics button would attempt a compile in whatever context the button
    happened to be pressed in, and a failure there sets the sticky
    `_shader_failed` flag -- so the button could cause the very fault it is
    meant to report, and poison every later draw.
    """
    if _shader is not None:
        return "built"
    if _shader_failed:
        return "compile FAILED"
    return "not built yet (builds on first draw)"


def _drop_shader():
    global _shader, _shader_failed
    _shader = None
    _shader_failed = False


# --- Texture ----------------------------------------------------------------

def _get_texture(image):
    """Fetch the GPUTexture for an image, cached on the datablock identity.

    `gpu.texture.from_image` hands back Blender's OWN cached texture for that
    image -- calling it twice on one image returns the same object -- and the
    memory is shared with Blender rather than owned by us.

    Which is why nothing here calls `texture.free()`: GPUTexture has no `free`
    method on 4.5, 5.0, 5.1 or 5.2 (checked on all four), so that call would
    raise AttributeError. Invalidation is done by dropping our reference and
    letting Blender manage the buffer it owns. What we must not do is hold a
    reference across a file load, which is what `clear_cache` is for.

    We also never remove the image datablock. The original addon built a
    texture, deleted the datablock on the next line, then reused that texture
    for every later redraw -- the texture points at the image's GPU buffer, so
    whether that shows pixels or a blank quad is driver-dependent. Here the
    user owns the datablock and we only borrow it.
    """
    global _texture, _texture_key

    # `is_dirty` means the pixels changed under us (painted, reloaded), so the
    # cached handle has to be re-fetched rather than trusted.
    key = (image.as_pointer(), image.name_full)
    if _texture is not None and _texture_key == key and not image.is_dirty:
        return _texture

    try:
        _texture = gpu.texture.from_image(image)
    except Exception as exc:
        _texture = None
        _texture_key = None
        set_status("Could not create texture from '%s': %s" % (image.name, exc))
        return None

    _texture_key = key
    return _texture


def clear_cache():
    """Drop the cached texture. Called on file load and at unregister."""
    global _texture, _texture_key
    _texture = None
    _texture_key = None


# --- Geometry ---------------------------------------------------------------

def camera_frame_rect(context):
    """The camera border in region pixels, as (x0, y0, x1, y1).

    Taken from the CAMERA rather than from the region: `view_frame` gives the
    true framing including passepartout, and projecting it through the region
    keeps it correct under any zoom, region size or UI scale. Hand-rolled
    region maths is exactly where UI-scale bugs come from.

    Returns None if the camera is missing or any corner fails to project.
    """
    scene = context.scene
    camera = scene.camera
    if camera is None or camera.type != 'CAMERA':
        return None

    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None

    corners = [camera.matrix_world @ corner
               for corner in camera.data.view_frame(scene=scene)]

    xs = []
    ys = []
    for corner in corners:
        projected = view3d_utils.location_3d_to_region_2d(region, rv3d, corner)
        if projected is None:
            return None
        xs.append(projected.x)
        ys.append(projected.y)

    return (min(xs), min(ys), max(xs), max(ys))


def quad(props, rect, image_width, image_height):
    """Corner positions and UVs for the overlay quad.

    Fit first, then scale, then offset, then rotation -- so rotating never
    changes where the image is centred.
    """
    x0, y0, x1, y1 = rect
    frame_w = x1 - x0
    frame_h = y1 - y0
    if frame_w <= 0.0 or frame_h <= 0.0 or image_width <= 0 or image_height <= 0:
        return None

    image_aspect = image_width / image_height
    frame_aspect = frame_w / frame_h

    if props.fit == 'STRETCH':
        width, height = frame_w, frame_h
    elif props.fit == 'FILL':
        # Cover the frame; the overflowing axis runs past the frame edge.
        if image_aspect > frame_aspect:
            width, height = frame_h * image_aspect, frame_h
        else:
            width, height = frame_w, frame_w / image_aspect
    else:  # 'FIT' -- contain, letterboxed inside the frame
        if image_aspect > frame_aspect:
            width, height = frame_w, frame_w / image_aspect
        else:
            width, height = frame_h * image_aspect, frame_h

    width *= props.scale
    height *= props.scale

    # Offsets are a fraction of the FRAME, not of the image, so nudging by 0.1
    # means the same distance whatever image is loaded.
    center_x = x0 + frame_w * 0.5 + props.offset_x * frame_w
    center_y = y0 + frame_h * 0.5 + props.offset_y * frame_h

    half_w = width * 0.5
    half_h = height * 0.5
    local = ((-half_w, -half_h), (half_w, -half_h),
             (half_w, half_h), (-half_w, half_h))

    # `rotation` is an ANGLE property: Blender shows the user degrees but
    # stores radians, so this takes the value straight rather than converting.
    angle = props.rotation
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    positions = [(center_x + dx * cos_a - dy * sin_a,
                  center_y + dx * sin_a + dy * cos_a) for dx, dy in local]

    u0, u1 = (1.0, 0.0) if props.flip_x else (0.0, 1.0)
    v0, v1 = (1.0, 0.0) if props.flip_y else (0.0, 1.0)
    uvs = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]

    return positions, uvs


# --- Drawing ----------------------------------------------------------------

_CHANNEL_INDEX = {'LUMINANCE': 0, 'R': 1, 'G': 2, 'B': 3, 'ALPHA': 4}


def draw():
    """The registered handler. Nothing may escape it.

    A draw handler that raises does so on EVERY redraw: the console fills up
    and the viewport stutters while the artist is trying to work. Worse, the
    exception happens inside Blender's draw loop, where the GPU state we set
    may not have been put back.

    So a failure switches the overlay off and says why, once, rather than
    failing sixty times a second. Toggling Enable clears it and tries again.
    """
    global _draw_failed

    if _draw_failed:
        return
    try:
        _draw()
    except Exception as exc:
        _draw_failed = True
        set_status("Overlay stopped after an error (toggle Enable to retry): "
                   "%s" % exc)
        # Put the state back by hand: _draw's own finally may not have run.
        try:
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('LESS_EQUAL')
        except Exception:
            pass


def _draw():
    context = bpy.context

    props = getattr(context.scene, "cam_overlay", None)
    if props is None or not props.enabled:
        return

    # Only over the camera frame. A reference that floats around during free
    # navigation is noise, and it is not aligned to anything meaningful.
    rv3d = context.region_data
    if rv3d is None or rv3d.view_perspective != 'CAMERA':
        return

    image = props.image
    if image is None:
        set_status("No image selected")
        return

    width, height = image.size
    if width <= 0 or height <= 0:
        set_status("'%s' has zero size -- is the file missing?" % image.name)
        return

    rect = camera_frame_rect(context)
    if rect is None:
        set_status("Camera frame off screen, or no active camera")
        return

    corners = quad(props, rect, width, height)
    if corners is None:
        set_status("Camera frame has no area")
        return

    shader = get_shader()
    if shader is None:
        return  # get_shader already set the status

    texture = _get_texture(image)
    if texture is None:
        return  # _get_texture already set the status

    positions, uvs = corners

    # Save the GPU state and put back exactly what we found. Restoring to
    # hardcoded defaults instead is how an addon corrupts OTHER addons'
    # overlays -- whichever one draws after us inherits our assumptions.
    previous_blend = gpu.state.blend_get()
    previous_depth = gpu.state.depth_test_get()
    try:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')

        # TRIS with an index buffer rather than TRI_FAN: fans are unsupported
        # by Vulkan and deprecated in Blender's GPU module, and this costs one
        # extra line.
        batch = batch_for_shader(
            shader, 'TRIS', {"pos": positions, "texCoord": uvs},
            indices=[(0, 1, 2), (0, 2, 3)])

        shader.bind()
        shader.uniform_sampler("image", texture)
        shader.uniform_float("opacity", props.opacity)
        shader.uniform_float("threshold", props.threshold)
        shader.uniform_float("tint", tuple(props.tint))
        shader.uniform_int("channel", _CHANNEL_INDEX.get(props.channel, 0))
        shader.uniform_int("invert", 1 if props.invert else 0)
        shader.uniform_int("maskMode", 1 if props.mode == 'MASK' else 0)
        batch.draw(shader)
    except Exception as exc:
        # Visible, not swallowed: the panel will say what went wrong.
        set_status("Draw failed: %s" % exc)
        return
    finally:
        gpu.state.blend_set(previous_blend)
        gpu.state.depth_test_set(previous_depth)

    clear_status()


# --- Handler lifecycle ------------------------------------------------------

def handler_registered():
    return _handle is not None


def enable_handler():
    """Add the draw handler, at most once.

    Also clears a previous draw failure: toggling Enable is the retry.
    """
    global _handle, _draw_failed
    _draw_failed = False
    clear_status()
    if _handle is not None:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(
        draw, (), 'WINDOW', 'POST_PIXEL')


def disable_handler():
    global _handle
    if _handle is None:
        return
    bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
    _handle = None
    clear_status()


def sync_handler(scene=None):
    """Match the handler to whether any scene wants the overlay.

    Needed because `enabled` is saved in the .blend: opening a file with the
    overlay on has to bring the handler back, and opening one with it off has
    to take it away.

    Safe to call from anywhere: during register() Blender hands out a
    restricted `bpy.data` with no `scenes` at all, so that case backs off
    rather than raising and taking the whole addon's registration down with
    it. The caller in register() defers through a timer for that reason.
    """
    try:
        scenes = [scene] if scene is not None else list(bpy.data.scenes)
    except AttributeError:
        return
    for candidate in scenes:
        props = getattr(candidate, "cam_overlay", None)
        if props is not None and props.enabled:
            enable_handler()
            return
    disable_handler()


def shutdown():
    """Full teardown, clean enough to survive repeated addon reloads."""
    global _draw_failed
    disable_handler()
    clear_cache()
    _drop_shader()
    clear_status()
    _draw_failed = False
