"""Builds the Festoon Strand geometry node group.

The node group is constructed in Python rather than shipped as a .blend, so
the source of truth stays text: diffable in git, reviewable, and buildable
headlessly in a test. `tests/run_festoon_test.sh` evaluates the result and
checks the actual generated geometry.

The group name carries a version (`Festoon Strand v1`). When the rig changes
shape incompatibly, bump to v2 and leave v1 alone -- strands in existing
scenes keep pointing at the group they were built with and never break under
an addon update.

Editing note: tweaking the nodes by hand inside Blender works fine for
experimenting, but those edits live only in that .blend. To make a change
permanent it has to come back into this file.

The catenary
------------
Not a real catenary, deliberately. The curve is the straight chord plus an
offset that follows a shape function:

    shape(t) = 1 - |(t - tc) / tc|^p         for t <= tc
             = 1 - |(t - tc) / (1 - tc)|^p   for t >= tc

where `tc` is where the sag empty sits along the span. shape() is 0 at both
ends and exactly 1 at `tc`, so the curve always passes through the sag empty
no matter what `p` is -- position and flatness never fight each other.

`p` comes from the sag empty's SCALE:

    p = 1    sharp V, a taut wire with a weight hung on it
    p ~ 2.2  reads as a catenary; visually indistinguishable from real cosh
    p = 5-6  flat-bottomed swag, heavy slack cable or bunting

A true cosh catenary needs solving a transcendental for the curve parameter,
and the parameter it hands back is horrible to drag. This is within about 1%
at any sag anyone would use for festoon, and both controls are direct.

Consequence worth knowing: this is NOT length-conserving. Move an endpoint
and the sag stays where you put it rather than the cable paying out slack.
That's the more predictable behaviour for placing strands quickly.
"""

import math

import bpy

from .shape import EXPONENT_MAX, EXPONENT_MIN, FLATNESS_TO_EXPONENT

GROUP_BASE_NAME = "Festoon Strand v1"

# Node names used to find the datablock-carrying nodes after the group is
# built. Blender keeps node names unique per tree, so these are stable handles.
NODE_START_INFO = "Festoon Start Info"
NODE_END_INFO = "Festoon End Info"
NODE_SAG_INFO = "Festoon Sag Info"
NODE_BULB_INFO = "Festoon Bulb Info"
NODE_BULB_COLLECTION = "Festoon Bulb Collection"
NODE_CABLE_MATERIAL = "Festoon Cable Material"

# FLATNESS_TO_EXPONENT / EXPONENT_MIN / EXPONENT_MAX are imported from shape.py
# so the node group and the viewport preview use identical numbers.

# Full-strength random tilt, in degrees, when Random Tilt is 1.0.
MAX_RANDOM_TILT_DEGREES = 25.0

# Absolute floor for bulb spacing, enforced inside the node tree.
MIN_BULB_SPACING = 0.01

# Numeric defaults for a new strand's modifier.
#
# Applied explicitly when a strand is created rather than relying on the
# modifier picking up the node group's interface defaults: assigning
# `node_group` from Python does not reliably seed them, and an unset Bulb
# Spacing lands on 0.0, which is the resample-by-zero hang the node tree now
# guards against. Belt and braces, because the failure mode is a locked-up
# Blender rather than a wrong-looking strand.
NEW_STRAND_DEFAULTS = {
    "Bulb Spacing": 0.5,
    "Bulb Scale": 1.0,
    "Cable Radius": 0.008,
    "Random Tilt": 0.15,
    "Random Spin": 1.0,
    "Seed": 0,
    "Curve Resolution": 64,
}


def _new_input(tree, socket_type, name, default=None, min_value=None,
               max_value=None, description=""):
    """Add a modifier input.

    Order matters: interface sockets default to min=max=0.0, so assigning
    `default_value` before widening the range silently clamps it to 0. Set the
    bounds first, then the default.
    """
    item = tree.interface.new_socket(name=name, in_out='INPUT',
                                     socket_type=socket_type)
    if description:
        item.description = description
    if min_value is not None:
        item.min_value = min_value
    if max_value is not None:
        item.max_value = max_value
    if default is not None:
        item.default_value = default
    return item


def _math(tree, operation, a=None, b=None, c=None, label=""):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation = operation
    if label:
        node.label = label
    for index, value in ((0, a), (1, b), (2, c)):
        if value is None:
            continue
        if hasattr(value, "bl_idname") or hasattr(value, "is_output"):
            tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value
    return node.outputs[0]


def _vmath(tree, operation, a=None, b=None, scale=None, label=""):
    node = tree.nodes.new("ShaderNodeVectorMath")
    node.operation = operation
    if label:
        node.label = label
    for index, value in ((0, a), (1, b)):
        if value is None:
            continue
        if hasattr(value, "is_output"):
            tree.links.new(value, node.inputs[index])
        else:
            node.inputs[index].default_value = value
    if scale is not None:
        # SCALE takes its factor on the dedicated float socket, not input 1.
        socket = node.inputs["Scale"]
        if hasattr(scale, "is_output"):
            tree.links.new(scale, socket)
        else:
            socket.default_value = scale
    # VectorMath exposes both Vector and Value outputs; callers want whichever
    # is enabled for this operation.
    return node.outputs[0] if node.outputs[0].enabled else node.outputs[1]


def _object_info(tree, node_name, label=""):
    """An Object Info node whose target is set later, by name.

    The object is assigned straight onto this node rather than through a
    modifier input -- see create_group() for why.
    """
    node = tree.nodes.new("GeometryNodeObjectInfo")
    # RELATIVE puts the empty's position in the strand object's local space,
    # which is what makes parenting the empties to the strand produce a rigid
    # move instead of a double transform.
    node.transform_space = 'RELATIVE'
    node.name = node_name
    node.label = label
    return node


def create_group():
    """Build a fresh Festoon Strand node group -- one per strand.

    Per strand, not shared, and the object/material datablocks live on the
    nodes rather than on modifier inputs. That is a workaround, not a
    preference.

    Blender 5.2 hangs -- hard, no error, GUI and background alike -- when an
    Object assigned to a geometry nodes MODIFIER input is evaluated. Reduced
    to five nodes (Object Info -> Curve Line -> Resample) it reproduces every
    time; 5.0 and 5.1 run the identical setup fine. Setting the object
    straight onto the Object Info node avoids it completely, but a node's
    datablock is per-tree, so each strand needs its own tree.

    Numeric inputs are unaffected and stay on the modifier, which is what the
    panel exposes and what artists tweak.

    Cost is ~60 nodes per strand, which is nothing in memory. What's actually
    lost is edit-one-affect-all: tweaking one strand's nodes no longer changes
    the others. If the 5.2 bug is fixed, move the objects back to modifier
    inputs and share a single group again.
    """
    tree = bpy.data.node_groups.new(GROUP_BASE_NAME, "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out='OUTPUT',
                              socket_type='NodeSocketGeometry')

    # NOTE: no Object or Material sockets here -- see create_group().
    _new_input(tree, 'NodeSocketFloat', "Bulb Spacing", 0.5, 0.01, 100.0)
    _new_input(tree, 'NodeSocketFloat', "Bulb Scale", 1.0, 0.001, 100.0)
    _new_input(tree, 'NodeSocketFloat', "Cable Radius", 0.008, 0.0, 1.0)
    _new_input(tree, 'NodeSocketFloat', "Random Tilt", 0.15, 0.0, 1.0,
               description="How much each bulb tips off vertical")
    _new_input(tree, 'NodeSocketFloat', "Random Spin", 1.0, 0.0, 1.0,
               description="How much each bulb spins about its own axis")
    _new_input(tree, 'NodeSocketInt', "Seed", 0, 0, 10000)
    _new_input(tree, 'NodeSocketInt', "Curve Resolution", 64, 2, 512,
               description="Points along the cable. Raise for very long strands.")

    group_in = tree.nodes.new("NodeGroupInput")
    group_out = tree.nodes.new("NodeGroupOutput")
    inp = group_in.outputs

    # --- Endpoints -------------------------------------------------------
    start_info = _object_info(tree, NODE_START_INFO, "Start")
    end_info = _object_info(tree, NODE_END_INFO, "End")
    sag_info = _object_info(tree, NODE_SAG_INFO, "Sag")

    p0 = start_info.outputs["Location"]
    p1 = end_info.outputs["Location"]
    sag_point = sag_info.outputs["Location"]

    # --- Straight chord, resampled --------------------------------------
    line = tree.nodes.new("GeometryNodeCurvePrimitiveLine")
    tree.links.new(p0, line.inputs["Start"])
    tree.links.new(p1, line.inputs["End"])

    resample = tree.nodes.new("GeometryNodeResampleCurve")
    resample.label = "Cable resolution"
    tree.links.new(line.outputs["Curve"], resample.inputs["Curve"])
    resample.inputs["Mode"].default_value = 'Count'
    tree.links.new(inp["Curve Resolution"], resample.inputs["Count"])

    spline_param = tree.nodes.new("GeometryNodeSplineParameter")
    t = spline_param.outputs["Factor"]

    # --- Where the sag empty sits along the chord ------------------------
    chord = _vmath(tree, 'SUBTRACT', p1, p0, label="chord")
    span = _vmath(tree, 'LENGTH', chord, label="span")
    rel_sag = _vmath(tree, 'SUBTRACT', sag_point, p0, label="sag - start")

    # tc = dot(rel_sag, chord) / span^2  -- the chord's own length cancels the
    # normalisation, so no separate normalize step is needed.
    tc_raw = _math(tree, 'DIVIDE',
                   _vmath(tree, 'DOT_PRODUCT', rel_sag, chord),
                   _math(tree, 'MULTIPLY', span, span),
                   label="tc")
    # Keep tc off the ends: it divides the shape function, and a sag empty
    # dragged past an endpoint would otherwise blow the curve up.
    tc = _math(tree, 'MAXIMUM', _math(tree, 'MINIMUM', tc_raw, 0.98), 0.02,
               label="tc clamped")

    # The point on the chord directly "under" the sag empty, and the full 3D
    # offset out to it. Taking the whole vector (not just Z) is what gives
    # lateral bow and asymmetry for free.
    proj = _vmath(tree, 'ADD', p0, _vmath(tree, 'SCALE', chord, scale=tc),
                  label="chord point at tc")
    offset_vector = _vmath(tree, 'SUBTRACT', sag_point, proj, label="sag offset")

    # --- shape(t) --------------------------------------------------------
    # denom = tc when t < tc, else (1 - tc). Written branch-free as
    #   denom = (1 - tc) + less * (2*tc - 1)
    # to avoid a Mix node, whose A/B sockets share names across data types and
    # are fiddly to address reliably.
    less = _math(tree, 'LESS_THAN', t, tc, label="t < tc")
    denom = _math(tree, 'ADD',
                  _math(tree, 'SUBTRACT', 1.0, tc),
                  _math(tree, 'MULTIPLY', less,
                        _math(tree, 'SUBTRACT', _math(tree, 'MULTIPLY', tc, 2.0), 1.0)),
                  label="denom")

    ratio = _math(tree, 'MINIMUM',
                  _math(tree, 'DIVIDE',
                        _math(tree, 'ABSOLUTE', _math(tree, 'SUBTRACT', t, tc)),
                        _math(tree, 'MAXIMUM', denom, 1e-4)),
                  1.0, label="|t-tc| / denom")

    # Shape exponent from the sag empty's scale. Averaging the three axes means
    # a plain uniform S-drag in the viewport controls it.
    sag_scale = sag_info.outputs["Scale"]
    separate_scale = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(sag_scale, separate_scale.inputs[0])
    scale_avg = _math(tree, 'DIVIDE',
                      _math(tree, 'ADD',
                            _math(tree, 'ADD', separate_scale.outputs["X"],
                                  separate_scale.outputs["Y"]),
                            separate_scale.outputs["Z"]),
                      3.0, label="mean scale")

    exponent = _math(tree, 'MAXIMUM',
                     _math(tree, 'MINIMUM',
                           _math(tree, 'MULTIPLY', scale_avg, FLATNESS_TO_EXPONENT),
                           EXPONENT_MAX),
                     EXPONENT_MIN, label="shape exponent")

    shape = _math(tree, 'SUBTRACT', 1.0,
                  _math(tree, 'POWER', ratio, exponent), label="shape(t)")

    set_position = tree.nodes.new("GeometryNodeSetPosition")
    set_position.label = "Apply sag"
    tree.links.new(resample.outputs["Curve"], set_position.inputs["Geometry"])
    tree.links.new(_vmath(tree, 'SCALE', offset_vector, scale=shape),
                   set_position.inputs["Offset"])
    catenary = set_position.outputs["Geometry"]

    # --- Cable -----------------------------------------------------------
    profile = tree.nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.label = "Cable profile"
    profile.inputs["Resolution"].default_value = 6
    tree.links.new(inp["Cable Radius"], profile.inputs["Radius"])

    to_mesh = tree.nodes.new("GeometryNodeCurveToMesh")
    tree.links.new(catenary, to_mesh.inputs["Curve"])
    tree.links.new(profile.outputs["Curve"], to_mesh.inputs["Profile Curve"])

    cable_material = tree.nodes.new("GeometryNodeSetMaterial")
    cable_material.name = NODE_CABLE_MATERIAL
    cable_material.label = "Cable material"
    tree.links.new(to_mesh.outputs["Mesh"], cable_material.inputs["Geometry"])

    # --- Bulbs -----------------------------------------------------------
    # Resample by LENGTH rather than count: Blender divides the curve evenly to
    # fit, so the requested spacing is honoured approximately but the ends come
    # out even. No stub bulb at one end.
    bulb_points = tree.nodes.new("GeometryNodeResampleCurve")
    bulb_points.label = "Bulb spacing"
    tree.links.new(catenary, bulb_points.inputs["Curve"])
    bulb_points.inputs["Mode"].default_value = 'Length'
    # Hard floor on the spacing. Resample-by-length with a length at or near
    # zero asks Blender for an unbounded number of points and locks the whole
    # application up with no error -- reachable by a user typing 0 in the
    # modifier, so it has to be impossible here rather than merely unlikely.
    tree.links.new(_math(tree, 'MAXIMUM', inp["Bulb Spacing"], MIN_BULB_SPACING,
                         label="never zero"),
                   bulb_points.inputs["Length"])

    # Two bulb sources, joined. A real bulb asset is usually a COLLECTION --
    # glass, filament, fixture, metal as separate objects, often with per-engine
    # variants -- while a quick stand-in is a single object. Rather than make
    # the user pick a mode, both sockets exist and whichever is filled
    # contributes. Setting neither yields cable with no bulbs.
    bulb_source = tree.nodes.new("GeometryNodeObjectInfo")
    bulb_source.name = NODE_BULB_INFO
    bulb_source.label = "Bulb object"
    bulb_source.transform_space = 'RELATIVE'
    bulb_source.inputs["As Instance"].default_value = True

    bulb_collection = tree.nodes.new("GeometryNodeCollectionInfo")
    bulb_collection.name = NODE_BULB_COLLECTION
    bulb_collection.label = "Bulb collection"
    bulb_collection.transform_space = 'RELATIVE'
    # Separate Children off: the whole collection is ONE bulb. On, every object
    # in it would become its own bulb strung along the cable.
    bulb_collection.inputs["Separate Children"].default_value = False

    bulb_join = tree.nodes.new("GeometryNodeJoinGeometry")
    bulb_join.label = "Bulb source"
    tree.links.new(bulb_source.outputs["Geometry"], bulb_join.inputs["Geometry"])
    tree.links.new(bulb_collection.outputs["Instances"], bulb_join.inputs["Geometry"])

    instances = tree.nodes.new("GeometryNodeInstanceOnPoints")
    tree.links.new(bulb_points.outputs["Curve"], instances.inputs["Points"])
    tree.links.new(bulb_join.outputs["Geometry"], instances.inputs["Instance"])

    # --- Per-bulb random orientation -------------------------------------
    # data_type MUST be set before touching Min/Max: from Blender 5.2 the node
    # rebuilds its socket list to match, so the vector sockets do not exist
    # until the switch has happened.
    random_vector = tree.nodes.new("FunctionNodeRandomValue")
    random_vector.data_type = 'FLOAT_VECTOR'
    random_vector.label = "Per-bulb random"
    random_vector.inputs["Min"].default_value = (-1.0, -1.0, -1.0)
    random_vector.inputs["Max"].default_value = (1.0, 1.0, 1.0)
    tree.links.new(inp["Seed"], random_vector.inputs["Seed"])
    index = tree.nodes.new("GeometryNodeInputIndex")
    tree.links.new(index.outputs["Index"], random_vector.inputs["ID"])

    split_random = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(random_vector.outputs["Value"], split_random.inputs[0])

    tilt_amount = _math(tree, 'MULTIPLY', inp["Random Tilt"],
                        math.radians(MAX_RANDOM_TILT_DEGREES), label="tilt range")
    euler = tree.nodes.new("ShaderNodeCombineXYZ")
    tree.links.new(_math(tree, 'MULTIPLY', split_random.outputs["X"], tilt_amount),
                   euler.inputs["X"])
    tree.links.new(_math(tree, 'MULTIPLY', split_random.outputs["Y"], tilt_amount),
                   euler.inputs["Y"])
    tree.links.new(_math(tree, 'MULTIPLY', split_random.outputs["Z"],
                         _math(tree, 'MULTIPLY', inp["Random Spin"], math.pi)),
                   euler.inputs["Z"])

    to_rotation = tree.nodes.new("FunctionNodeEulerToRotation")
    tree.links.new(euler.outputs["Vector"], to_rotation.inputs["Euler"])

    rotate = tree.nodes.new("GeometryNodeRotateInstances")
    tree.links.new(instances.outputs["Instances"], rotate.inputs["Instances"])
    tree.links.new(to_rotation.outputs["Rotation"], rotate.inputs["Rotation"])
    rotate.inputs["Local Space"].default_value = True

    # Uniform scale only. Real bulbs come off a production line at one size, so
    # there is deliberately no per-bulb scale randomness here.
    scale_node = tree.nodes.new("GeometryNodeScaleInstances")
    tree.links.new(rotate.outputs["Instances"], scale_node.inputs["Instances"])
    uniform_scale = tree.nodes.new("ShaderNodeCombineXYZ")
    for axis in ("X", "Y", "Z"):
        tree.links.new(inp["Bulb Scale"], uniform_scale.inputs[axis])
    tree.links.new(uniform_scale.outputs["Vector"], scale_node.inputs["Scale"])

    # --- Output ----------------------------------------------------------
    join = tree.nodes.new("GeometryNodeJoinGeometry")
    tree.links.new(cable_material.outputs["Geometry"], join.inputs["Geometry"])
    tree.links.new(scale_node.outputs["Instances"], join.inputs["Geometry"])
    tree.links.new(join.outputs["Geometry"], group_out.inputs[0])

    _lay_out(tree)
    return tree


def _lay_out(tree):
    """Rough left-to-right layout.

    Purely cosmetic, but a node group that opens as a hairball is one nobody
    will read. Columns are assigned by walking backwards from the output.
    """
    depth = {}

    def walk(node, level=0):
        if depth.get(node, -1) >= level or level > 60:
            return
        depth[node] = level
        for socket in node.inputs:
            for link in socket.links:
                walk(link.from_node, level + 1)

    outputs = [n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"]
    for node in outputs:
        walk(node)

    columns = {}
    for node, level in depth.items():
        columns.setdefault(level, []).append(node)

    for level, nodes in columns.items():
        for row, node in enumerate(sorted(nodes, key=lambda n: n.name)):
            node.location = (-level * 260.0, -row * 170.0)
