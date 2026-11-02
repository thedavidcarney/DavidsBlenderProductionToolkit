"""After each frame, check that the File Output EXRs really reached the disk.

When memory runs out, Blender still logs `Saved:` and exits 0, leaving a
truncated EXR or none at all. With the render output off there is no second
copy to fall back on, so this looks at the files themselves.

Read-only. A problem is printed and shown in red in the Lightgroups tab; the
render carries on, because the other frames may well be fine. Nothing in here
may raise, since it runs inside the render.
"""

import os
import re
import struct
import time

import bpy

EXR_MAGIC = 20000630
MULTIPART_FLAG = 0x1000
# The longest list worth drawing in a sidebar. The count keeps going.
MAX_SHOWN = 6

_frame_started = 0.0
_problem_count = 0
_problems = []


def _read_cstring(handle):
    chars = bytearray()
    while True:
        char = handle.read(1)
        if not char:
            raise ValueError("header is cut off")
        if char == b"\0":
            return chars.decode("latin-1")
        chars += char


def read_exr_parts(path):
    """Return (part count, problem or None) from the EXR's headers.

    Part count is None for a single-part file, which doesn't have the chunk
    counts this relies on. Blender only fills the offset tables in once a part
    has finished writing, so a zero offset or one past the end of the file means
    the write didn't complete.
    """
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        start = handle.read(8)
        if len(start) < 8:
            return 0, "file is cut off"
        magic, version = struct.unpack("<II", start)
        if magic != EXR_MAGIC:
            return 0, "not an EXR"
        if not version & MULTIPART_FLAG:
            return None, None

        chunk_counts = []
        try:
            while True:
                name = _read_cstring(handle)
                if not name:
                    # An empty header ends the list of parts.
                    break
                chunks = None
                while name:
                    _read_cstring(handle)  # the attribute's type
                    length_bytes = handle.read(4)
                    if len(length_bytes) < 4:
                        raise ValueError("header is cut off")
                    length = struct.unpack("<i", length_bytes)[0]
                    if name == "chunkCount":
                        chunks = struct.unpack("<i", handle.read(4))[0]
                    else:
                        handle.seek(length, os.SEEK_CUR)
                    name = _read_cstring(handle)
                if chunks is None:
                    return len(chunk_counts), "a part has no chunk count"
                chunk_counts.append(chunks)
        except ValueError as error:
            return len(chunk_counts), str(error)

        for chunks in chunk_counts:
            table = handle.read(chunks * 8)
            if len(table) < chunks * 8:
                return len(chunk_counts), "file is cut off"
            for offset in struct.unpack("<%dQ" % chunks, table):
                if offset == 0 or offset >= size:
                    return len(chunk_counts), "file is cut off"
    return len(chunk_counts), None


def _candidate_paths(node, scene):
    """Where this node writes the current frame, or None if we can't tell."""
    if not bpy.data.filepath:
        return None
    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    folder = node.directory.replace("{blend_name}", blend_name)
    name = node.file_name.replace("{blend_name}", blend_name)
    if "{" in folder or "{" in name:
        return None
    folder = bpy.path.abspath(folder)
    frame = scene.frame_current
    if "#" in name:
        name = re.sub(r"#+", lambda run: str(frame).zfill(len(run.group())), name)
        return [os.path.join(folder, name + ".exr")]
    # A plain F12 still gets no frame number.
    return [os.path.join(folder, "%s%04d.exr" % (name, frame)),
            os.path.join(folder, name + ".exr")]


def _check_node(node, scene, since):
    paths = _candidate_paths(node, scene)
    if paths is None:
        return None
    fresh = [p for p in paths if os.path.isfile(p) and os.path.getmtime(p) >= since]
    if not fresh:
        return "%s: not written" % os.path.basename(paths[0])
    path = fresh[0]
    label = os.path.basename(path)
    parts, problem = read_exr_parts(path)
    if problem:
        return "%s: %s" % (label, problem)
    expected = sum(1 for socket in node.inputs if socket.is_linked)
    if parts is not None and parts < expected:
        return "%s: %d of %d layers" % (label, parts, expected)
    return None


def check_scene(scene, since=0.0):
    """Return one line per File Output whose file isn't right."""
    tree = getattr(scene, "compositing_node_group", None)
    if tree is None or not scene.render.use_compositing:
        return []
    problems = []
    for node in tree.nodes:
        if node.bl_idname != 'CompositorNodeOutputFile' or node.mute:
            continue
        if node.format.file_format != 'OPEN_EXR_MULTILAYER':
            continue
        problem = _check_node(node, scene, since)
        if problem:
            problems.append(problem)
    return problems


def problems():
    """(lines to show, total count) from the current or latest render."""
    return list(_problems), _problem_count


def _redraw_panels():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'NODE_EDITOR'}:
                area.tag_redraw()
    return None


@bpy.app.handlers.persistent
def _on_render_init(*_args):
    global _problem_count
    _problem_count = 0
    _problems.clear()


@bpy.app.handlers.persistent
def _on_render_pre(*_args):
    global _frame_started
    # Slack for filesystems that store modified times to the nearest 2 seconds.
    _frame_started = time.time() - 2.0


@bpy.app.handlers.persistent
def _on_render_post(scene, *_args):
    global _problem_count
    try:
        found = check_scene(scene, _frame_started)
    except Exception as error:
        print("[lightgroup_tools] output check could not run: %s" % error)
        return
    if not found:
        return
    for line in found:
        print("[lightgroup_tools] OUTPUT CHECK FAILED: %s" % line)
    _problem_count += len(found)
    _problems.extend(found[:MAX_SHOWN - len(_problems)])
    if not bpy.app.background:
        # We may be on the render thread here; the panel redraws on the main one.
        bpy.app.timers.register(_redraw_panels, first_interval=0.1)


_HANDLERS = (
    ("render_init", _on_render_init),
    ("render_pre", _on_render_pre),
    ("render_post", _on_render_post),
)


def _is_ours(handler, func):
    # Matched by name, not identity, so an importlib.reload can't leave the old
    # function running beside the new one.
    return (getattr(handler, "__module__", None) == func.__module__
            and getattr(handler, "__name__", None) == func.__name__)


def unregister_handlers():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        for handler in [h for h in handlers if _is_ours(h, func)]:
            handlers.remove(handler)


def register_handlers():
    unregister_handlers()
    for name, func in _HANDLERS:
        getattr(bpy.app.handlers, name).append(func)


def draw_status(layout, context):
    """The Compositor section's notes: render output off, and any bad files."""
    if not getattr(context.scene.render, "save_output", True):
        layout.label(text="Render Output off: File Output only", icon='INFO')
    shown, total = problems()
    if shown:
        box = layout.box()
        box.alert = True
        box.label(text="%d bad EXR%s in the last render" % (total, "" if total == 1 else "s"), icon='ERROR')
        for line in shown:
            box.label(text=line)
