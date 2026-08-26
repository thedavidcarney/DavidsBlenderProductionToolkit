"""Shared infrastructure for every tool in the toolkit.

Nothing tool-specific belongs here -- this is the stuff that would have to be
duplicated if the toolkit were split into separate addons. Right now that means
the self-updater and the addon preferences it stores its state in.

`classes` is built at import time, so the top-level reload guard must reload
this package's submodules BEFORE reloading this package. Otherwise the tuple
below is rebuilt from stale module objects and register() hands Blender the
previous build's classes.
"""

from . import updater

# Preferences first: the panels read prefs while drawing, and several operators
# look them up on invoke.
classes = (
    updater.LightgroupToolsPreferences,
    updater.LIGHTGROUP_OT_check_updates,
    updater.LIGHTGROUP_OT_download_update,
    updater.LIGHTGROUP_OT_restore_backup,
    updater.LIGHTGROUP_OT_dismiss_install_notice,
    updater.LIGHTGROUP_OT_update_dialog,
    updater.LIGHTGROUP_OT_restart_dialog,
    updater.LIGHTGROUP_OT_close_dialog,
)
