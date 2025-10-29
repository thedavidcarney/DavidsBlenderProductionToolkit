import bpy

class LIGHTGROUP_OT_create_for_each_light(bpy.types.Operator):
    """Create a lightgroup for each light, world, and emissive object"""
    bl_idname = "lightgroup.create_for_each_light"
    bl_label = "Create Lightgroups"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        lightGroupsAmount = 0
        lightGroupsNames = []

        # Get all the lights in the scene
        lights = [obj for obj in context.scene.objects if obj.type == 'LIGHT']

        # Create a light group for each light and assign the light to it
        for i, light in enumerate(lights):
            oldName = light.name
            newName = oldName.replace(".", "_")
            
            # Create a new light group in the view layer tab
            bpy.ops.scene.view_layer_add_lightgroup(name=newName)
            
            # Make current light in list active object
            context.view_layer.objects.active = bpy.data.objects[light.name]
            
            # Assign the light to the new group in the shading tab
            context.object.lightgroup = newName
            
            # Increment our light group counter and add name to the list
            lightGroupsAmount += 1
            lightGroupsNames.append(newName)
            
        # Make a new lightgroup for world
        bpy.ops.scene.view_layer_add_lightgroup(name="World")
        # Assign World to world lightgroup
        context.scene.world.lightgroup = "World"
        # Increment our light group counter and add name to the list
        lightGroupsAmount += 1
        lightGroupsNames.append("World")

        emissive_materials = []
        emissive_objects = []

        # Loop through all the materials in the scene
        for material in bpy.data.materials:
            if not material.use_nodes:
                continue
            
            # Loop through all the nodes in the material's node tree
            for node in material.node_tree.nodes:
                # Check if the node is an Emission shader
                if node.type == 'EMISSION':
                    # Check if it's connected or has non-zero strength
                    is_connected = any(output.is_linked for output in node.outputs)
                    has_strength = node.inputs[1].default_value > 0 if len(node.inputs) > 1 else True
                    
                    if is_connected or has_strength:
                        # Avoid duplicates
                        if material.name not in emissive_materials:
                            emissive_materials.append(material.name)
                            print(f"Found Emissive Mat: {material.name}")
                        break

        # Check Principled BSDF for emission
        for material in bpy.data.materials:
            if not material.use_nodes:
                continue
            
            for node in material.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    # Find emission sockets by name (more reliable than index)
                    emission_socket = None
                    emission_strength_socket = None
                    
                    for input_socket in node.inputs:
                        if input_socket.name == "Emission Color":
                            emission_socket = input_socket
                        elif input_socket.name == "Emission Strength":
                            emission_strength_socket = input_socket
                    
                    # Check if emission strength > 0 or if emission is connected
                    has_emission_strength = emission_strength_socket and emission_strength_socket.default_value > 0
                    has_emission_connection = emission_strength_socket and emission_strength_socket.is_linked
                    has_color_connection = emission_socket and emission_socket.is_linked
                    
                    if has_emission_strength or has_emission_connection or has_color_connection:
                        # Avoid duplicates
                        if material.name not in emissive_materials:
                            emissive_materials.append(material.name)
                            print(f"Found Principled BSDF Mat with emission: {material.name}")
                        break

        # Print out the list of materials that use emission
        print(f"Total emissive materials found: {len(emissive_materials)}")
        print(emissive_materials)

        # Find objects using emissive materials
        for obj in bpy.data.objects:
            # Check if object has material slots
            if not hasattr(obj, 'material_slots'):
                continue
            
            # Iterate through all material slots
            for slot in obj.material_slots:
                # Handle missing materials (null check)
                if slot.material is None:
                    continue
                
                # Check if material name is in material_list
                if slot.material.name in emissive_materials:
                    # Avoid duplicate objects
                    if obj not in emissive_objects:
                        print(f"Found Object using Emission: {obj.name}")
                        emissive_objects.append(obj)
                    break

        # Create a light group for each emissive object and assign it
        for i, emissive_object in enumerate(emissive_objects):
            oldName = emissive_object.name
            newName = oldName.replace(".", "_")
            
            # Create a new light group in the view layer tab
            bpy.ops.scene.view_layer_add_lightgroup(name=newName)
            
            # Make current object in list active object
            context.view_layer.objects.active = bpy.data.objects[emissive_object.name]
            
            # Assign the object to the new group in the shading tab
            context.object.lightgroup = newName
            
            # Increment our light group counter and add name to the list
            lightGroupsAmount += 1
            lightGroupsNames.append(newName)

        print(f"\nTotal lightgroups created: {lightGroupsAmount}")
        print(f"Lightgroup names: {lightGroupsNames}")
        
        self.report({'INFO'}, f"Created {lightGroupsAmount} lightgroups")
        return {'FINISHED'}


class LIGHTGROUP_OT_denoise_all_cycles(bpy.types.Operator):
    """Set up compositor to denoise all lightgroups (Cycles only)"""
    bl_idname = "lightgroup.denoise_all_cycles"
    bl_label = "Setup Denoise Compositor"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        # Check if Cycles is the active render engine
        if context.scene.render.engine != 'CYCLES':
            self.report({'ERROR'}, "This script requires Cycles render engine. Please switch to Cycles and try again.")
            return {'CANCELLED'}
        
        # SET UP COMPOSITOR
        # Prep lightgroups variables
        lightGroups = context.scene.view_layers["ViewLayer"].lightgroups
        lightGroupsAmount = len(lightGroups)
        lightGroupsNames = []
        i = 0
        while i < lightGroupsAmount:
            lightGroupsNames.append(lightGroups[i].name)
            i += 1
            
        print(lightGroupsNames)
        # Make sure compositor nodes are on
        context.scene.use_nodes = True
        context.view_layer.cycles.denoising_store_passes = True
        tree = context.scene.node_tree
        # Clear all previous nodes so we can control where they are
        for node in tree.nodes:
            tree.nodes.remove(node)
            
        renderLayersNode = tree.nodes.new(type='CompositorNodeRLayers')
        renderLayersNode.location = 0, 0
        links = tree.links
        
        # Helper function to find output by name
        def find_output(node, output_name):
            for output in node.outputs:
                if output.name == output_name:
                    return output
            return None
        
        # Find the denoising outputs by name
        denoisingNormalOutput = find_output(renderLayersNode, "Denoising Normal")
        denoisingAlbedoOutput = find_output(renderLayersNode, "Denoising Albedo")
        
        # Check if denoising outputs exist
        if not denoisingNormalOutput or not denoisingAlbedoOutput:
            print("ERROR: Denoising outputs not found. Make sure 'Denoising Data' is enabled in render settings.")
            self.report({'ERROR'}, "Denoising outputs not found. Enable 'Denoising Data' in render settings.")
            return {'CANCELLED'}
        
        # Create Output Node
        outputNode = tree.nodes.new(type='CompositorNodeOutputFile')
        outputNode.base_path = "//../../04_Renders/01_Components/{blend_name}_"
        outputNode.location = 1000, -250
        outputNode.width = 500
        
        # Track which outputs we've already used
        usedOutputs = set()
        
        # Current slot index for file output
        slotIndex = 0
        
        # Process light groups with denoising
        i = 0
        while i < lightGroupsAmount:
            denoiseNode = tree.nodes.new(type='CompositorNodeDenoise')
            denoiseNode.location = 500, i * -250
            
            # Find the light group output by name with "Combined_" prefix
            lightGroupOutputName = f"Combined_{lightGroupsNames[i]}"
            lightGroupOutput = find_output(renderLayersNode, lightGroupOutputName)
            
            if lightGroupOutput and denoisingNormalOutput and denoisingAlbedoOutput:
                # Track that we're using these outputs
                usedOutputs.add(lightGroupOutputName)
                usedOutputs.add("Denoising Normal")
                usedOutputs.add("Denoising Albedo")
                
                # link the image to denoise
                links.new(lightGroupOutput, denoiseNode.inputs[0])
                
                # link the denoising data
                links.new(denoisingNormalOutput, denoiseNode.inputs[1])
                links.new(denoisingAlbedoOutput, denoiseNode.inputs[2])
                
                # link the denoiser to file output
                if slotIndex == 0:
                    outputNode.layer_slots[0].name = lightGroupsNames[i]
                    links.new(denoiseNode.outputs[0], outputNode.inputs[slotIndex])
                else:
                    outputNode.layer_slots.new(lightGroupsNames[i])
                    links.new(denoiseNode.outputs[0], outputNode.inputs[slotIndex])
                
                slotIndex += 1
            else:
                print(f"WARNING: Could not find output for light group '{lightGroupOutputName}'")
            
            i += 1
        
        # Now add all remaining passes (except Denoising Depth) directly to file output
        for output in renderLayersNode.outputs:
            # Skip if we've already used this output, or if it's Denoising Depth, or if it's not enabled
            if output.name in usedOutputs or output.name == "Denoising Depth" or output.name == "Noisy Image" or not output.enabled:
                continue
            
            # Add this pass to the file output
            if slotIndex == 0:
                outputNode.layer_slots[0].name = output.name
                links.new(output, outputNode.inputs[slotIndex])
            else:
                outputNode.layer_slots.new(output.name)
                links.new(output, outputNode.inputs[slotIndex])
            
            slotIndex += 1
            print(f"Added pass: {output.name}")
        
        self.report({'INFO'}, "Compositor setup complete")
        return {'FINISHED'}