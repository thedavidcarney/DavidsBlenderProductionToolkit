"""Creates the objects that make up a festoon strand.

Layout:

    Festoons/                 the strands you placed
      Festoon                 mesh + Geometry Nodes modifier
        Festoon_Start         empty, parented to the strand
        Festoon_End
        Festoon_Sag
    Festoon Bulbs/            bulb SOURCES, hidden (eye off)
      Marquee Bulb/           the bundled asset

Bulb sources are a separate collection: Festoons should list the things you
placed, and the objects being instanced are machinery. They stay IN the view
layer though -- Collection Info instances what the depsgraph evaluates, so
excluding them would empty every strand.

The empties are children of the strand mesh whose modifier reads them. That
sounds circular but isn't: Blender tracks object transform and object geometry
as separate depsgraph components, so mesh-geometry-depends-on-empty-transform
and empty-transform-depends-on-mesh-transform coexist without a cycle
(verified). The payoff is that each strand collapses to one outliner row, and
grabbing the strand mesh moves the whole thing rigidly -- which also makes
"parent a festoon to a flying truss" a one-object operation later.

Object Info runs in RELATIVE space for the same reason: with parenting, that's
what makes a parent move rigid instead of double-transformed.
"""

import os

import bmesh
import bpy
from mathutils import Vector

from . import nodes
from .picking import CONTROL_PROP, STRAND_PROP

COLLECTION_NAME = "Festoons"
STRAND_BASE_NAME = "Festoon"

# Bulb SOURCES live in their own collection, not mixed in with the strands.
# Festoons/ should contain the things you placed; the objects being instanced
# are machinery.
BULB_COLLECTION_NAME = "Festoon Bulbs"

BULB_NAME = "Festoon_Bulb"
BULB_MATERIAL_NAME = "Festoon Bulb Emission"

# Radius of the fallback stand-in bulb, in metres. Only used when the bundled
# asset can't be loaded.
DEFAULT_BULB_RADIUS = 0.03

# Bundled bulb asset. A marquee bulb is a collection -- glass, filament,
# fixture, metal, plus separate Cycles and EEVEE glass variants -- so it is
# instanced as a collection rather than a single object.
BULB_ASSET_FILE = "marquee_bulb.blend"
BULB_ASSET_COLLECTION = "Marquee Bulb"


def _get_or_link_collection(scene, name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        return collection

    linked = any(child is collection for child in scene.collection.children_recursive)
    if not linked:
        scene.collection.children.link(collection)
    return collection


def get_collection(scene):
    """The Festoons collection, holding the strands you placed."""
    return _get_or_link_collection(scene, COLLECTION_NAME)


def get_bulb_collection(scene):
    """The collection holding bulb SOURCE objects.

    Kept separate from Festoons so the strand list stays readable. The sources
    have to remain in the view layer -- Collection Info instances what the
    depsgraph evaluates, and excluding the collection would empty it -- so they
    are hidden rather than excluded.
    """
    return _get_or_link_collection(scene, BULB_COLLECTION_NAME)


def _asset_path(filename):
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets", filename)


def _hide_layer_collection(context, collection):
    """Switch the eye off for a collection in the current view layer.

    The eye is viewport visibility only, so the objects stay in the depsgraph
    and remain instanceable. The monitor icon (collection.hide_viewport) would
    drop them out entirely and the bulbs would vanish.
    """
    def walk(layer_collection):
        if layer_collection.collection is collection:
            layer_collection.hide_viewport = True
            return True
        return any(walk(child) for child in layer_collection.children)

    try:
        walk(context.view_layer.layer_collection)
    except AttributeError:
        pass


def ensure_marquee_bulb(context):
    """Append the bundled marquee bulb collection, or return it if present.

    Returns None if the asset is missing, so callers can fall back to the
    generated stand-in rather than producing a strand with no bulbs.
    """
    existing = bpy.data.collections.get(BULB_ASSET_COLLECTION)
    if existing is not None:
        return existing

    path = _asset_path(BULB_ASSET_FILE)
    if not os.path.isfile(path):
        print("Festoon: bundled bulb asset missing at " + path)
        return None

    try:
        with bpy.data.libraries.load(path, link=False) as (source, target):
            if BULB_ASSET_COLLECTION not in source.collections:
                print("Festoon: '" + BULB_ASSET_COLLECTION + "' not found in the bulb asset")
                return None
            target.collections = [BULB_ASSET_COLLECTION]
    except Exception as error:  # noqa: BLE001 - a bad asset must not kill placement
        print("Festoon: could not append the bulb asset: " + str(error))
        return None

    appended = bpy.data.collections.get(BULB_ASSET_COLLECTION)
    if appended is None:
        return None

    # Park it under Festoon Bulbs and hide it. Appending does not link it to
    # the scene, and an unlinked collection is not evaluated -- so without this
    # Collection Info would hand back nothing.
    bulbs = get_bulb_collection(context.scene)
    if not any(child is appended for child in bulbs.children):
        bulbs.children.link(appended)
    _hide_layer_collection(context, bulbs)
    return appended


def _link_only(obj, collection):
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    collection.objects.link(obj)


def ensure_bulb_material():
    material = bpy.data.materials.get(BULB_MATERIAL_NAME)
    if material is not None:
        return material

    material = bpy.data.materials.new(BULB_MATERIAL_NAME)
    if material.node_tree is None:
        # Deprecated in 5.x (slated for removal in 6.0) but still required on
        # the older versions bl_info allows.
        material.use_nodes = True
    tree = material.node_tree

    # Clear the default Principled BEFORE grabbing the output node: removing a
    # node invalidates Python references to its siblings, so a handle fetched
    # first goes stale and its sockets stop resolving.
    for node in list(tree.nodes):
        if node.type != 'OUTPUT_MATERIAL':
            tree.nodes.remove(node)
    output = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputMaterial")

    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.82, 0.55, 1.0)
    emission.inputs["Strength"].default_value = 25.0
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def ensure_default_bulb(scene):
    """A stand-in bulb, so a fresh strand shows something immediately.

    Built with bmesh rather than bpy.ops so it works headlessly and doesn't
    depend on selection state.

    Hidden with hide_set (the H key), NOT hide_viewport (the monitor icon):
    hide_viewport drops the object out of the depsgraph entirely, and Object
    Info would then hand the node group nothing to instance.
    """
    existing = bpy.data.objects.get(BULB_NAME)
    if existing is not None:
        return existing

    mesh = bpy.data.meshes.new(BULB_NAME + "_mesh")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=DEFAULT_BULB_RADIUS)
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    mesh.materials.append(ensure_bulb_material())

    bulb = bpy.data.objects.new(BULB_NAME, mesh)
    _link_only(bulb, get_bulb_collection(scene))
    bulb.hide_render = True
    try:
        bulb.hide_set(True)
    except RuntimeError:
        # No view layer context (headless); harmless, it just stays visible.
        pass
    return bulb


def input_identifier(tree, name):
    """Opaque socket identifier ("Socket_3") for an interface input NAME.

    Everything addresses inputs by name and resolves the identifier at the
    point of use. Identifiers shift when the interface is reordered, so
    hardcoding them would let a future edit quietly write a bulb object into
    the cable radius.
    """
    for item in tree.interface.items_tree:
        if getattr(item, "item_type", "") != 'SOCKET':
            continue
        if item.in_out == 'INPUT' and item.name == name:
            return item.identifier
    return None


def interface_input(tree, name):
    """The interface item for an input socket, by name."""
    for item in tree.interface.items_tree:
        if getattr(item, "item_type", "") != 'SOCKET':
            continue
        if item.in_out == 'INPUT' and item.name == name:
            return item
    return None


def input_identifier(tree, name):
    item = interface_input(tree, name)
    return item.identifier if item is not None else None


def set_parameter(tree, modifier, name, value):
    """Set a strand parameter.

    Writes the node group's INTERFACE DEFAULT, which is the part that actually
    takes effect, and then best-effort writes the modifier input too.

    On Blender 5.2 there is no working Python route to a geometry nodes
    modifier input: `modifier.properties.inputs.<Socket_N>` is a read-only
    RNA pointer, and the IDProperty underneath accepts a write that the
    evaluator then ignores outright (verified -- a cube driven by a modifier
    input stayed at its interface default after assigning a different value).
    The interface default is what gets used, so that's what we set.

    This is only viable because every strand owns its own node group -- forced
    on us by a separate 5.2 bug, and here it pays for itself. On 5.0/5.1 the
    modifier's stored value overrides the default, so both are written and
    each version uses whichever it honours.
    """
    item = interface_input(tree, name)
    if item is None:
        return False

    try:
        item.default_value = value
    except (TypeError, AttributeError):
        return False

    if modifier is not None:
        properties = getattr(modifier, "properties", None)
        container = properties.inputs if properties is not None else modifier
        try:
            container[item.identifier] = value
        except (TypeError, KeyError, RuntimeError):
            # 5.2 replaces the entry with a property group after the first
            # evaluation and refuses a scalar. The interface default above is
            # already doing the real work, so this is genuinely optional.
            pass
    return True


def get_parameter(tree, name, default=None):
    item = interface_input(tree, name)
    if item is None:
        return default
    return getattr(item, "default_value", default)


def _make_empty(name, location, normal, collection, display_size):
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = 'PLAIN_AXES'
    empty.empty_display_size = display_size
    empty.location = location
    if normal is not None and normal.length > 1e-6:
        # Align Z to the surface normal. Nothing reads this yet -- it's here so
        # a future "mounting bracket at each end" has the orientation already.
        empty.rotation_euler = normal.to_track_quat('Z', 'Y').to_euler()
    empty[CONTROL_PROP] = True
    collection.objects.link(empty)
    return empty


def create_strand(context, start, end, sag, flatness=1.0,
                  start_normal=None, end_normal=None, bulb_object=None,
                  bulb_collection=None, bulb_spacing=None):
    """Build a complete strand. Returns the strand mesh object."""
    scene = context.scene
    collection = get_collection(scene)
    # One group per strand -- see nodes.create_group() for the 5.2 bug that
    # forces this.
    tree = nodes.create_group()

    span = (Vector(end) - Vector(start)).length
    # Scale the empties with the strand so they stay grabbable on a 30m span
    # without swamping a 2m one.
    display_size = max(0.05, min(0.5, span * 0.03))

    mesh = bpy.data.meshes.new(STRAND_BASE_NAME + "_mesh")
    strand = bpy.data.objects.new(STRAND_BASE_NAME, mesh)
    # Identity transform: the node group works in the strand's local space, and
    # leaving it at the origin keeps RELATIVE Object Info equal to world space
    # until the user deliberately moves the strand.
    strand.location = (0.0, 0.0, 0.0)
    strand[STRAND_PROP] = True
    collection.objects.link(strand)

    start_empty = _make_empty(strand.name + "_Start", start, start_normal,
                              collection, display_size)
    end_empty = _make_empty(strand.name + "_End", end, end_normal,
                            collection, display_size)
    sag_empty = _make_empty(strand.name + "_Sag", sag, None,
                            collection, display_size)
    sag_empty.empty_display_type = 'SPHERE'
    # Scale IS the flatness control, so it must start at the intended value.
    sag_empty.scale = (flatness, flatness, flatness)

    for empty in (start_empty, end_empty, sag_empty):
        empty.parent = strand
        empty.matrix_parent_inverse = strand.matrix_world.inverted()

    modifier = strand.modifiers.new("Festoon", 'NODES')
    modifier.node_group = tree

    for input_name, value in nodes.NEW_STRAND_DEFAULTS.items():
        set_parameter(tree, modifier, input_name, value)
    if bulb_spacing:
        # Overrides the built-in default so the strand matches the spacing the
        # placement preview just drew.
        set_parameter(tree, modifier, "Bulb Spacing", bulb_spacing)

    # Prefer whatever the user picked; otherwise fall back to the bundled
    # marquee bulb, and to a generated sphere only if that asset is missing.
    if bulb_object is None and bulb_collection is None:
        bulb_collection = ensure_marquee_bulb(context)
        if bulb_collection is None:
            bulb_object = ensure_default_bulb(scene)

    set_strand_targets(tree,
                       start=start_empty,
                       end=end_empty,
                       sag=sag_empty,
                       bulb=bulb_object,
                       bulb_collection=bulb_collection)
    return strand


def set_strand_targets(tree, start=None, end=None, sag=None, bulb=None,
                       bulb_collection=None, cable_material=None):
    """Point a strand's node group at its objects.

    Assigned straight onto the nodes, NOT through modifier inputs: an Object
    on a geometry nodes modifier input hangs Blender 5.2 outright. See
    nodes.create_group().
    """
    targets = (
        (nodes.NODE_START_INFO, "Object", start),
        (nodes.NODE_END_INFO, "Object", end),
        (nodes.NODE_SAG_INFO, "Object", sag),
        (nodes.NODE_BULB_INFO, "Object", bulb),
        (nodes.NODE_BULB_COLLECTION, "Collection", bulb_collection),
        (nodes.NODE_CABLE_MATERIAL, "Material", cable_material),
    )
    for node_name, socket_name, value in targets:
        if value is None:
            continue
        node = tree.nodes.get(node_name)
        if node is not None:
            node.inputs[socket_name].default_value = value


def strand_node(strand, node_name):
    """Fetch a named node from a strand's own group, or None."""
    modifier = next((m for m in strand.modifiers if m.type == 'NODES'), None)
    if modifier is None or modifier.node_group is None:
        return None
    return modifier.node_group.nodes.get(node_name)


def strand_objects(scene):
    """Every strand mesh in the scene.

    Keyed off the custom property rather than the collection, so strands that
    get reorganised into a per-show collection are still found.
    """
    return [obj for obj in scene.objects if obj.get(STRAND_PROP)]
