import bpy
import urllib.request
import urllib.error
import json
import zipfile
import os
import shutil
from pathlib import Path


# Preferences to store update info (persists across sessions)
class LightgroupToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__.partition('.')[0]
    
    update_available: bpy.props.BoolProperty(default=False)
    latest_version: bpy.props.StringProperty(default="")
    download_url: bpy.props.StringProperty(default="")
    update_downloaded: bpy.props.BoolProperty(default=False)
    staged_update_path: bpy.props.StringProperty(default="")


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
    print("Lightgroup Tools: Checking for staged updates...")
    try:
        scene = bpy.context.scene
        
        # Debug info
        has_downloaded = hasattr(scene, 'lightgroup_update_downloaded') and scene.lightgroup_update_downloaded
        print(f"Lightgroup Tools: Update downloaded flag: {has_downloaded}")
        
        if has_downloaded:
            staged_path = scene.lightgroup_staged_update_path
            print(f"Lightgroup Tools: Staged path: {staged_path}")
            
            if os.path.exists(staged_path):
                print(f"Lightgroup Tools: Staged path exists, installing...")
                
                # Get the current addon directory
                addon_dir = os.path.dirname(os.path.realpath(__file__))
                print(f"Lightgroup Tools: Installing to: {addon_dir}")
                
                # Copy new files over
                for item in os.listdir(staged_path):
                    if item == "__pycache__":
                        continue
                    
                    s = os.path.join(staged_path, item)
                    d = os.path.join(addon_dir, item)
                    
                    print(f"Lightgroup Tools: Copying {item}...")
                    
                    if os.path.exists(d):
                        if os.path.isdir(d):
                            shutil.rmtree(d)
                        else:
                            os.remove(d)
                    
                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
                
                # Clean up
                scene.lightgroup_update_downloaded = False
                scene.lightgroup_staged_update_path = ""
                
                print("Lightgroup Tools: Update installed successfully!")
            else:
                print(f"Lightgroup Tools: Staged path does not exist: {staged_path}")
        else:
            print("Lightgroup Tools: No update to install")
    except Exception as e:
        print(f"Lightgroup Tools: Error installing update: {e}")
        import traceback
        traceback.print_exc()


def register_handlers():
    if install_update_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(install_update_on_load)

def unregister_handlers():
    if install_update_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(install_update_on_load)