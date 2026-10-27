# Light-pass findings from the carousel heart-stage job (Oct 2026)

These are findings for a future Toolkit session, not fixes. Nothing in `lightgroup_tools/` was changed.
- **Toolkit version:** v1.0.19 (released).
- **Blender:** 5.2 LTS.
- **Scene:** a proscenium plus heart-wall GN rigs, 34 spots, and GN-instanced LED cards and bulbs.

The workaround script lives in BlenderExpert:
`scripts/carousel_heartstage/heartstage_lightpass_setup.py`. It runs the real operators, then repairs
the light-group assignments. The compositor stays exactly as `denoise_all_cycles` builds it.

## 1. Create Lightgroups overwrites existing assignments
`create_for_each_light` sets `obj.lightgroup` on every emissive object, even one that already has a
deliberate group. Here it renamed `HW_LEDCard` from `LED` to `HW_LEDCard`.
- **Repro:** give an emissive mesh `obj.lightgroup = "X"` and run the button. Its group becomes the object name.
- **Expected:** assignments that already exist are left alone, or there is an option to keep them.

## 2. Shared groups across objects have to be restored after the button
`Bulbs_1/2/3` are shared by several `<rig>_BulbsN` objects (one group, many objects). The button splits
them into one group per object. The script snapshots `obj.lightgroup` before running the button and
writes it back afterwards. This is the same root cause as 1. It matters for chases: AE builds a 3-step
bulb chase from exactly those three layer names.

## 3. Groups get made for instance sources and holdout objects
- **Instance sources:** the button also makes groups for source objects that are hidden from render
  and only render as instances. Here that was `HW_Src_MarqueeBulb`, which isn't instanced as an object.
- **Holdout objects (new):** it made groups for the mask eyes, which have `is_holdout` on. Their passes
  came out empty. The script now skips objects with `obj.is_holdout`.
- **Expected:** groups only for objects that contribute light. Skip holdouts, and judge render
  visibility as described in 4.

## 4. An instanced object's light group comes from the instanced SOURCE (measured)
In Cycles, the instance takes the light group of the object being instanced, not the GN instancer's.
- **Case:** `HW_LEDCard` has hide_render on, is in group `LED`, and is instanced 1908 times per heart wall.
- **Measurement:** with `LED` missing from the view-layer list, its light went into no pass. In a
  linear test render (File Output temporarily set to Linear Rec.709), the groups summed to 0.73 of
  Image (blue 0.18). With `LED` in the list they summed to 0.984. The remainder is per-group vs.
  combined denoising.
- **Consequence:** a "skip non-visible objects" filter would also drop these sources and lose their light.
  Count an object as rendering if it renders directly OR appears as
  `depsgraph.object_instances[i].object.original` with `is_instance`.
- **Consequence:** one shared source card can't be split into per-wall passes. Each wall would need its own copy.

## 5. The World pass has alpha 1.0 everywhere
The `World` layer comes out with alpha = 1.0 over the whole frame. An ambient deliverable with
transparency would have to take it from the `Alpha` pass. **David's call:** only do that when he asks for it.

## 6. Multi-part DWAB EXR: a false OOM at 65 parts
At full res, a 65-part DWAB-half multilayer write failed three times with an out-of-memory error even
though memory was free. A PC restart fixed it.
- **Related:** an earlier note (BlenderExpert memory) records `EXR_ERR_OUT_OF_MEMORY` at ~50 parts,
  7700x1440, which fixed render threads (8) avoided. AE holding a large RAM cache has also truncated writes.
- **After every write:** check the part count and that the file opens.
