# Lightgroup Tools

Splits a Cycles render into one denoised pass per light and writes it all to one EXR per frame for After Effects. Also includes Camera Overlay, which puts a reference image over the camera frame.

**Find it:** 3D Viewport > Sidebar (N) > Lightgroups tab (also in the Compositor sidebar). Camera Overlay has its own tab.

## Quick start

1. Click **Create Lightgroups for Each Light**, or select objects and use **Add Selected to Lightgroup**.
2. Turn on **Denoising Data** in View Layer > Passes, then click **Setup Denoise Compositor**.
3. Render the animation. The EXRs land in `../../04_Renders/01_Components/` next to the .blend.

## Settings

| Setting | What it does |
|---|---|
| **Lightgroups** | |
| Clear All Lightgroups | Deletes every lightgroup on the current view layer. |
| Create Lightgroups for Each Light | One group per light, per emissive object, plus `World`. |
| Add Selected to Lightgroup | Puts the selected lights and objects in an existing or new group. |
| Solo Light | Mode: only the selected lights are lit in the viewport, World off. Renders and saves are never affected. |
| Setup Denoise Compositor | Rebuilds the compositor: one Denoise per group, all passes into one multilayer EXR (half float, DWAB, Filmic). Cycles only. |
| Output check | After each frame, flags a missing or cut-off EXR in red in the panel. |
| Write Diagnostics | Saves a support report and opens its folder. |
| **Camera Overlay** | |
| Enable | Draws the image over the camera frame, in camera view only. Never renders. |
| Image | The reference image (Open, pack or unlink). |
| Opacity | How strongly the image shows. Default 0.5. |
| Passepartout | The active camera's own passepartout. |
| Match File to Image Resolution | Sets the render resolution to the image's size. |
| Mode | Normal, or Mask (threshold one channel and tint it). |
| Fit | Fit, Fill or Stretch to the camera frame. |
| Scale / Offset / Rotation / Flip | Moves the image within the frame. |

## Tips

- Create Lightgroups replaces any lightgroups already set on those lights and objects. On a hand-built setup, use Add Selected instead.
- The output path expects `04_Renders/01_Components/` two folders above the .blend.
- Very many lightgroups at large sizes can run out of RAM without an error. If frames look wrong, check the red output check in the panel.
- Blender 5.2 and later write one EXR per frame. 5.0 and 5.1 also write a second render-output file.
