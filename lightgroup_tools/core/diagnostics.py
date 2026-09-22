"""One-click support report for the whole toolkit.

The problem this solves: a team member says "it doesn't work" and there is
nothing to go on. The Camera Overlay exists at all because a commercial addon
failed silently and diagnosing it took a source read. The lesson generalises,
so the report covers the whole toolkit rather than one tool.

One click writes a text file and opens the folder holding it, so the reply is
"drag that file into the chat" rather than a paragraph of instructions about
the system console. The text also goes to the clipboard and the console, so a
quick paste still works.

Safety rules in here, because this runs on other people's machines:

* **Nothing may raise.** Every probe is guarded individually -- a report that
  crashes is worse than no report, and the machine producing it is by
  definition already misbehaving. A section that fails says so and the rest
  of the report still arrives.
* **The folder is opened through `bpy.ops.wm.path_open`**, Blender's own
  cross-platform opener. No subprocess, so no shell quoting to get wrong on a
  path with spaces, and it works the same on Windows, macOS and Linux.
* **Only what is needed for diagnosis.** File paths are included because the
  whole bug class this toolkit guards against is path resolution -- knowing a
  path is `//relative` or packed is the diagnosis. No environment dump, no
  credentials, nothing that is not addon state.
* Writing can fail for ordinary reasons (read-only disk, permissions). That
  is reported in the UI rather than thrown.

Tools contribute their own section through `register_section`, so this module
never imports them -- core must not depend on the tools that depend on it.
"""

import datetime
import os
import platform
import sys

import bpy

REPORT_PREFIX = "lightgroup_tools_diagnostics"

# [(title, callable(context) -> list[str])], in registration order. Tools add
# to this from their own register(); core never imports a tool to find them.
_SECTIONS = []


def register_section(title, func):
    unregister_section(title)
    _SECTIONS.append((title, func))


def unregister_section(title):
    for index, (existing, _) in enumerate(list(_SECTIONS)):
        if existing == title:
            del _SECTIONS[index]
            return


def _safe(label, func, default="unavailable"):
    """Run a probe, never let it break the report."""
    try:
        return func()
    except Exception as exc:
        return "%s (%s: %s)" % (default, type(exc).__name__, exc)


def _report_dir():
    """Beside the updater's staging and backup dirs, for consistency."""
    return os.path.join(bpy.utils.user_resource('CONFIG'),
                        "lightgroup_tools_diagnostics")


def report_path(stamp=None):
    """A fresh, timestamped filename.

    Each run writes a NEW file and nothing is ever overwritten or tidied up.
    They are a couple of kilobytes each, so there is no reason to delete one
    to make room for the next -- and "the addon removed a file on my machine"
    is not a sentence anyone wants to read mid-season. Old reports stay until
    the user removes them.
    """
    if stamp is None:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(_report_dir(), "%s_%s.txt" % (REPORT_PREFIX, stamp))


def _addon_version():
    package = sys.modules.get(__name__.partition('.')[0])
    info = getattr(package, "bl_info", {}) if package else {}
    version = info.get("version")
    return ".".join(str(part) for part in version) if version else "unknown"


def _gpu_lines():
    import gpu

    lines = []
    for label, getter in (("backend", gpu.platform.backend_type_get),
                          ("vendor", gpu.platform.vendor_get),
                          ("renderer", getattr(gpu.platform, "renderer_get",
                                               None)),
                          ("device", gpu.platform.device_type_get)):
        if getter is None:
            continue
        lines.append("  %-10s %s" % (label + ":", _safe(label, getter)))
    return lines


def _registration_lines():
    """Is the addon actually fully registered?

    The most common support answer. A partly-registered addon -- which is
    what Blender leaves behind when a register() raises -- looks fine in the
    Preferences list while a tab is silently missing.
    """
    lines = []
    addon = sys.modules.get(__name__.partition('.')[0])
    enabled = bpy.context.preferences.addons.get(
        __name__.partition('.')[0]) is not None
    lines.append("  enabled in prefs: %s" % enabled)

    for tab, panel in (("Lightgroups", "LIGHTGROUP_PT_main_panel"),
                       ("Festoon Clicker", "FESTOON_PT_main_panel"),
                       ("Camera Overlay", "CAMOVERLAY_PT_main_panel")):
        present = hasattr(bpy.types, panel)
        lines.append("  %-16s %s" % (tab + ":",
                                     "registered" if present
                                     else "MISSING -- this tool failed to "
                                          "register, check the console"))
    if addon is not None:
        expected = len(getattr(addon, "classes", ()))
        lines.append("  classes declared: %d" % expected)
    return lines


def _scene_lines(context):
    scene = context.scene
    lines = [
        "  blend file:   %s" % (bpy.data.filepath or "<unsaved>"),
        "  scene:        %s" % scene.name,
        "  view layer:   %s" % context.view_layer.name,
        "  engine:       %s" % scene.render.engine,
        "  resolution:   %d x %d @ %d%%" % (scene.render.resolution_x,
                                            scene.render.resolution_y,
                                            scene.render.resolution_percentage),
        "  camera:       %s" % (scene.camera.name if scene.camera else "none"),
        "  view layers:  %d" % len(scene.view_layers),
    ]
    groups = getattr(context.view_layer, "lightgroups", None)
    if groups is not None:
        lines.append("  lightgroups:  %d" % len(groups))
    return lines


def _preferences_lines():
    addon_name = __name__.partition('.')[0]
    entry = bpy.context.preferences.addons.get(addon_name)
    if entry is None or entry.preferences is None:
        return ["  <no preferences registered>"]
    prefs = entry.preferences
    # Deliberately a fixed list: update state only, nothing else.
    lines = []
    for field in ("update_available", "latest_version", "update_downloaded",
                  "staged_update_version", "backup_available",
                  "backup_version", "update_just_installed",
                  "last_installed_version"):
        lines.append("  %-22s %s" % (field + ":",
                                     getattr(prefs, field, "<absent>")))
    return lines


def build_report(context):
    """The whole report as a list of lines. Never raises."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 64,
        "Lightgroup Tools -- diagnostics report",
        "Generated: %s" % stamp,
        "=" * 64,
        "",
        "ADDON",
        "  version:      %s" % _safe("version", _addon_version),
        "",
        "BLENDER",
        "  version:      %s" % bpy.app.version_string,
        "  build hash:   %s" % _safe("hash", lambda: (
            bpy.app.build_hash.decode()
            if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash)),
        "  binary:       %s" % bpy.app.binary_path,
        "  platform:     %s" % _safe("platform", platform.platform),
        "  python:       %s" % sys.version.split()[0],
        "",
        "GPU",
    ]
    gpu_lines = _safe("gpu", _gpu_lines, default=None)
    lines.extend(gpu_lines if isinstance(gpu_lines, list)
                 else ["  unavailable (%s)" % gpu_lines])

    for title, builder in (("REGISTRATION", _registration_lines),
                           ("PREFERENCES (update state)", _preferences_lines)):
        lines.extend(["", title])
        produced = _safe(title, builder, default=None)
        lines.extend(produced if isinstance(produced, list)
                     else ["  unavailable (%s)" % produced])

    lines.extend(["", "SCENE"])
    produced = _safe("scene", lambda: _scene_lines(context), default=None)
    lines.extend(produced if isinstance(produced, list)
                 else ["  unavailable (%s)" % produced])

    # Per-tool sections. Each is guarded on its own: a tool whose reporter is
    # broken must not cost us the rest of the report.
    for title, func in list(_SECTIONS):
        lines.extend(["", title.upper()])
        produced = _safe(title, lambda f=func: f(context), default=None)
        lines.extend(produced if isinstance(produced, list)
                     else ["  unavailable (%s)" % produced])

    lines.extend(["", "=" * 64, "end of report", "=" * 64])
    return lines


def write_report(context):
    """Write a new report to disk. Returns (path, error_message).

    Creates one file and touches nothing else. Nothing in this module
    deletes, overwrites or moves anything.
    """
    text = "\n".join(build_report(context))
    try:
        os.makedirs(_report_dir(), exist_ok=True)
        path = report_path()
        # 'x' rather than 'w': refuse to clobber even in the unlikely event
        # that a file with this timestamp already exists.
        try:
            handle = open(path, "x", encoding="utf-8")
        except FileExistsError:
            path = report_path(
                datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f"))
            handle = open(path, "x", encoding="utf-8")
        with handle:
            handle.write(text)
        return path, None
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


class LIGHTGROUP_OT_write_diagnostics(bpy.types.Operator):
    """Save a support report and show it in the file browser"""

    bl_idname = "lightgroup.write_diagnostics"
    bl_label = "Save Diagnostics Report"
    bl_description = ("Write a support report to a text file, open the folder "
                      "containing it, and copy it to the clipboard")

    def execute(self, context):
        text = "\n".join(build_report(context))
        print(text)

        # Clipboard first: it is the one thing that still works if the disk
        # write fails, and it costs nothing.
        try:
            context.window_manager.clipboard = text
        except Exception:
            pass

        path, error = write_report(context)
        if path is None:
            self.report({'ERROR'},
                        "Could not write the report (%s). It is on the "
                        "clipboard and in the system console instead." % error)
            return {'CANCELLED'}

        # Blender's own opener: cross-platform, and no shell quoting to get
        # wrong on a path with spaces. Failing to open is not worth failing
        # the operator over -- the file is written either way.
        #
        # NOT in background mode. `wm.path_open` still asks the OS to open a
        # file browser with no GUI running, so a headless test run spawns a
        # window on the machine running it -- which is exactly what happened,
        # once per Blender version, on David's desktop.
        opened = False
        if not bpy.app.background:
            try:
                bpy.ops.wm.path_open(filepath=os.path.dirname(path))
                opened = True
            except Exception:
                opened = False

        name = os.path.basename(path)
        if opened:
            self.report({'INFO'}, "Saved %s -- the folder is open, send that "
                                  "file to David" % name)
        else:
            self.report({'INFO'}, "Saved to %s (also on the clipboard)" % path)
        return {'FINISHED'}


classes = (
    LIGHTGROUP_OT_write_diagnostics,
)
