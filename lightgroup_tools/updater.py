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
    """Download the update (restart Blender to install)"""
    bl_idname = "lightgroup.download_update"
    bl_label = "Download Update"
    
    def execute(self, context):
        if not context.scene.lightgroup_update_available:
            self.report({'WARNING'}, "No update available")
            return {'CANCELLED'}
        
        download_url = context.scene.lightgroup_download_url
        
        try:
            self.report({'INFO'}, "Downloading update...")
            
            # Download to temp location
            temp_zip = os.path.join(bpy.app.tempdir, "lightgroup_tools_update.zip")
            urllib.request.urlretrieve(download_url, temp_zip)
            
            # Extract
            extract_dir = os.path.join(bpy.app.tempdir, "lightgroup_extract")
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Find addon folder
            extracted_contents = os.listdir(extract_dir)
            if not extracted_contents:
                self.report({'ERROR'}, "Downloaded archive is empty")
                return {'CANCELLED'}
            
            root_folder = extracted_contents[0]
            addon_source = os.path.join(extract_dir, root_folder, "lightgroup_tools")
            
            if not os.path.exists(addon_source):
                self.report({'ERROR'}, "Could not find addon folder in archive")
                return {'CANCELLED'}
            
            # Store the path for installation on restart
            context.scene.lightgroup_staged_update_path = addon_source
            context.scene.lightgroup_update_downloaded = True
            
            self.report({'INFO'}, "Update downloaded! Restart Blender to install.")
            return {'FINISHED'}
                    
        except Exception as e:
            self.report({'ERROR'}, f"Error downloading update: {e}")
            return {'CANCELLED'}


class LIGHTGROUP_OT_install_update(bpy.types.Operator):
    """Install the downloaded update (will uninstall and reinstall the addon)"""
    bl_idname = "lightgroup.install_update"
    bl_label = "Install Update Now"
    
    def execute(self, context):
        if not context.scene.lightgroup_update_downloaded:
            self.report({'WARNING'}, "No update downloaded")
            return {'CANCELLED'}
        
        staged_path = context.scene.lightgroup_staged_update_path
        
        if not os.path.exists(staged_path):
            self.report({'ERROR'}, "Staged update path not found")
            return {'CANCELLED'}
        
        try:
            # Get the current addon directory
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            parent_dir = os.path.dirname(addon_dir)
            addon_folder_name = os.path.basename(addon_dir)
            
            # Create a backup
            backup_dir = addon_dir + "_backup"
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
            shutil.copytree(addon_dir, backup_dir)
            
            # Try to remove old addon files
            try:
                # Remove all files except __pycache__
                for item in os.listdir(addon_dir):
                    if item == "__pycache__":
                        continue
                    item_path = os.path.join(addon_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                
                # Copy new files
                for item in os.listdir(staged_path):
                    s = os.path.join(staged_path, item)
                    d = os.path.join(addon_dir, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
                
                # Clean up
                context.scene.lightgroup_update_downloaded = False
                context.scene.lightgroup_staged_update_path = ""
                context.scene.lightgroup_update_available = False
                
                # Remove backup if successful
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                
                self.report({'INFO'}, "Update installed! Please save your work and restart Blender.")
                return {'FINISHED'}
                
            except PermissionError as e:
                # Restore backup if something went wrong
                if os.path.exists(backup_dir):
                    shutil.rmtree(addon_dir)
                    shutil.copytree(backup_dir, addon_dir)
                self.report({'ERROR'}, f"Could not install update: {e}. Please restart Blender and try again.")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Error installing update: {e}")
            return {'CANCELLED'}


# Add properties to store update info
def register_updater_properties():
    bpy.types.Scene.lightgroup_update_available = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.lightgroup_latest_version = bpy.props.StringProperty(default="")
    bpy.types.Scene.lightgroup_download_url = bpy.props.StringProperty(default="")
    bpy.types.Scene.lightgroup_update_downloaded = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.lightgroup_staged_update_path = bpy.props.StringProperty(default="")

def unregister_updater_properties():
    del bpy.types.Scene.lightgroup_update_available
    del bpy.types.Scene.lightgroup_latest_version
    del bpy.types.Scene.lightgroup_download_url
    del bpy.types.Scene.lightgroup_update_downloaded
    del bpy.types.Scene.lightgroup_staged_update_path


# Handler to install updates on startup
@bpy.app.handlers.persistent
def install_update_on_load(dummy):
    """Check if there's a staged update to install on startup"""
    scene = bpy.context.scene
    if hasattr(scene, 'lightgroup_update_downloaded') and scene.lightgroup_update_downloaded:
        # Trigger the install operator
        bpy.ops.lightgroup.install_update()


def register_handlers():
    if install_update_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(install_update_on_load)

def unregister_handlers():
    if install_update_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(install_update_on_load)