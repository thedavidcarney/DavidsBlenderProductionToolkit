import bpy
import sys
import urllib.request
import urllib.error
import json
import zipfile
import os
import shutil
from pathlib import Path


def _get_update_dir():
    """Path to the staging dir where downloaded updates are extracted."""
    return os.path.join(os.path.dirname(bpy.utils.user_resource('CONFIG')), "lightgroup_tools_update")


def _get_backup_dir():
    """Path to the backup dir holding the previous addon version for rollback."""
    return os.path.join(os.path.dirname(bpy.utils.user_resource('CONFIG')), "lightgroup_tools_backup")


# Preferences to store update info (persists across sessions)
class LightgroupToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__.partition('.')[0]

    update_available: bpy.props.BoolProperty(default=False)
    latest_version: bpy.props.StringProperty(default="")
    download_url: bpy.props.StringProperty(default="")
    update_downloaded: bpy.props.BoolProperty(default=False)
    staged_update_path: bpy.props.StringProperty(default="")
    # The version string of whatever is currently staged in staged_update_path
    # (set when downloading or queuing a restore, read by the install handler).
    staged_update_version: bpy.props.StringProperty(default="")

    # Backup of the pre-update addon files, for rollback
    backup_available: bpy.props.BoolProperty(default=False)
    backup_version: bpy.props.StringProperty(default="")

    # Sticky banner asking user to restart after an in-session update install
    update_just_installed: bpy.props.BoolProperty(default=False)
    last_installed_version: bpy.props.StringProperty(default="")


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
            try:
                latest_version = tuple(map(int, latest_version_str.split(".")))
            except ValueError:
                msg = f"Couldn't parse release tag '{data['tag_name']}' as a version. Tags must be vX.Y.Z (digits only)."
                print(f"ERROR: {msg}")
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}
            
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

            persistent_dir = _get_update_dir()
            os.makedirs(persistent_dir, exist_ok=True)

            temp_zip = os.path.join(persistent_dir, "update.zip")
            urllib.request.urlretrieve(download_url, temp_zip)

            # Validate the downloaded file before extracting — guards against
            # truncated/empty downloads that would otherwise stage garbage.
            if not os.path.exists(temp_zip) or os.path.getsize(temp_zip) == 0:
                self.report({'ERROR'}, "Downloaded file is empty")
                return {'CANCELLED'}
            if not zipfile.is_zipfile(temp_zip):
                self.report({'ERROR'}, "Downloaded file is not a valid zip archive")
                return {'CANCELLED'}

            # Extract
            extract_dir = os.path.join(persistent_dir, "extracted")
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)

            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # Find the addon folder inside the extracted archive.
            # GitHub zipballs wrap everything in a top-level dir like
            # `thedavidcarney-DavidsBlenderProductionToolkit-<sha>/`, so look for
            # whichever subdirectory actually contains `lightgroup_tools/`.
            extracted_contents = os.listdir(extract_dir)
            if not extracted_contents:
                self.report({'ERROR'}, "Downloaded archive is empty")
                return {'CANCELLED'}

            addon_source = None
            for entry in extracted_contents:
                candidate = os.path.join(extract_dir, entry, "lightgroup_tools")
                if os.path.isdir(candidate):
                    addon_source = candidate
                    break

            if addon_source is None:
                self.report({'ERROR'}, "Could not find 'lightgroup_tools' folder in archive")
                return {'CANCELLED'}

            # Store the path in preferences (persists!)
            prefs.staged_update_path = addon_source
            prefs.staged_update_version = prefs.latest_version
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
        addon_name = "lightgroup_tools"  # Use the actual addon name directly
        if addon_name not in bpy.context.preferences.addons:
            print("Lightgroup Tools: Addon not in preferences yet")
            return
        
        prefs = bpy.context.preferences.addons[addon_name].preferences
        
        # Debug info
        print(f"Lightgroup Tools: Update downloaded flag: {prefs.update_downloaded}")
        
        if prefs.update_downloaded:
            staged_path = prefs.staged_update_path
            print(f"Lightgroup Tools: Staged path: {staged_path}")
            
            if not os.path.exists(staged_path):
                print(f"Lightgroup Tools: Staged path does not exist: {staged_path}")
                # Clean up the flag since the path is invalid
                prefs.update_downloaded = False
                prefs.staged_update_path = ""
                bpy.ops.wm.save_userpref()
                return
            
            print(f"Lightgroup Tools: Staged path exists, installing...")

            # Get the current addon directory
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            print(f"Lightgroup Tools: Installing to: {addon_dir}")

            update_base_dir = _get_update_dir()
            backup_dir = _get_backup_dir()
            installed_version = prefs.staged_update_version

            # Determine the version we're about to replace, for the backup label.
            pre_install_version = ""
            try:
                if addon_name in sys.modules and hasattr(sys.modules[addon_name], "bl_info"):
                    pre_install_version = ".".join(map(str, sys.modules[addon_name].bl_info["version"]))
            except Exception as version_error:
                print(f"Lightgroup Tools: Could not determine current version for backup: {version_error}")

            # Back up the current addon dir before overwriting, so the user can roll back.
            # Treated as best-effort: if backup fails the install still proceeds, but the
            # user won't have rollback for this version.
            try:
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                shutil.copytree(addon_dir, backup_dir, ignore=shutil.ignore_patterns('__pycache__'))
                prefs.backup_available = True
                prefs.backup_version = pre_install_version
                print(f"Lightgroup Tools: Backed up current version (v{pre_install_version}) to: {backup_dir}")
            except Exception as backup_error:
                print(f"Lightgroup Tools: Warning - could not create backup: {backup_error}")

            # First, remove __pycache__ from addon directory
            pycache_dir = os.path.join(addon_dir, "__pycache__")
            if os.path.exists(pycache_dir):
                print(f"Lightgroup Tools: Removing old __pycache__...")
                try:
                    shutil.rmtree(pycache_dir)
                except Exception as e:
                    print(f"Lightgroup Tools: Warning - could not remove __pycache__: {e}")

            # Copy new files over
            files_copied = 0
            for item in os.listdir(staged_path):
                if item == "__pycache__":
                    continue

                s = os.path.join(staged_path, item)
                d = os.path.join(addon_dir, item)

                print(f"Lightgroup Tools: Copying {item}...")

                try:
                    if os.path.exists(d):
                        if os.path.isdir(d):
                            shutil.rmtree(d)
                        else:
                            os.remove(d)

                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)

                    files_copied += 1
                except Exception as e:
                    print(f"Lightgroup Tools: Error copying {item}: {e}")

            print(f"Lightgroup Tools: Copied {files_copied} files/folders")

            # Clean up the update directory
            print(f"Lightgroup Tools: Cleaning up update directory...")
            try:
                if os.path.exists(update_base_dir):
                    shutil.rmtree(update_base_dir)
                    print(f"Lightgroup Tools: Update directory cleaned up")
            except Exception as e:
                print(f"Lightgroup Tools: Warning - could not clean up update directory: {e}")

            # Clean up flags in preferences
            prefs.update_downloaded = False
            prefs.staged_update_path = ""
            prefs.staged_update_version = ""
            prefs.update_available = False

            # Sticky banner: tell the user a restart is recommended for full effect.
            prefs.update_just_installed = True
            prefs.last_installed_version = installed_version

            # Save preferences after cleanup
            bpy.ops.wm.save_userpref()
            
            print("Lightgroup Tools: Update installed successfully!")
            print("Lightgroup Tools: Reloading add-on...")
            
            # Reload the add-on to use the new code
            try:
                bpy.ops.preferences.addon_disable(module=addon_name)
                bpy.ops.preferences.addon_enable(module=addon_name)
                print("Lightgroup Tools: Add-on reloaded with new version!")
            except Exception as reload_error:
                print(f"Lightgroup Tools: Could not reload add-on: {reload_error}")
                print("Lightgroup Tools: The update is installed. Please restart Blender to use the new version.")
        else:
            print("Lightgroup Tools: No update to install")
    except Exception as e:
        print(f"Lightgroup Tools: Error installing update: {e}")
        import traceback
        traceback.print_exc()


class LIGHTGROUP_OT_restore_backup(bpy.types.Operator):
    """Restore the previous version of the addon from backup (requires Blender restart)"""
    bl_idname = "lightgroup.restore_backup"
    bl_label = "Restore Previous Version"

    def execute(self, context):
        addon_name = __name__.partition('.')[0]
        if addon_name not in context.preferences.addons:
            self.report({'ERROR'}, "Could not access addon preferences")
            return {'CANCELLED'}
        prefs = context.preferences.addons[addon_name].preferences

        if not prefs.backup_available:
            self.report({'WARNING'}, "No backup available")
            return {'CANCELLED'}

        backup_dir = _get_backup_dir()
        if not os.path.exists(backup_dir):
            self.report({'ERROR'}, "Backup directory missing — cannot restore")
            prefs.backup_available = False
            prefs.backup_version = ""
            bpy.ops.wm.save_userpref()
            return {'CANCELLED'}

        # Stage the backup via the same install pipeline used for updates.
        # We copy into the staging dir (rather than pointing staged_update_path
        # directly at the backup) so the install handler's cleanup step doesn't
        # delete our backup.
        try:
            update_base_dir = _get_update_dir()
            if os.path.exists(update_base_dir):
                shutil.rmtree(update_base_dir)
            os.makedirs(update_base_dir, exist_ok=True)
            staged_path = os.path.join(update_base_dir, "lightgroup_tools")
            shutil.copytree(backup_dir, staged_path)

            prefs.staged_update_path = staged_path
            prefs.staged_update_version = prefs.backup_version
            prefs.update_downloaded = True
            bpy.ops.wm.save_userpref()

            label = f"v{prefs.backup_version}" if prefs.backup_version else "previous version"
            self.report({'INFO'}, f"Restore queued ({label}). Restart Blender to apply.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Could not stage backup for restore: {e}")
            return {'CANCELLED'}


class LIGHTGROUP_OT_dismiss_install_notice(bpy.types.Operator):
    """Dismiss the 'Restart Blender' notice for the recent install"""
    bl_idname = "lightgroup.dismiss_install_notice"
    bl_label = "Dismiss"

    def execute(self, context):
        addon_name = __name__.partition('.')[0]
        if addon_name not in context.preferences.addons:
            return {'CANCELLED'}
        prefs = context.preferences.addons[addon_name].preferences
        prefs.update_just_installed = False
        prefs.last_installed_version = ""
        bpy.ops.wm.save_userpref()
        return {'FINISHED'}


def register_handlers():
    # `load_post` fires on Blender startup (after the startup .blend loads) and
    # on any subsequent file open, which is sufficient. Earlier versions also
    # registered `load_factory_startup_post` based on a misdiagnosis — that
    # event only fires for File > New / factory settings load, which is not a
    # useful update moment.
    if install_update_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(install_update_on_load)


def unregister_handlers():
    if install_update_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(install_update_on_load)
