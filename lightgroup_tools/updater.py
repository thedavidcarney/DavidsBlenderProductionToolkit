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
        
        print(f"Checking for updates from: {github_user}/{github_repo}")
        
        # Get current version from bl_info
        from . import bl_info
        current_version = bl_info["version"]
        print(f"Current version: {current_version}")
        
        # Get preferences safely
        addon_name = __name__.partition('.')[0]
        if addon_name not in context.preferences.addons:
            self.report({'ERROR'}, "Could not access addon preferences")
            return {'CANCELLED'}
        
        prefs = context.preferences.addons[addon_name].preferences
        
        try:
            # Check GitHub API for latest release
            url = f"https://api.github.com/repos/{github_user}/{github_repo}/releases/latest"
            print(f"Fetching: {url}")
            
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode())
            
            print(f"Response received, tag: {data.get('tag_name', 'NOT FOUND')}")
                
            latest_version_str = data["tag_name"].lstrip("v")
            latest_version = tuple(map(int, latest_version_str.split(".")))
            
            print(f"Latest version: {latest_version}")
            
            if latest_version > current_version:
                message = f"New version available: v{latest_version_str} (current: v{'.'.join(map(str, current_version))})"
                print(message)
                self.report({'INFO'}, message)
                
                # Store update info in preferences (persists!)
                prefs.update_available = True
                prefs.latest_version = latest_version_str
                prefs.download_url = data["zipball_url"]
                
                # Save preferences to disk
                bpy.ops.wm.save_userpref()
                
                return {'FINISHED'}
            else:
                message = "You have the latest version!"
                print(message)
                self.report({'INFO'}, message)
                prefs.update_available = False
                
                # Save preferences to disk
                bpy.ops.wm.save_userpref()
                
                return {'FINISHED'}
                
        except urllib.error.HTTPError as e:
            error_msg = f"HTTP error {e.code}: {e.reason}"
            print(f"ERROR: {error_msg}")
            self.report({'ERROR'}, f"Could not check for updates: {error_msg}")
            return {'CANCELLED'}
        except urllib.error.URLError as e:
            error_msg = f"URL error: {e.reason}"
            print(f"ERROR: {error_msg}")
            self.report({'ERROR'}, f"Could not check for updates: {error_msg}")
            return {'CANCELLED'}
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            print(f"ERROR: {error_msg}")
            self.report({'ERROR'}, f"Error checking updates: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class LIGHTGROUP_OT_download_update(bpy.types.Operator):
    """Download the update (restart Blender to install)"""
    bl_idname = "lightgroup.download_update"
    bl_label = "Download Update"
    
    def execute(self, context):
        # Get preferences safely
        addon_name = __name__.partition('.')[0]
        if addon_name not in context.preferences.addons:
            self.report({'ERROR'}, "Could not access addon preferences")
            return {'CANCELLED'}
        
        prefs = context.preferences.addons[addon_name].preferences
        
        if not prefs.update_available:
            self.report({'WARNING'}, "No update available")
            return {'CANCELLED'}
        
        download_url = prefs.download_url
        
        try:
            self.report({'INFO'}, "Downloading update...")
            
            # Use a persistent location instead of temp
            # Store in Blender's config directory
            import tempfile
            persistent_dir = os.path.join(os.path.dirname(bpy.utils.user_resource('CONFIG')), "lightgroup_tools_update")
            os.makedirs(persistent_dir, exist_ok=True)
            
            temp_zip = os.path.join(persistent_dir, "update.zip")
            urllib.request.urlretrieve(download_url, temp_zip)
            
            # Extract
            extract_dir = os.path.join(persistent_dir, "extracted")
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
            
            # Store the path in preferences (persists!)
            prefs.staged_update_path = addon_source
            prefs.update_downloaded = True
            
            # CRITICAL: Save preferences to disk so they persist!
            bpy.ops.wm.save_userpref()
            
            self.report({'INFO'}, "Update downloaded! Restart Blender to install.")
            return {'FINISHED'}
                    
        except Exception as e:
            self.report({'ERROR'}, f"Error downloading update: {e}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


# Handler to install updates on startup
@bpy.app.handlers.persistent
def install_update_on_load(dummy):
    """Check if there's a staged update to install on startup"""
    print("Lightgroup Tools: Checking for staged updates...")
    try:
        # Get preferences
        addon_name = __name__.partition('.')[0]
        if addon_name not in bpy.context.preferences.addons:
            print("Lightgroup Tools: Addon not in preferences yet")
            return
        
        prefs = bpy.context.preferences.addons[addon_name].preferences
        
        # Debug info
        print(f"Lightgroup Tools: Update downloaded flag: {prefs.update_downloaded}")
        
        if prefs.update_downloaded:
            staged_path = prefs.staged_update_path
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
                
                # Clean up flags in preferences
                prefs.update_downloaded = False
                prefs.staged_update_path = ""
                prefs.update_available = False
                
                # Save preferences after cleanup
                bpy.ops.wm.save_userpref()
                
                print("Lightgroup Tools: Update installed successfully!")
                print("Lightgroup Tools: Reloading add-on...")
                
                # Reload the add-on to use the new code
                addon_name = __name__.partition('.')[0]
                try:
                    bpy.ops.preferences.addon_disable(module=addon_name)
                    bpy.ops.preferences.addon_enable(module=addon_name)
                    print("Lightgroup Tools: Add-on reloaded with new version!")
                except Exception as reload_error:
                    print(f"Lightgroup Tools: Could not reload add-on: {reload_error}")
                    print("Lightgroup Tools: Please restart Blender one more time to use the new version.")
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