# DavidsBlenderProductionToolkit
Blender Tools that have been useful for my team

Adds a panel in the viewport and compositor windows (and a button under the Passes/Lightgroups section.)

- Create Lightgroup for Every Light: Loops through your scene and creates a lightgroup using the name of each light and emissive material it finds.  This is kind of an auto-setup if you want everything split out on it's own.

- Add Selected to Lightgroup:  Adds all selected objects and lights to a lightgroup.  Gives you a dropdown with existing lightgroups and an option to create a new one.

- Setup Denoise Compositor: Automatically sets up the compositor to denoise lightpasses, and hooks up other passes you have selected.  It makes the output location "//../../04_Renders/01_Components/{blend_name}_"

- Check for Updates: I believe this is working now
