"""Custom-property tags shared between tools.

These live in core rather than in the tool that writes them, because the tool
that READS them is a different subpackage. `lightgroups` needs to recognise a
festoon strand, but importing `festoon` from `lightgroups` would couple two
features that are otherwise deliberately independent -- and would mean
disabling one tool breaks the other.

A tag is just a string key set as a custom property on an object.
"""

# Marks a festoon strand mesh.
#
# Festoon strands emit light through INSTANCED geometry, so the strand object
# itself has no material slots. Any scan that looks for emissive materials in
# an object's slots -- which is how create_for_each_light finds mesh emitters --
# sees nothing and silently skips every strand in the scene. The tag is what
# makes them findable.
FESTOON_STRAND = "festoon_strand"

# Marks the start/end/sag empties belonging to a strand. Empties never emit, so
# this is only used to keep them out of viewport picking.
FESTOON_CONTROL = "festoon_control"

# Marks an object that exists only to be INSTANCED by another tool -- a bulb
# source sitting in Festoon Bulbs, for example.
#
# These usually carry emissive materials, so a material-slot scan happily
# creates a lightgroup for each one. That group would be pure noise: the source
# is excluded from the view layer and contributes nothing to the render, while
# the light actually comes from the strand instancing it. Skip anything tagged.
FESTOON_BULB_SOURCE = "festoon_bulb_source"
