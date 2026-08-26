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

        box = layout.box()
        box.label(text="Click start, click end, set sag", icon='INFO')
        box.label(text="Scroll during sag = flatness")

        layout.separator()
        layout.label(text="New strands use:")
        layout.prop(settings, "bulb_object")
        layout.prop(settings, "flatness", slider=True)

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
        "Cable Radius",
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

        # Bulb and cable material live on nodes inside the strand's own group,
        # not on modifier inputs -- an Object on a modifier input hangs Blender
        # 5.2. See nodes.create_group(). Edit them through the node sockets.
        bulb_node = rig.strand_node(strand, festoon_nodes.NODE_BULB_INFO)
        if bulb_node is not None:
            layout.prop(bulb_node.inputs["Object"], "default_value", text="Bulb")

        material_node = rig.strand_node(strand, festoon_nodes.NODE_CABLE_MATERIAL)
        if material_node is not None:
            layout.prop(material_node.inputs["Material"], "default_value",
                        text="Cable Material")

        layout.separator()
        layout.operator("festoon.select_controls", icon='EMPTY_AXIS')

        box = layout.box()
        box.label(text="Sag: move the _Sag empty", icon='INFO')
        box.label(text="Flatness: scale that empty")


classes = (
    FESTOON_PT_main_panel,
    FESTOON_PT_strand_panel,
)
