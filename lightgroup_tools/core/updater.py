import bpy
import sys
import urllib.request
import urllib.error
import json
import zipfile
import os
import shutil
import threading
import datetime
from pathlib import Path


# Module-level guard so the auto-check only runs once per Blender session.
# load_post fires on every file open, but we only want to nag once per launch.
_auto_check_done_this_session = False


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

    # ISO timestamp of the most recent auto-check, used to throttle to once per
    # 24 hours so we don't hammer GitHub's unauthenticated API rate limit.
    last_auto_check: bpy.props.StringProperty(default="")


class LIGHTGROUP_OT_check_updates(bpy.types.Operator):
    """Check for add-on updates on GitHub"""
    bl_idname = "lightgroup.check_updates"
    bl_label = "Check for Updates"
    
    def execute(self, context):
        # Your GitHub repo info
        github_user = "thedavidcarney"
        github_repo = "DavidsBlenderProductionToolkit"
        
        print(f"Checking for updates from: {github_user}/{github_repo}")
        
        # Get current version from bl_info. Reached through sys.modules rather
        # than a relative import, so this keeps working wherever updater.py sits
        # in the package tree -- it moved into core/ during the restructure, and
        # `from . import bl_info` would have started resolving against core/.
        # Matches how the other bl_info reads in this file already work.
        addon_name = __name__.partition('.')[0]
        current_version = sys.modules[addon_name].bl_info["version"]
        print(f"Current version: {current_version}")

        # Get preferences safely
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
                message = f"You have the latest version (v{latest_version_str})"
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

            # Prompt the user to restart Blender now (or later).
            _schedule_dialog("lightgroup.restart_dialog")
            
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
    """Check if there's a staged update to install on startup, then trigger
    the once-per-session auto-check for new updates.
    """
    print("Lightgroup Tools: Checking for staged updates...")
    try:
        _maybe_auto_check_on_startup()
    except Exception as e:
        print(f"Lightgroup Tools: auto-check trigger failed: {e}")

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

            # Get the current addon directory.
            #
            # This MUST resolve to the top-level package dir. Deriving it from
            # this file's __file__ was correct while updater.py sat at the top
            # level, but it now lives in core/ -- dirname(__file__) would point
            # at lightgroup_tools/core/, and we would install the update inside
            # core/ while backing up only core/. Go through the package module
            # instead, which is location-independent.
            addon_dir = None
            addon_module = sys.modules.get(addon_name)
            if addon_module is not None and getattr(addon_module, "__file__", None):
                addon_dir = os.path.dirname(os.path.realpath(addon_module.__file__))
            if not addon_dir or not os.path.isdir(addon_dir):
                print("Lightgroup Tools: Could not resolve the addon directory; aborting install")
                return
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

            # Remove modules that the previous layout had but this build doesn't.
            #
            # The copy loop above only touches paths that exist in the NEW build,
            # so anything dropped between versions lingers forever. Up to v1.0.15
            # updater.py and operators.py sat flat at the top level; they now live
            # in core/ and lightgroups/. Without this, that one upgrade leaves two
            # dead modules sitting beside the new packages -- inert, since nothing
            # imports them, but exactly the shape that causes import confusion for
            # whoever opens the folder next.
            #
            # Deliberately an explicit list rather than "mirror the staged tree":
            # a general delete-what's-missing pass could wipe a live install if a
            # staged build were ever partial, and the updater is the one thing
            # that must never fail destructively.
            for orphan in ("updater.py", "operators.py"):
                orphan_path = os.path.join(addon_dir, orphan)
                if os.path.isfile(orphan_path) and not os.path.exists(os.path.join(staged_path, orphan)):
                    try:
                        os.remove(orphan_path)
                        print(f"Lightgroup Tools: Removed pre-restructure module {orphan}")
                    except Exception as orphan_error:
                        print(f"Lightgroup Tools: Warning - could not remove {orphan}: {orphan_error}")

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

                # CRITICAL: evict the addon's cached module objects from
                # sys.modules. Without this, addon_enable would just return the
                # OLD modules from cache and re-register the OLD code, even
                # though new files are already on disk. The user would then see
                # an error on next startup (e.g. classes referenced by the new
                # __init__.py but not present in the cached old updater.py),
                # leaving the addon disabled and unrecoverable without manual
                # delete + reinstall.
                for mod_name in list(sys.modules.keys()):
                    if mod_name == addon_name or mod_name.startswith(addon_name + "."):
                        del sys.modules[mod_name]

                # Belt-and-suspenders: ask Blender's addon registry to re-scan
                # so it sees the new file state too. CGCookie's updater relies
                # on this alone (no sys.modules eviction); we do both.
                try:
                    bpy.ops.preferences.addon_refresh()
                except Exception as refresh_error:
                    print(f"Lightgroup Tools: addon_refresh failed (non-fatal): {refresh_error}")

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


# --------------------------------------------------------------------------- #
# Auto-check on startup
# --------------------------------------------------------------------------- #

_AUTO_CHECK_THROTTLE_SECONDS = 24 * 60 * 60  # 24 hours


def _maybe_auto_check_on_startup():
    """Triggered from load_post on Blender startup. Decides whether to run an
    auto-check and shows the update dialog if there's already a known update
    waiting (and one isn't already downloaded).
    """
    global _auto_check_done_this_session
    if _auto_check_done_this_session:
        return
    _auto_check_done_this_session = True

    try:
        addon_name = "lightgroup_tools"
        if addon_name not in bpy.context.preferences.addons:
            return
        prefs = bpy.context.preferences.addons[addon_name].preferences

        # If an update is already downloaded and waiting to install, the
        # restart-on-startup banner / install handler covers it. Don't pop
        # an additional dialog over that.
        if prefs.update_downloaded:
            return

        # If a previous check already found an update, surface it now without
        # re-checking GitHub. The dialog will reappear next session unless the
        # user acts on it.
        if prefs.update_available:
            _schedule_dialog("lightgroup.update_dialog")

        # Throttle: only hit GitHub if the last auto-check was > 24h ago
        if prefs.last_auto_check:
            try:
                last = datetime.datetime.fromisoformat(prefs.last_auto_check)
                if (datetime.datetime.now() - last).total_seconds() < _AUTO_CHECK_THROTTLE_SECONDS:
                    return
            except ValueError:
                pass  # bad timestamp → fall through and check anyway

        # Spawn a background thread so the HTTP call doesn't block startup
        threading.Thread(target=_perform_check_in_thread, daemon=True).start()
    except Exception as e:
        print(f"Lightgroup Tools: auto-check setup failed: {e}")


def _perform_check_in_thread():
    """Runs in a background thread. Hits GitHub's releases API and schedules a
    main-thread callback to apply the result (Blender's API isn't thread-safe).
    """
    try:
        github_user = "thedavidcarney"
        github_repo = "DavidsBlenderProductionToolkit"
        url = f"https://api.github.com/repos/{github_user}/{github_repo}/releases/latest"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())

        latest_version_str = data["tag_name"].lstrip("v")
        try:
            latest_version = tuple(map(int, latest_version_str.split(".")))
        except ValueError:
            print(f"Lightgroup Tools: auto-check ignored malformed tag '{data['tag_name']}'")
            return

        zipball_url = data["zipball_url"]

        # Hand back to main thread via a one-shot timer
        def apply_result():
            _apply_check_result(latest_version_str, latest_version, zipball_url)
            return None

        bpy.app.timers.register(apply_result, first_interval=0.1)
    except Exception as e:
        print(f"Lightgroup Tools: background auto-check failed: {e}")


def _apply_check_result(latest_version_str, latest_version, zipball_url):
    """Runs on the main thread. Updates prefs and shows the dialog if newer."""
    try:
        addon_name = "lightgroup_tools"
        if addon_name not in bpy.context.preferences.addons:
            return
        prefs = bpy.context.preferences.addons[addon_name].preferences

        # Read current version from the loaded module's bl_info
        current_version = (0, 0, 0)
        if addon_name in sys.modules and hasattr(sys.modules[addon_name], "bl_info"):
            current_version = sys.modules[addon_name].bl_info.get("version", (0, 0, 0))

        prefs.last_auto_check = datetime.datetime.now().isoformat()

        if latest_version > current_version:
            prefs.update_available = True
            prefs.latest_version = latest_version_str
            prefs.download_url = zipball_url
            print(f"Lightgroup Tools: auto-check found v{latest_version_str} (current: v{'.'.join(map(str, current_version))})")
            if not prefs.update_downloaded:
                _schedule_dialog("lightgroup.update_dialog")
        else:
            prefs.update_available = False
            print(f"Lightgroup Tools: auto-check confirmed up to date (v{latest_version_str})")

        bpy.ops.wm.save_userpref()
    except Exception as e:
        print(f"Lightgroup Tools: applying auto-check result failed: {e}")


def _schedule_dialog(operator_idname):
    """Defer a dialog operator to run on the next main-thread tick. Calling
    operators directly from load_post / from a thread is unreliable; the timer
    indirection gives Blender a clean context to work with.
    """
    op_path = operator_idname.split(".")
    def show():
        try:
            op = getattr(getattr(bpy.ops, op_path[0]), op_path[1])
            op('INVOKE_DEFAULT')
        except Exception as e:
            print(f"Lightgroup Tools: could not show {operator_idname}: {e}")
        return None  # don't repeat
    bpy.app.timers.register(show, first_interval=0.5)


# --------------------------------------------------------------------------- #
# Dialog operators
# --------------------------------------------------------------------------- #

class LIGHTGROUP_OT_update_dialog(bpy.types.Operator):
    """Popup shown when an update is available — Update Now or Ignore"""
    bl_idname = "lightgroup.update_dialog"
    bl_label = "Lightgroup Tools update available"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        layout = self.layout
        addon_name = __name__.partition('.')[0]
        prefs = context.preferences.addons[addon_name].preferences

        current = "?"
        if addon_name in sys.modules and hasattr(sys.modules[addon_name], "bl_info"):
            current = ".".join(map(str, sys.modules[addon_name].bl_info.get("version", ())))

        layout.label(text=f"Lightgroup Tools v{prefs.latest_version} is available", icon='INFO')
        layout.label(text=f"You are running v{current}")
        layout.separator()
        row = layout.row()
        row.operator("lightgroup.download_update", text="Update Now", icon='IMPORT')
        row.operator("lightgroup.close_dialog", text="Ignore")

    def execute(self, context):
        return {'FINISHED'}


class LIGHTGROUP_OT_restart_dialog(bpy.types.Operator):
    """Popup shown after a successful update download — Restart Now or Later"""
    bl_idname = "lightgroup.restart_dialog"
    bl_label = "Restart Blender"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Update downloaded.", icon='CHECKMARK')
        layout.label(text="Restart Blender to install.")
        layout.separator()
        row = layout.row()
        # wm.quit_blender prompts about unsaved changes before exiting.
        row.operator("wm.quit_blender", text="Restart Now", icon='RECOVER_LAST')
        row.operator("lightgroup.close_dialog", text="Later")

    def execute(self, context):
        return {'FINISHED'}


class LIGHTGROUP_OT_close_dialog(bpy.types.Operator):
    """No-op used as the dismiss button inside our popup dialogs"""
    bl_idname = "lightgroup.close_dialog"
    bl_label = "Close"

    def execute(self, context):
        return {'FINISHED'}


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
