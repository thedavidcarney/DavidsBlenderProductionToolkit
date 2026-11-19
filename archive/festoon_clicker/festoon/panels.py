"""Festoon Clicker sidebar panel.

Deliberately its own tab. The Lightgroups tab is a per-project workhorse used
on every job; festoon is a building tool. Mixing unrelated tools into one
panel is what makes a toolkit turn into a junk drawer.
"""

import bpy

from . import nodes as festoon_nodes
from . import rig


class FESTOON_PT_main_panel(bpy.types.Panel):
    bl_label = "Festoon Clicker"
    bl_idname = "FESTOON_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Festoon Clicker'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.festoon_settings

        column = layout.column()
        column.scale_y = 1.5
        column.operator("festoon.place_strand", icon='OUTLINER_OB_LIGHT',
                        text="Place Strand")
        column.operator("festoon.place_spiral", icon='FORCE_MAGNETIC',
                        text="Wrap Object")

        box = layout.box()
        box.label(text="Strand: start, end, then set sag", icon='INFO')
        box.label(text="Wrap: base, top, then set wraps")
        box.label(text="Scroll fine-tunes; preview follows the cursor")

        layout.separator()
        layout.label(text="New strands use:")
        layout.prop(settings, "bulb_collection")
        layout.prop(settings, "bulb_object")
        layout.prop(settings, "bulb_spacing")
        layout.prop(settings, "flatness", slider=True)
        layout.prop(settings, "spiral_turns")

        strands = rig.strand_objects(context.scene)
        if strands:
            layout.separator()
            layout.label(text="%d strand%s in scene"
                              % (len(strands), "" if len(strands) == 1 else "s"))


class FESTOON_PT_strand_panel(bpy.types.Panel):
    """Settings for the selected strand.

    These are the geometry nodes modifier's own inputs. Surfacing them here
    saves a trip to the modifier tab for the handful that get tweaked
    constantly, without hiding the full set.
    """

    bl_label = "Selected Strand"
    bl_idname = "FESTOON_PT_strand_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Festoon Clicker'
    bl_parent_id = "FESTOON_PT_main_panel"

    # Inputs worth having one click away, in the order they get fiddled with.
    QUICK_INPUTS = (
        "Bulb Spacing",
        "Bulb Scale",
        "Bulb Rotation",
        "Cable Radius",
        "Cable Strands",
        "Cable Twist",
        "Turns",
        "Surface Offset",
        "Search Radius",
        "Radius Jitter",
        "Fallback Radius",
        "Random Tilt",
        "Random Spin",
        "Seed",
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("festoon_strand") is not None

    def draw(self, context):
        layout = self.layout
        strand = context.active_object

        modifier = next((m for m in strand.modifiers if m.type == 'NODES'), None)
        if modifier is None or modifier.node_group is None:
            layout.label(text="No festoon modifier on this object", icon='ERROR')
            return

        layout.label(text=strand.name, icon='OUTLINER_OB_MESH')

        tree = modifier.node_group

        # Drawn from the node group's INTERFACE items, not from the modifier.
        # On Blender 5.2 a modifier input is a read-only RNA pointer whose
        # underlying value the evaluator ignores; the interface default is
        # what actually drives the result. Safe because every strand owns its
        # own group, so editing here affects only this strand.
        for name in self.QUICK_INPUTS:
            item = rig.interface_input(tree, name)
            if item is None or not hasattr(item, "default_value"):
                continue
            layout.prop(item, "default_value", text=name)

        # Bulb object/collection live on NODES rather than modifier inputs,
        # unlike Cable Material above. Not because a datablock socket can't be
        # exposed -- it can -- but because these two are the ones this addon
        # assigns from Python at creation time, and that specific write
        # (modifier.properties.inputs[...] = datablock) is what hangs 5.2.
        # See nodes.create_group().
        collection_node = rig.strand_node(strand, festoon_nodes.NODE_BULB_COLLECTION)
        if collection_node is not None:
            layout.prop(collection_node.inputs["Collection"], "default_value",
                        text="Bulb Collection")

        bulb_node = rig.strand_node(strand, festoon_nodes.NODE_BULB_INFO)
        if bulb_node is not None:
            layout.prop(bulb_node.inputs["Object"], "default_value", text="Bulb Object")

        # Cable Material is deliberately NOT drawn here. It is a real modifier
        # input, and for a linked group input the interface default stores but
        # never applies -- only the modifier's own value does, and only Blender's
        # UI can write that. Drawing it here would be an inert control that
        # looks like it works.
        # Cable Material itself is a modifier input and can only be written by
        # Blender's own UI, so it isn't drawn here. The toggle beside it is a
        # plain boolean and works fine from the interface default.
        toggle = rig.interface_input(tree, "Use Custom Cable Material")
        if toggle is not None:
            layout.prop(toggle, "default_value", text="Use Custom Cable Material")
        layout.label(text="Cable Material: in the Modifier panel", icon='MATERIAL')

        layout.separator()
        layout.operator("festoon.select_controls", icon='EMPTY_AXIS')

        box = layout.box()
        box.label(text="Sag: move the _Sag empty", icon='INFO')
        box.label(text="Flatness: scale that empty")


classes = (
    FESTOON_PT_main_panel,
    FESTOON_PT_strand_panel,
)
