"""
Builds the lightgroup_tools test scene additively.

Usage:
    1. Open Blender with whatever startup file you normally use.
    2. Open the Scripting workspace, Open this file, Run Script.
    3. Save the .blend somewhere with this folder structure so the addon's
       Setup Denoise Compositor path-resolution lands correctly:
           <root>/03_Production/<this>.blend
           <root>/04_Renders/01_Components/    (create empty)

This script is purely additive: it does NOT touch your render settings,
color management, world, view layers, default camera, default cube, or
default light. It only adds collections, lights, mesh emitters, and
materials. Test objects are positioned to avoid intersecting the default
cube at the origin.

Re-running is blocked while the test collections already exist — delete
the test collections (Stage, Performers, Mixed, EmptyCollection,
NonEmissiveOnly) before re-running to get a clean rebuild.
"""

import bpy
import bmesh


TEST_COLLECTIONS = ("Stage", "Performers", "Mixed", "EmptyCollection", "NonEmissiveOnly")


def make_cube(name, location, collection, material=None):
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.location = location
    if material:
        obj.data.materials.append(material)
    return obj


def make_light(name, light_type, location, collection, energy=1000.0):
    data = bpy.data.lights.new(name=name + "_data", type=light_type)
    data.energy = energy
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = location
    return obj


def make_collection(name, parent):
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


def make_principled_emission_mat(name, strength, color, link_color=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Emission Strength"].default_value = strength
    if link_color:
        rgb = nodes.new("ShaderNodeRGB")
        rgb.outputs["Color"].default_value = (*color, 1.0)
        links.new(rgb.outputs["Color"], bsdf.inputs["Emission Color"])
    else:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    return mat


def make_standalone_emission_mat(name, color, strength=10.0, link_color=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for n in list(nodes):
        if n.type == 'BSDF_PRINCIPLED':
            nodes.remove(n)
    out = next(n for n in nodes if n.type == 'OUTPUT_MATERIAL')
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = strength
    if link_color:
        rgb = nodes.new("ShaderNodeRGB")
        rgb.outputs["Color"].default_value = (*color, 1.0)
        links.new(rgb.outputs["Color"], em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = (*color, 1.0)
    links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_plain_mat(name, color=(0.5, 0.5, 0.5)):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    return mat


def build():
    existing = [c for c in TEST_COLLECTIONS if c in bpy.data.collections]
    if existing:
        print(f"Test collections already exist: {existing}")
        print("Delete them and re-run to rebuild.")
        return

    scene = bpy.context.scene
    master = scene.collection

    stage = make_collection("Stage", master)
    front_truss = make_collection("Front_Truss", stage)
    back_truss = make_collection("Back_Truss", stage)
    floor = make_collection("Floor", stage)
    performers = make_collection("Performers", master)
    mixed = make_collection("Mixed", master)
    make_collection("EmptyCollection", master)
    non_emissive_only = make_collection("NonEmissiveOnly", master)

    # Lights — one of each type, plus naming and multi-collection edge cases.
    make_light("Light_Point_01", 'POINT', (-3, -5, 3), front_truss)
    make_light("Light_Spot_01",  'SPOT',  ( 3, -5, 3), front_truss)
    make_light("Light_Sun_01",   'SUN',   ( 0, -3, 6), back_truss, energy=5.0)
    make_light("Light_Area_01",  'AREA',  ( 0, -7, 4), back_truss, energy=200.0)

    # Duplicate-named lights — Blender auto-suffixes the second to .001;
    # the addon does name.replace(".", "_") so groups land as Dup / Dup_001.
    make_light("Light_Point_Dup", 'POINT', (-2, 4, 2), front_truss)
    make_light("Light_Point_Dup", 'POINT', ( 2, 4, 2), front_truss)

    # Light linked into two collections — primary case for the upcoming
    # collection-based grouping feature; should still produce one group today.
    mc_data = bpy.data.lights.new(name="Light_MultiCollection_data", type='POINT')
    mc = bpy.data.objects.new("Light_MultiCollection", mc_data)
    front_truss.objects.link(mc)
    performers.objects.link(mc)
    mc.location = (0, 5, 2)

    # Principled BSDF emission variants
    mat_p_normal       = make_principled_emission_mat("Mat_Princ_Normal",       strength=5.0, color=(1.0, 1.0, 1.0))
    mat_p_blackcolor   = make_principled_emission_mat("Mat_Princ_BlackColor",   strength=5.0, color=(0.0, 0.0, 0.0))
    mat_p_zerostrength = make_principled_emission_mat("Mat_Princ_ZeroStrength", strength=0.0, color=(1.0, 0.5, 0.5))
    mat_p_linkedcolor  = make_principled_emission_mat("Mat_Princ_LinkedColor",  strength=5.0, color=(0.0, 1.0, 1.0), link_color=True)

    # Standalone Emission shader variants
    mat_s_normal      = make_standalone_emission_mat("Mat_Stand_Normal",      color=(1.0, 0.0, 0.0), strength=10.0)
    mat_s_blackcolor  = make_standalone_emission_mat("Mat_Stand_BlackColor",  color=(0.0, 0.0, 0.0), strength=10.0)
    mat_s_linkedcolor = make_standalone_emission_mat("Mat_Stand_LinkedColor", color=(1.0, 0.0, 1.0), strength=10.0, link_color=True)

    # Non-emissive control material
    mat_plain = make_plain_mat("Mat_Plain")

    # Mesh emitters — positioned offset from origin so they don't intersect
    # the default cube (which sits at 0,0,0 with size 2).
    make_cube("Emit_Princ_Normal",       (-2, -4, 0.5), floor,             mat_p_normal)
    make_cube("Emit_Princ_BlackColor",   ( 0, -4, 0.5), floor,             mat_p_blackcolor)
    make_cube("Emit_Princ_ZeroStrength", ( 2, -4, 0.5), floor,             mat_p_zerostrength)
    make_cube("Emit_Princ_LinkedColor",  (-1,  4, 0.5), mixed,             mat_p_linkedcolor)
    make_cube("Emit_Stand_Normal",       (-2,  6, 0.5), performers,        mat_s_normal)
    make_cube("Emit_Stand_BlackColor",   ( 0,  6, 0.5), performers,        mat_s_blackcolor)
    make_cube("Emit_Stand_LinkedColor",  ( 1,  4, 0.5), mixed,             mat_s_linkedcolor)
    make_cube("NonEmit_Plain",           ( 3,  4, 0.5), mixed,             mat_plain)
    make_cube("NonEmit_Plain_2",         ( 5,  5, 0.5), non_emissive_only, mat_plain)

    print("\n=== Test scene built (additive) ===")
    print(f"Lights total in scene:  {sum(1 for o in scene.objects if o.type == 'LIGHT')}")
    print(f"Mesh objs total in scene: {sum(1 for o in scene.objects if o.type == 'MESH')}")
    print(f"Test collections added: {len(TEST_COLLECTIONS) + 3}  (incl. Front_Truss, Back_Truss, Floor under Stage)")
    print("\nNote: counts include any default cube/light/etc. left in your startup file.")
    print("Save: <root>/03_Production/<name>.blend  with empty <root>/04_Renders/01_Components/ alongside.\n")


if __name__ == "__main__":
    build()
