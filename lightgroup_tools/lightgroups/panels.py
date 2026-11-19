"""Sidebar panels for the Lightgroups tool.

Moved verbatim out of the addon's top-level __init__.py during the package
restructure. Nothing about what these draw has changed -- same tab, same
buttons, same order.
"""

import bpy

# Module scope, never inside a function: a relative import in a function body
# only resolves when that code path runs, so moving this module would break
# a panel silently and only for whoever clicked the button.
from . import solo
from . import output_check



def _draw_tools(layout, context):
    """Draw the full Lightgroup Tools button set.

    Shared by every panel so the 3D View and Compositor sidebars can't drift
    apart the way they did previously (the compositor was missing two buttons).
    """
    layout.label(text="Setup:")
    layout.operator("lightgroup.clear_all_lightgroups", icon='X', text="Clear All Lightgroups")
    layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")
    layout.operator("lightgroup.assign_to_lightgroup", icon='LINKED', text="Add Selected to Lightgroup")

    layout.separator()

    solo.draw_solo(layout, context)

    layout.separator()

    layout.label(text="Compositor:")
    layout.operator("lightgroup.denoise_all_cycles", icon='NODE_COMPOSITING')
    output_check.draw_status(layout, context)

    layout.separator()

    # Support: one click writes a report and opens the folder holding it, so
    # "it isn't working" can arrive with something attached. Lives here rather
    # than in a tool's own tab because it covers the whole toolkit, and this is
    # the tab the team is already in every day.
    layout.label(text="Support:")
    layout.operator("lightgroup.write_diagnostics", icon='TEXT')


class LIGHTGROUP_PT_main_panel(bpy.types.Panel):
    """Main panel for Lightgroup Tools in 3D Viewport"""
    bl_label = "Lightgroup Tools"
    bl_idname = "LIGHTGROUP_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Lightgroups'

    def draw(self, context):
        _draw_tools(self.layout, context)


class LIGHTGROUP_PT_compositor_panel(bpy.types.Panel):
    """Main panel for Lightgroup Tools in Compositor"""
    bl_label = "Lightgroup Tools"
    bl_idname = "LIGHTGROUP_PT_compositor_panel"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Lightgroups'

    @classmethod
    def poll(cls, context):
        # Only show in compositor
        return context.space_data.tree_type == 'CompositorNodeTree'

    def draw(self, context):
        _draw_tools(self.layout, context)


class LIGHTGROUP_PT_viewlayer_panel(bpy.types.Panel):
    """Panel in View Layer properties"""
    bl_label = "Lightgroup Tools"
    bl_idname = "LIGHTGROUP_PT_viewlayer_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "view_layer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.operator("lightgroup.clear_all_lightgroups", icon='X', text="Clear All Lightgroups")
        layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")


# Registered by the addon's top-level __init__, in this order.
classes = (
    LIGHTGROUP_PT_main_panel,
    LIGHTGROUP_PT_compositor_panel,
    LIGHTGROUP_PT_viewlayer_panel,
)
