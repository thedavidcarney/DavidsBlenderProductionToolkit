# Lightgroup Tools: single-EXR output (Blender 5.2+)

A proposed change to David Carney's Lightgroup Tools add-on, made against his latest release (v1.0.19, from github.com/thedavidcarney/DavidsBlenderProductionToolkit).
It changes **Setup Denoise Compositor**. On Blender 5.2 and later, one click now gives you **one EXR per frame**. Blender 5.0/5.1 keep the old setup unchanged.

- `lightgroup_tools/`: the patched add-on
- `lightgroup_tools_upstream_1_0_19/`: David's original, untouched
- `single_exr.patch`: the diff. Only `lightgroups/operators.py` changes.

## What's wrong with the current setup (tested in 5.2)

1. **Every frame is written twice.** The button builds a File Output node but leaves the scene's render output on. So each frame writes:
   - `{blend}_.exr` (the File Output), holding the denoised lightgroups and the extra passes;
   - the render-output EXR, a full-float dump of *every* view-layer pass: noisy lightgroups, Crypto again, Noisy Image and all the Denoising data. In the test this file was 17 parts and **22x bigger**, and it is the file that caused the PC memory spike on save.
   - Cryptomatte ends up in both files. That's the "which file do I use?" confusion.
2. **Depth in the File Output is broken.** It is added as a colour (RGBA) layer, so it gets half precision plus the Filmic curve, and the max comes out as 1.002. It's useless in AE.
3. **Alpha gets its own layer and is Filmic-encoded** (1.0 comes out as 0.807). Image.A already holds the correct alpha.
4. **Junk layers.** 5.x added `Denoising Specular Albedo` and `Denoising Roughness`, and these slip through into the delivery file.
5. Normal, Vector, Position and value AOVs would get the same colour treatment as Depth.

## What the patched button does (5.2+)

- Denoises each lightgroup, as before. Same layer names, so existing AE comps still line up.
- Writes the **denoised beauty** as `Image`. If render denoising is off, it adds a Denoise node for the beauty too, so the file never holds a noisy beauty.
- Adds every other enabled pass, **typed so data stays data**:
  - Depth and value AOVs go in as FLOAT; Normal, Vector and Position as VECTOR. All are written as lossless float, untagged by Filmic.
  - Crypto is written as float, with the manifest.
  - Colour AOVs get the Filmic override like the lightgroups.
- Skips Alpha, Noisy Image and every `Denoising *` pass.
- Turns **`render.save_output` off**, so the File Output is the only writer. Turns `use_compositing` on.
- Wires the beauty to a Group Output, so the F12 render window shows it.
- Settings as before: half, DWAB, quality 15, and the Filmic sRGB override. The colour space is set last and read back; the button aborts if 5.2 resets it to Linear.
- Re-running is safe. It rebuilds the compositor as before, which also removes any old second File Output.

The output is still `//../../04_Renders/01_Components/{blend_name}_####.exr`.

## Verified (Blender 5.2.0, headless)

The test scene had a light, the World and an emissive sphere, with Crypto Object+Material, Depth, Normal, Vector and two AOVs turned on. It rendered a 2-frame animation, once with render denoising on and once with it off.

- **Only** `LGTest2_0001.exr` and `LGTest2_0002.exr` were written. No second file.
- Each file has 15 parts: Light, World, Sphere, Image (half, Filmic), Depth, Normal, Vector, Crypto ×6 and MaskVal (float data), plus MaskCol (half, Filmic).
- The Cryptomatte manifest metadata is present. Depth now holds real camera distances.
- Clicking the button twice does not duplicate nodes.

## Left alone, on purpose

- Lightgroups are still Filmic-baked, so they don't sum linearly to Image. This is the team convention.
- The lightgroup layers' alpha is still solid 1.0, the same as today.
- The Vector pass comes out as 3 channels, not 4. It only matters if someone uses motion vectors.

## Separate issue: Noah's 5.2 install is half-updated

In `~/Library/Application Support/Blender/5.2/scripts/addons/lightgroup_tools/`, the subfolders (`core/`, `lightgroups/`, `festoon/`, `camera_overlay/`) are from about v1.0.18 (Sep 26). But the top-level `__init__.py` is still **v1.0.14** (May), and it loads the old flat `operators.py`. So Blender is running 1.0.14: no Solo Light, and the denoise button only works on a view layer named exactly `ViewLayer`. A clean reinstall of 1.0.19 (or of this patch) fixes it.

## Status (Nov 2026)
Built into the Toolkit except two things. `Alpha` stays, because the template's Stencil Luma reads it (see `CLAUDE.md`). The FLOAT/VECTOR data passes were not taken, and the team standard is now Mist rather than Depth (see `CLAUDE.md`). Also: EXRDemux reads only R/G/B/A, and DWAB is lossy on `.Y`, so "lossless" above is not accurate for Normal, Vector or Position. See the Setup Denoise entry in `CLAUDE.md`. Noah's reported crypto problem is still open, pending a broken file.
