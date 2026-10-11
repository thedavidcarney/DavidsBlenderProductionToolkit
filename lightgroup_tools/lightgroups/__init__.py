"""Lightgroup tools: the production workhorse.

Sidebar tab 'Lightgroups' in the 3D View and Compositor, plus a short subset in
View Layer properties. Other tools in this toolkit get their own subpackage and
their own tab -- they do not add buttons here.

`classes` is built at import time, so the top-level reload guard must reload
this package's submodules BEFORE reloading this package.
"""

from . import operators
from . import solo
from . import panels

classes = (
    operators.LIGHTGROUP_OT_clear_all_lightgroups,
    operators.LIGHTGROUP_OT_create_for_each_light,
    operators.LIGHTGROUP_OT_denoise_all_cycles,
    operators.LIGHTGROUP_OT_assign_to_lightgroup,
) + solo.classes + panels.classes


def register_properties():
    solo.register_properties()


def unregister_properties():
    solo.unregister_properties()
