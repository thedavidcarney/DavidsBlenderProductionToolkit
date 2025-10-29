import bpy
import urllib.request
import urllib.error
import json
import zipfile
import os
import shutil
from pathlib import Path

class LIGHTGROUP_OT_check_updates(bpy.types.Operator):
    """Check for add-on updates on GitHub"""
    bl_idname = "lightgroup.check_updates"
    bl_label = "Check for Updates"
    
    def execute(self, context):
        # Your GitHub repo info
        github_user = "thedavidcarney"
        github_repo = "DavidsBlenderProductionToolkit"
        
        # Get current version from bl_info
        from . import bl_info
        current_version = bl_info["version"]
        
        try:
            # Check GitHub API for latest release
            url = f"https://api.github.com/repos/{github_user}/{github_repo}/releases/latest"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
                
            latest_version_str = data["tag_name"].lstrip("v")
            latest_version = tuple(map(int, latest_version_str.split(".")))
            
            if latest_version > current_version:
                message = f"New version available: v{latest_version_str} (current: v{'.'.join(map(str, current_version))})"
                self.report({'INFO'}, message)
                
                # Store update info in scene for the UI
                context.scene.lightgroup_update_available = True
                context.scene.lightgroup_latest_version = latest_version_str
                context.scene.lightgroup_download_url = data["zipball_url"]
                
                return {'FINISHED'}
            else:
                self.report({'INFO'}, "You have the latest version!")
                context.scene.lightgroup_update_available = False
                return {'FINISHED'}
                
        except urllib.error.URLError as e:
            self.report({'ERROR'}, f"Could not check for updates: {e}")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error checking updates: {e}")
            return {'CANCELLED'}


class LIGHTGROUP_OT_download_update(bpy.types.Operator):
    """Download and install the latest version"""
    bl_idname = "lightgroup.download_update"
    bl_label = "Download & Install Update"
    
    def execute(self, context):
        if not context.scene.lightgroup_update_available:
            self.report({'WARNING'}, "No update available")
            return {'CANCELLED'}
        
        download_url = context.scene.lightgroup_download_url
        
        try:
            # Download the zip file
            self.report({'INFO'}, "Downloading update...")
            temp_zip = os.path.join(bpy.app.tempdir, "lightgroup_tools_update.zip")
            
            urllib.request.urlretrieve(download_url, temp_zip)
            
            # Get the add-on installation path
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            
            self.report({'INFO'}, "Installing update... Please restart Blender after this completes.")
            
            # Extract and replace files
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                # GitHub zipballs have a root folder, we need to handle that
                zip_contents = zip_ref.namelist()
                root_folder = zip_contents[0].split('/')[0]
                
                # Extract to temp location first
                temp_extract = os.path.join(bpy.app.tempdir, "lightgroup_extract")
                zip_ref.extractall(temp_extract)
                
                # Find the actual addon folder inside
                extracted_addon = os.path.join(temp_extract, root_folder, "lightgroup_tools")
                
                if os.path.exists(extracted_addon):
                    # Copy files from extracted addon to current addon location
                    for item in os.listdir(extracted_addon):
                        s = os.path.join(extracted_addon, item)
                        d = os.path.join(addon_dir, item)
                        if os.path.isdir(s):
                            if os.path.exists(d):
                                shutil.rmtree(d)
                            shutil.copytree(s, d)
                        else:
                            shutil.copy2(s, d)
                    
                    # Cleanup
                    os.remove(temp_zip)
                    shutil.rmtree(temp_extract)
                    
                    self.report({'INFO'}, "Update installed! Please restart Blender to complete the update.")
                    context.scene.lightgroup_update_available = False
                    return {'FINISHED'}
                else:
                    self.report({'ERROR'}, "Could not find addon folder in downloaded zip")
                    return {'CANCELLED'}
                    
        except Exception as e:
            self.report({'ERROR'}, f"Error installing update: {e}")
            return {'CANCELLED'}


# Add properties to store update info
def register_updater_properties():
    bpy.types.Scene.lightgroup_update_available = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.lightgroup_latest_version = bpy.props.StringProperty(default="")
    bpy.types.Scene.lightgroup_download_url = bpy.props.StringProperty(default="")

def unregister_updater_properties():
    del bpy.types.Scene.lightgroup_update_available
    del bpy.types.Scene.lightgroup_latest_version
    del bpy.types.Scene.lightgroup_download_url