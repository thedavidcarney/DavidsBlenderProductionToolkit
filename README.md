# DavidsBlenderProductionToolkit
Blender Tools that have been useful for my team

Adds a panel in the viewport and compositor windows (and a button under the Passes/Lightgroups section.)

- Create Lightgroup for Every Light: Loops through your scene and creates a lightgroup using the name of each light and emissive material it finds.  This is kind of an auto-setup if you want everything split out on it's own.

- Add Selected to Lightgroup:  Adds all selected objects and lights to a lightgroup.  Gives you a dropdown with existing lightgroups and an option to create a new one.

- Setup Denoise Compositor: Automatically sets up the compositor to denoise lightpasses, and hooks up other passes you have selected.  It makes the output location "//../../04_Renders/01_Components/{blend_name}_"

- Check for Updates: I believe this is working now

## Camera Overlay

Own tab in the viewport sidebar. Puts a reference image over the camera frame while you work — load an image, tick Enable, pull the opacity slider. Viewport only, and only in camera view; it never shows up in a render.

Mask mode (threshold a channel and tint it) and the transform controls (fit, scale, offset, rotation, flip) are in collapsed sub-panels if you want them.

If the image ever doesn't appear, the panel says why in red, and the Diagnostics button under Support copies a full report to the clipboard.
