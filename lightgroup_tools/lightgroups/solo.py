"""Solo Light: preview the selected lights on their own, in the viewport.

One toggle. On: every other light in the view layer is hidden with the eye,
and the World is switched off in every 3D viewport. Off: exactly what was
changed is put back, nothing more.

VIEWPORT ONLY, BY CONSTRUCTION. Neither switch reaches a render:

- The eye (`hide_set`) drops an object from the viewport depsgraph but not
  from F12 / command-line renders, which read `hide_render`. That flag is
  never touched here.
- The World is muted through each viewport's own shading settings: Scene
  World off, studio-light strength 0. Those live on the 3D view, not on the
  World datablock, so its Strength and node tree are never edited.

So a file saved mid-solo still renders every light. That is the whole safety
story: there is nothing to forget to undo before a render.

What gets muted is LIGHT objects only. Emissive meshes and festoon bulbs are
left alone -- hiding one hides its geometry too, which is a different tool.

Only what this operator changed is restored: a light that was already hidden
stays hidden, and each viewport gets its own World settings back.
"""

import bpy


# --- State, saved in the scene ----------------------------------------------
#
# Kept on the scene rather than in module globals so it survives a save and
# reopen mid-solo, and travels with the file it describes.

class LightgroupSoloMuted(bpy.types.PropertyGroup):
    # A pointer rather than a name: renaming a light mid-solo must not strand
    # it hidden.
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


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
    soloed: bpy.props.CollectionProperty(type=LightgroupSoloMuted)
    muted: bpy.props.CollectionProperty(type=LightgroupSoloMuted)
    spaces: bpy.props.CollectionProperty(type=LightgroupSoloSpace)


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


def solo_on(context, lights):
    """Mute every light except `lights`, and the World. Returns muted count."""
    settings = context.scene.lightgroup_solo
    view_layer = context.view_layer
    keep = set(lights)

    settings.muted.clear()
    settings.soloed.clear()
    settings.spaces.clear()
    settings.view_layer = view_layer.name

    for obj in lights:
        settings.soloed.add().obj = obj

    for obj in view_layer.objects:
        # visible_get covers the eye, the monitor and hidden collections:
        # anything already invisible is not ours to hide, or to unhide later.
        if obj.type != 'LIGHT' or obj in keep or not obj.visible_get(view_layer=view_layer):
            continue
        obj.hide_set(True, view_layer=view_layer)
        settings.muted.add().obj = obj

    for screen, area_index, space in _view3d_spaces():
        record = settings.spaces.add()
        record.screen = screen.name
        record.area_index = area_index
        record.use_scene_world_render = space.shading.use_scene_world_render
        record.studiolight_intensity = space.shading.studiolight_intensity
        space.shading.use_scene_world_render = False
        space.shading.studiolight_intensity = 0.0

    settings.active = True
    _redraw_viewports(context)
    return len(settings.muted)


def solo_off(context):
    """Put back exactly what solo_on changed."""
    settings = context.scene.lightgroup_solo
    view_layer = context.scene.view_layers.get(settings.view_layer) or context.view_layer

    for record in settings.muted:
        obj = record.obj
        if obj is None:  # deleted mid-solo
            continue
        try:
            obj.hide_set(False, view_layer=view_layer)
        except RuntimeError:
            # Moved out of the view layer mid-solo; nothing to unhide.
            pass

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


class LIGHTGROUP_OT_solo_light(bpy.types.Operator):
    """Viewport only: hide every other light and switch off the World so the selected lights can be judged on their own. Click again to restore"""
    bl_idname = "lightgroup.solo_light"
    bl_label = "Solo Light"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.lightgroup_solo

        if settings.active:
            solo_off(context)
            self.report({'INFO'}, "Solo off: lights and World restored")
            return {'FINISHED'}

        lights = [obj for obj in context.selected_objects if obj.type == 'LIGHT']
        if not lights:
            self.report({'ERROR'}, "Select one or more lights to solo")
            return {'CANCELLED'}

        muted = solo_on(context, lights)
        self.report({'INFO'}, f"Solo: {len(lights)} light(s), {muted} muted, World off (viewport only)")
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
        shown = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
        box.label(text=f"Soloing: {shown}", icon='LIGHT')
        box.label(text=f"{len(settings.muted)} lights hidden, World off")


classes = (
    LightgroupSoloMuted,
    LightgroupSoloSpace,
    LightgroupSoloSettings,
    LIGHTGROUP_OT_solo_light,
)


def register_properties():
    bpy.types.Scene.lightgroup_solo = bpy.props.PointerProperty(
        type=LightgroupSoloSettings)


def unregister_properties():
    if hasattr(bpy.types.Scene, "lightgroup_solo"):
        del bpy.types.Scene.lightgroup_solo
