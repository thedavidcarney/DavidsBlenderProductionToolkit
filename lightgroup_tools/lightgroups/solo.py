"""Solo Light mode: whichever light you click is the one you hear.

Turn the mode on, then click lights -- in the viewport or the outliner. The
selected lights stay lit; every other light in the view layer goes dark, and
the World is switched off in every 3D viewport. Shift-click to solo several.
Clicking something that isn't a light keeps the current solo. Turn the mode
off and everything is put back exactly as it was.

HOW A LIGHT IS MUTED: its ray visibility (camera, diffuse, glossy,
transmission, volume scatter) is switched off. Measured to silence point,
area, spot and sun lights completely in both Cycles and EEVEE. Unlike hiding
it with the eye, the light stays in the viewport -- gizmo, outline and all --
so it can still be clicked, which is the whole point of the mode.

WHY THAT IS STILL SAFE FOR RENDERS: ray visibility does reach F12, so it is
never allowed to. Every switch is put back before each render and each save,
and re-applied straight after:

- render_pre / render_post / render_cancel: F12 and animation renders see
  every light. Verified: a soloed F12 matches an unsoloed one pixel for pixel.
- save_pre / save_post: the .blend on disk NEVER has a muted light in it, so a
  file saved mid-solo renders correctly on the farm or on a machine without
  this addon. Re-muting after the save does not mark the file dirty.

The World is muted differently -- through each 3D view's own shading (Scene
World off, studio-light strength 0) -- so its Strength and node tree are never
edited and it needs no safety net at all.

Only LIGHT objects are muted. Emissive meshes and festoon bulbs are untouched.
"""

import bpy


# Ray-visibility switches that, all off, make a light contribute nothing.
RAY_FLAGS = (
    "visible_camera",
    "visible_diffuse",
    "visible_glossy",
    "visible_transmission",
    "visible_volume_scatter",
)


# --- State, saved in the scene ----------------------------------------------
#
# On the scene rather than in module globals, so undo and save/reopen keep the
# state and the switches it describes in step.

class LightgroupSoloLight(bpy.types.PropertyGroup):
    # A pointer rather than a name: renaming a light mid-solo must not strand
    # it muted.
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


class LightgroupSoloMuted(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object)
    # The light's own switches before we touched them, restored verbatim -- a
    # light deliberately set to no-glossy stays that way.
    visible_camera: bpy.props.BoolProperty()
    visible_diffuse: bpy.props.BoolProperty()
    visible_glossy: bpy.props.BoolProperty()
    visible_transmission: bpy.props.BoolProperty()
    visible_volume_scatter: bpy.props.BoolProperty()


class LightgroupSoloSpace(bpy.types.PropertyGroup):
    # Spaces cannot carry custom properties and are not IDs, so a viewport is
    # addressed by where it sits. A layout edited mid-solo just means that
    # record no longer matches anything, and it is skipped.
    screen: bpy.props.StringProperty()
    area_index: bpy.props.IntProperty()
    use_scene_world_render: bpy.props.BoolProperty()
    studiolight_intensity: bpy.props.FloatProperty()


class LightgroupSoloSettings(bpy.types.PropertyGroup):
    active: bpy.props.BoolProperty(default=False)
    view_layer: bpy.props.StringProperty()
    soloed: bpy.props.CollectionProperty(type=LightgroupSoloLight)
    muted: bpy.props.CollectionProperty(type=LightgroupSoloMuted)
    spaces: bpy.props.CollectionProperty(type=LightgroupSoloSpace)


# --- Muting -------------------------------------------------------------------

def _mute(settings, obj):
    record = settings.muted.add()
    record.obj = obj
    for flag in RAY_FLAGS:
        setattr(record, flag, getattr(obj, flag))
        setattr(obj, flag, False)


def _write_back(record):
    obj = record.obj
    if obj is None:  # deleted mid-solo
        return
    for flag in RAY_FLAGS:
        if getattr(obj, flag) != getattr(record, flag):
            setattr(obj, flag, getattr(record, flag))


def _remute(record):
    obj = record.obj
    if obj is None:
        return
    for flag in RAY_FLAGS:
        if getattr(obj, flag):
            setattr(obj, flag, False)


def _selected_lights(view_layer):
    return [obj for obj in view_layer.objects.selected if obj.type == 'LIGHT']


def _view_layer(scene, settings):
    return scene.view_layers.get(settings.view_layer)


def apply(scene, view_layer):
    """Make the muted set match the current selection. Cheap when unchanged.

    Runs on every depsgraph update while the mode is on, so the common case --
    nothing about the selection changed -- has to cost a set comparison and
    nothing else. Our own writes trigger one more update, which lands here and
    finds nothing to do.
    """
    settings = scene.lightgroup_solo

    selected = _selected_lights(view_layer)
    if selected:
        current = {r.obj for r in settings.soloed}
        if set(selected) != current:
            settings.soloed.clear()
            for obj in selected:
                settings.soloed.add().obj = obj
    # Nothing selected, or a non-light clicked: keep the current solo, so
    # clicking a mesh to look at it does not relight the whole scene.

    soloed = {r.obj for r in settings.soloed}
    wanted = {obj for obj in view_layer.objects
              if obj.type == 'LIGHT' and obj not in soloed}
    have = {r.obj for r in settings.muted}
    if wanted == have:
        return

    # Unmute what should now be heard, in reverse so indices stay valid.
    for index in range(len(settings.muted) - 1, -1, -1):
        record = settings.muted[index]
        if record.obj not in wanted:
            _write_back(record)
            settings.muted.remove(index)

    for obj in wanted - have:
        _mute(settings, obj)


def _view3d_spaces():
    """Every 3D view in the file, with the address used to find it again.

    All screens, not just the open one: switching workspace mid-solo must not
    bring the World back.
    """
    for screen in bpy.data.screens:
        for area_index, area in enumerate(screen.areas):
            if area.type == 'VIEW_3D':
                yield screen, area_index, area.spaces.active


def _redraw_viewports(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def mode_on(context):
    settings = context.scene.lightgroup_solo
    settings.muted.clear()
    settings.soloed.clear()
    settings.spaces.clear()
    settings.view_layer = context.view_layer.name

    for screen, area_index, space in _view3d_spaces():
        record = settings.spaces.add()
        record.screen = screen.name
        record.area_index = area_index
        record.use_scene_world_render = space.shading.use_scene_world_render
        record.studiolight_intensity = space.shading.studiolight_intensity
        space.shading.use_scene_world_render = False
        space.shading.studiolight_intensity = 0.0

    settings.active = True
    apply(context.scene, context.view_layer)
    _redraw_viewports(context)


def mode_off(context):
    """Put back exactly what the mode changed."""
    settings = context.scene.lightgroup_solo

    for record in settings.muted:
        _write_back(record)

    for record in settings.spaces:
        screen = bpy.data.screens.get(record.screen)
        if screen is None or record.area_index >= len(screen.areas):
            continue
        area = screen.areas[record.area_index]
        if area.type != 'VIEW_3D':
            continue
        shading = area.spaces.active.shading
        shading.use_scene_world_render = record.use_scene_world_render
        shading.studiolight_intensity = record.studiolight_intensity

    settings.muted.clear()
    settings.soloed.clear()
    settings.spaces.clear()
    settings.active = False
    _redraw_viewports(context)


# --- Handlers -----------------------------------------------------------------
#
# All persistent, so they survive file loads; each one checks the scene's own
# state, so a file that was never soloed costs one attribute read.

def _active_settings(scene):
    settings = getattr(scene, "lightgroup_solo", None)
    if settings is None or not settings.active:
        return None
    return settings


_applying = []


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    if _applying or _suspended:
        return
    settings = _active_settings(scene)
    if settings is None:
        return
    view_layer = _view_layer(scene, settings)
    if view_layer is None or depsgraph.view_layer.name != view_layer.name:
        return
    _applying.append(True)
    try:
        apply(scene, view_layer)
    except Exception:
        # A handler that raises does so on every update. Say so once, then
        # leave the scene alone rather than spamming the console.
        import traceback
        traceback.print_exc()
    finally:
        _applying.clear()


# Scenes whose lights are currently written back for a render or save.
_suspended = []


@bpy.app.handlers.persistent
def _suspend(*_args):
    """Before a render or save: every muted light gets its own switches back."""
    if _suspended:
        return
    for scene in bpy.data.scenes:
        settings = _active_settings(scene)
        if settings is None:
            continue
        for record in settings.muted:
            _write_back(record)
        _suspended.append(scene.name)


@bpy.app.handlers.persistent
def _resume(*_args):
    """After the render or save: mute them again."""
    names = list(_suspended)
    _suspended.clear()
    for name in names:
        scene = bpy.data.scenes.get(name)
        settings = _active_settings(scene) if scene else None
        if settings is None:
            continue
        for record in settings.muted:
            _remute(record)


_HANDLERS = (
    ("depsgraph_update_post", _on_depsgraph_update),
    ("render_pre", _suspend),
    ("render_post", _resume),
    ("render_cancel", _resume),
    ("save_pre", _suspend),
    ("save_post", _resume),
)


def _is_ours(handler, func):
    # Matched by name, not identity: after an importlib.reload the live
    # handler is the OLD function object, and an identity check would leave
    # it running beside the new one -- two handlers muting the same lights.
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


# --- UI -------------------------------------------------------------------------

class LIGHTGROUP_OT_solo_light(bpy.types.Operator):
    """Solo mode: whichever light you click is the only one lit, World off. Viewport only -- renders and saved files always get every light. Click again to leave the mode"""
    bl_idname = "lightgroup.solo_light"
    bl_label = "Solo Light"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.scene.lightgroup_solo.active:
            mode_off(context)
            self.report({'INFO'}, "Solo off: lights and World restored")
        else:
            mode_on(context)
            self.report({'INFO'}, "Solo on: click a light to hear it on its own")
        return {'FINISHED'}


def draw_solo(layout, context):
    """The Solo section of the Lightgroups panel."""
    settings = getattr(context.scene, "lightgroup_solo", None)
    if settings is None:
        return

    layout.label(text="Solo:")
    layout.operator("lightgroup.solo_light", icon='LIGHT_SUN',
                    text="Solo Light: ON" if settings.active else "Solo Light",
                    depress=settings.active)

    if settings.active:
        box = layout.box()
        box.alert = True
        names = [r.obj.name for r in settings.soloed if r.obj is not None]
        if names:
            shown = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
            box.label(text=f"Soloing: {shown}", icon='LIGHT')
        else:
            box.label(text="Click a light to solo it", icon='LIGHT')
        box.label(text=f"{len(settings.muted)} lights muted, World off")


classes = (
    LightgroupSoloLight,
    LightgroupSoloMuted,
    LightgroupSoloSpace,
    LightgroupSoloSettings,
    LIGHTGROUP_OT_solo_light,
)


def register_properties():
    bpy.types.Scene.lightgroup_solo = bpy.props.PointerProperty(
        type=LightgroupSoloSettings)
    register_handlers()


def unregister_properties():
    unregister_handlers()
    if hasattr(bpy.types.Scene, "lightgroup_solo"):
        del bpy.types.Scene.lightgroup_solo
