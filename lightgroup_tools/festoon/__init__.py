"""Festoon Clicker: click-to-place festoon light strings.

Its own sidebar tab ('Festoon Clicker'), separate from Lightgroups.

Module map:
    picking.py    visibility-aware viewport raycasting
    shape.py      chord-frame maths and the sag shape function
    nodes.py      builds the Festoon Strand geometry node group
    rig.py        creates the strand mesh, empties and collection
    operators.py  the modal placement operator
    panels.py     sidebar UI

`classes` is built at import time, so the addon's reload guard must reload
these submodules BEFORE reloading this package.
"""

from . import nodes
from . import picking
from . import shape
from . import rig
from . import operators
from . import panels

classes = operators.classes + panels.classes


def register():
    operators.register_properties()


def unregister():
    operators.unregister_properties()
