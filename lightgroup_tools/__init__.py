bl_info = {
    "name": "David's Production Toolkit",
    "author": "David Carney",
    "version": (0, 0, 6),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > Lightgroup Tools",
    "description": "Tools for managing lightgroups and compositor setup",
    "category": "Lighting",
}


import bpy
from . import operators
from . import updater

class LIGHTGROUP_PT_main_panel(bpy.types.Panel):
    """Main panel for Lightgroup Tools in 3D Viewport"""
    bl_label = "Lightgroup Tools"
    bl_idname = "LIGHTGROUP_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Lightgroups'
    
    def draw(self, context):
        layout = self.layout
        
        # Get preferences
        prefs = context.preferences.addons[__name__.partition('.')[0]].preferences
        
        layout.label(text="Setup:")
        layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")
        layout.operator("lightgroup.assign_to_lightgroup", icon='LINKED', text="Add Selected to Lightgroup")
        
        layout.separator()
        
        layout.label(text="Compositor:")
        layout.operator("lightgroup.denoise_all_cycles", icon='NODE_COMPOSITING')
        
        layout.separator()
        
        # Update section
        layout.label(text="Updates:")
        row = layout.row()
        row.operator("lightgroup.check_updates", icon='FILE_REFRESH')
        
        # Show update available message and download button
        if prefs.update_downloaded:
            box = layout.box()
            box.label(text="Update ready!", icon='CHECKMARK')
            box.label(text="Restart Blender to install", icon='INFO')
        elif prefs.update_available:
            box = layout.box()
            box.label(text=f"Update available: v{prefs.latest_version}", icon='INFO')
            box.operator("lightgroup.download_update", icon='IMPORT')

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
        layout = self.layout
        
        layout.label(text="Setup:")
        layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")
        
        layout.separator()
        
        layout.label(text="Compositor:")
        layout.operator("lightgroup.denoise_all_cycles", icon='NODE_COMPOSITING')
        
        layout.separator()
        
        # Update section
        layout.label(text="Updates:")
        row = layout.row()
        row.operator("lightgroup.check_updates", icon='FILE_REFRESH')
        
        # Show update available message and download button
        if hasattr(context.scene, 'lightgroup_update_downloaded') and context.scene.lightgroup_update_downloaded:
            box = layout.box()
            box.label(text="Update ready!", icon='CHECKMARK')
            box.label(text="Restart Blender to install", icon='INFO')
        elif context.scene.lightgroup_update_available:
            box = layout.box()
            box.label(text=f"Update available: v{context.scene.lightgroup_latest_version}", icon='INFO')
            box.operator("lightgroup.download_update", icon='IMPORT')


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
        layout.operator("lightgroup.create_for_each_light", icon='LIGHT', text="Create Lightgroups for Each Light")


classes = (
    operators.LIGHTGROUP_OT_create_for_each_light,
    operators.LIGHTGROUP_OT_denoise_all_cycles,
    operators.LIGHTGROUP_OT_assign_to_lightgroup,
    updater.LIGHTGROUP_OT_check_updates,
    updater.LIGHTGROUP_OT_download_update,
    LIGHTGROUP_PT_main_panel,
    LIGHTGROUP_PT_compositor_panel,
    LIGHTGROUP_PT_viewlayer_panel,
)

def register():
    updater.register_updater_properties()
    updater.register_handlers()
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    updater.unregister_handlers()
    updater.unregister_updater_properties()

if __name__ == "__main__":
    register()