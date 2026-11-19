"""Shared infrastructure for every tool in the toolkit.

Nothing tool-specific belongs here -- this is the stuff that would have to be
duplicated if the toolkit were split into separate addons. Right now that is
the diagnostics report. (The self-updater lived here until v1.1.0; installs
and updates now come through IFTK, the team's tool manager.)

`classes` is built at import time, so the top-level reload guard must reload
this package's submodules BEFORE reloading this package. Otherwise the tuple
below is rebuilt from stale module objects and register() hands Blender the
previous build's classes.
"""

from . import diagnostics

classes = diagnostics.classes
