"""Sidebar panels for the Lightgroups tool.

Moved verbatim out of the addon's top-level __init__.py during the package
restructure. Nothing about what these draw has changed -- same tab, same
buttons, same order.
"""

import bpy


def _get_prefs(context):
    """Fetch addon preferences, or None if the addon isn't registered under the expected name."""
    # partition on the first dot, so this yields the top-level package name no
    # matter how deep in the package tree this module lives.
    addon_name = __name__.partition('.')[0]
    if addon_name in context.preferences.addons:
        return context.preferences.addons[addon_name].preferences
    return None


def _draw_tools(layout, context):
    """Draw the full Lightgroup Tools button set.

    Shared by every panel so the 3D View and Compositor sidebars can't drift
    apart the way they did previously (the compositor was missing two buttons).
    """
    prefs = _get_prefs(context)

    layout.label(text="Setup:")
    layout.operator("lightgroup.clear_all_lightgroups", icon='X', text="Clear All Lightgroups")
    layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")
    layout.operator("lightgroup.assign_to_lightgroup", icon='LINKED', text="Add Selected to Lightgroup")

    layout.separator()

    layout.label(text="Compositor:")
    layout.operator("lightgroup.denoise_all_cycles", icon='NODE_COMPOSITING')

    layout.separator()

    # Update section
    layout.label(text="Updates:")

    if prefs:
        # Sticky restart-required notice from a recent in-session install
        if prefs.update_just_installed:
            box = layout.box()
            version_label = f"Update v{prefs.last_installed_version} installed" if prefs.last_installed_version else "Update installed"
            box.label(text=version_label, icon='CHECKMARK')
            box.label(text="Restart Blender for full effect", icon='INFO')
            box.operator("lightgroup.dismiss_install_notice", icon='X')

    row = layout.row()
    row.operator("lightgroup.check_updates", icon='FILE_REFRESH')

    # Show update available message and download button
    if prefs:
        if prefs.update_downloaded:
            box = layout.box()
            box.label(text="Update ready!", icon='CHECKMARK')
            box.label(text="Restart Blender to install", icon='INFO')
        elif prefs.update_available:
            box = layout.box()
            box.label(text=f"Update available: v{prefs.latest_version}", icon='INFO')
            box.operator("lightgroup.download_update", icon='IMPORT')

        # Rollback to the backup of the previous version
        if prefs.backup_available:
            row = layout.row()
            restore_text = f"Restore Previous Version (v{prefs.backup_version})" if prefs.backup_version else "Restore Previous Version"
            row.operator("lightgroup.restore_backup", icon='RECOVER_LAST', text=restore_text)


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
