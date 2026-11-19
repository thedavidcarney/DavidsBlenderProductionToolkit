# DavidsBlenderProductionToolkit

A repo of Blender addons for David Carney's team. Currently contains one addon (`lightgroup_tools/`); the "toolkit" name is **aspirational** — more addons are intended to live here over time. One repo by design. Don't suggest splitting addons into separate repos.

## Package layout

**Festoon Clicker was removed** (Nov 2026; never used in production). The
code, its tests and its notes are kept, not shipped, in
`archive/festoon_clicker/` — see the README there. Don't bring it back into
`lightgroup_tools/` without an explicit ask.

```
lightgroup_tools/          <- folder name is FROZEN; IFTK and existing installs key off it
├── __init__.py            registration hub + reload guard. No feature code.
├── core/                  shared infrastructure
│   └── diagnostics.py     toolkit-wide support report; tools add sections
├── lightgroups/           the 'Lightgroups' sidebar tab
│   ├── operators.py
│   ├── solo.py            Solo Light mode
│   ├── output_check.py    checks each File Output EXR after every frame
│   └── panels.py
└── camera_overlay/        the 'Camera Overlay' sidebar tab
    ├── overlay.py         shader, texture cache, draw handler, status string
    ├── props.py           the scene PropertyGroup (scene.cam_overlay)
    └── panels.py
```

Each subpackage owns a `classes` tuple; `__init__.py` concatenates them. A new
tool = a new subpackage + two lines in `__init__.py`, and it gets **its own
sidebar tab** (`bl_category`) rather than adding buttons to an existing one.
Unrelated tools must not share a panel.

**The reload guard's order is load-bearing: leaf modules first, then their
packages.** Each package builds `classes` at import time, so reloading a package
before its submodules rebuilds that tuple from stale classes -- the same
`has no attribute` bug the guard exists to prevent, one level up.

**Never put a relative import inside a function or class body.** It only
resolves when that code path runs, so moving the module repoints it silently and
the failure surfaces in production when a user clicks a button. Reach the top
package through `sys.modules[__name__.partition('.')[0]]` instead. Phase 5 of
`tests/run_registration_test.sh` enforces this.

## Production context

The team renders motion graphics for LED screens behind performers at concerts. Pipeline is Blender → After Effects, where renders get animated/keyed to the music beat per layer. Because of that beat-syncing, almost every render has to be split into separate light passes (Blender lightgroups) so each light can be controlled independently in post.

Typical scenes: hundreds of lights, 30+ lightgroups. An "ambient" layer is needed on almost every render — sometimes that's the World HDRI alone, sometimes World combined with fill lights (handled in AE).

## What `lightgroup_tools` does

Sidebar panel in 3D View, Compositor, and View Layer properties. The 3D View and Compositor panels share one `_draw_tools()` helper in `lightgroup_tools/lightgroups/panels.py` and show an identical button set — add new buttons there, not per-panel. (The compositor panel originally showed a deliberate subset; David changed his mind in Aug 2026 and wants full parity.) The View Layer properties panel is deliberately still a short subset — leave it that way. Four operators:

- **Create Lightgroups for Each Light** (`LIGHTGROUP_OT_create_for_each_light`) — auto-creates one lightgroup per light, per emissive material's host objects, plus a `World` group. Shortcut for simple, well-named scenes; not used for big scenes. Includes black-emission-color filtering for both Principled BSDF (`Emission Color`/`Emission Strength`) and standalone Emission shader nodes — a material with strength > 0 but pure black color does NOT get a lightgroup. Color sockets that are linked count as emissive (we can't evaluate textures statically).
- **Add Selected to Lightgroup** (`LIGHTGROUP_OT_assign_to_lightgroup`) — primary daily-use operator for complex scenes. Dropdown picker of existing lightgroups + "New Lightgroup..." option. Fills a real gap in Blender (no built-in bulk-assign-selected exists).
- **Clear All Lightgroups** (`LIGHTGROUP_OT_clear_all_lightgroups`) — wipes lightgroups from the active view layer.
- **Setup Denoise Compositor** (`LIGHTGROUP_OT_denoise_all_cycles`) — wipes the compositor and rebuilds it: one Denoise node per lightgroup, then writes a multilayer EXR with all groups + remaining passes as layers. **This step is non-negotiable** — Blender's render-time denoiser flattens the image, so per-pass denoising has to happen here, and it's the accepted Cycles workflow even though it scales to N denoise nodes (related: [Cycles T101418](https://developer.blender.org/T101418)).
  - Output: `//../../04_Renders/01_Components/{blend_name}_`
  - Format: `OPEN_EXR_MULTILAYER`, 16-bit half, DWAB codec, Filmic sRGB
  - Cycles only — hard-checks `render.engine == 'CYCLES'` and bails otherwise
  - **5.2+ writes ONE EXR per frame** (`setup_single_exr`, from Noah's patch): `render.save_output` is turned off so the File Output is the only writer, every `Denoising *` pass is skipped, and `Image` gets its own Denoise node unless scene AND view layer render denoising are both on. A Group Output shows the beauty in the render window. **`Alpha` stays even though its values are Filmic-damaged and `Image.A` is the true alpha**: the template's Stencil Luma takes its matte from that layer's RGB (PostPost measured it on the ambient chase; `PostPost/docs/NIGHT_REPORT_2026-10-28.md`), and a missing layer blanks those comps in AE with no error. 5.0/5.1 keep the old two-file setup because `save_output` doesn't exist there. The setting saves in the .blend, so on a processed file an animation render with compositing off or no active File Output errors out. With it off, Overwrite-off no longer skips finished frames on a re-run (it checks the render output path), so a restart re-renders from the first frame.
  - **Every item stays RGBA, and that's the standard.** No float data layers (David, Nov 2026): the team uses Mist, not Depth, stylistically and to separate layers by distance, so exact measurements aren't needed, and float layers cost too much (a rough 40 MB per frame at 7700x1440 for two). Depth stays supported but new jobs shouldn't render it; the team `startup.blend` already has it off. Normal and Position are untouched. Noah's patch typed these as FLOAT/VECTOR; that part wasn't taken. Also: EXRDemux and PostPost read only R/G/B/A, Mist is used in AE as Luminosity and a Luma matte, and DWAB is lossy on `.Y`. One EXR per frame is firm: never a separate data file. Crypto needs nothing: already float and bit-exact as a plain RGBA item (tested on a toy scene; a teammate has reported crypto trouble, not yet seen).
  - **Post-render output check** (`lightgroups/output_check.py`): after each frame, each active multilayer File Output's file must exist, be newer than the frame's start, have complete EXR offset tables and enough parts. Problems print and show red in the panel; the render carries on. It parses EXR headers in plain Python, so it has no library dependency, and it is read-only. It catches the silent out-of-memory failure below (tested on hand-damaged files, not a real OOM).
  - **Out of RAM fails silently:** with 100+ groups at 7700x1440 (~42 GB peak) failed allocations still log `Saved:` and exit 0, leaving truncated or missing EXRs. Check file sizes/layer counts after. A File Output on FOLLOW_SCENE writes tone-mapped values clipped at 1 even into EXR; only OVERRIDE + Linear Rec.709 is scene-linear. See `notes/many_lightgroups_split_output_findings.md`.

Installs and updates come through IFTK, the team's tool manager (since v1.1.0). See below.

## Cycles-only by design

The compositor setup is Cycles-only. EEVEE lightgroup support is different/newer and **out of scope right now**. There's a researched plan for an EEVEE/Cycles hybrid pipeline (extend this addon to drive view-layer-per-group preview renders in EEVEE, keep Cycles native lightgroups for finals) — see the `project_eevee_hybrid_future` memory for the recommendation. Don't start on it without explicit ask.

## Hardcoded conventions (intentional — leave alone unless asked)

These are real production-team conventions, not bugs to fix:

- **Active view layer** is used by the denoise operator (was hardcoded to `"ViewLayer"` until Aug 2026). The Render Layers node is explicitly pinned to `context.view_layer` via `renderLayersNode.scene` / `.layer` — a freshly created `CompositorNodeRLayers` otherwise defaults to the scene's *first* view layer, which in multi-view-layer scenes reads sockets from the wrong layer and produces a bogus "Denoising Data not enabled" error.
- **Output path** assumes `04_Renders/01_Components/` exists two folders up from the .blend (typical numbered-folder production layout).
- **EXR settings** (DWAB / 16-bit half / Filmic sRGB) match the team's AE pipeline.

## Blender 4.5 vs 5.0 compatibility

`bl_info` targets `(5, 0, 0)`. Some 4.5 fallback code is intentionally still in place — check with David before removing any of it:

- `scene.compositing_node_group` (5.0) vs `scene.node_tree` + `use_nodes` (4.5)
- `outputNode.file_output_items.new(...)` (5.0) vs `outputNode.layer_slots` (4.5)
- `outputNode.directory` + `file_name` (5.0) vs `outputNode.base_path` (4.5)

In 5.0, `compositing_node_group` may be `None` until you create it — `lightgroups/operators.py` handles this via `bpy.data.node_groups.new(name="Compositor", type='CompositorNodeTree')` then assigning to `scene.compositing_node_group`.

## Release + dev workflow

**Since v1.1.0 the add-on has no self-updater.** IFTK, the team's tool manager
(Noah's repos: the `noschmo-manager` app and the `noschmo-catalog` list of tools),
installs, updates and uninstalls it. The add-on makes no network calls, starts
no threads, shows no update popups and writes no staging or backup folders.
Phase 9 of `tests/run_registration_test.sh` checks the source for this. v1.0.21 was the last
self-updating build. Its release note and panel line told the team to switch.

What IFTK needs from this repo:
- **A Blender build zip with `addon/lightgroup_tools/...` at the top.** IFTK copies
  each folder under `addon/` into `scripts/addons/` of every Blender 5.0+ it finds.
  Before copying, it DELETES the existing folder, so it replaces a hand-installed
  copy cleanly. Noah's `scripts/publish.py` can also build the zip from the plain
  `lightgroup_tools/` folder. The layout is in `noschmo-catalog/docs/FORMAT.md`.
- **The folder name stays `lightgroup_tools`.** That's how an IFTK install lands on
  top of the copy people already have.
- IFTK keeps its own receipt of the installed version and never reads `bl_info`.
  Keep `bl_info["version"]` in step anyway: the Diagnostics report prints it.
- **Never run `publish.py release/add`.** It pushes to the catalog's `main` and
  uploads a release, so every teammate gets the build straight away. Noah
  publishes. Changes go to him as PRs. The planned catalog entry is in
  `notes/iftk_catalog_entry.md`.
- **Be on `prod` before letting IFTK touch your Blender.** On `dev`, the add-on folder
  is a junction into this repo. IFTK's normal delete is Node's `fs.rmSync`, which
  should remove only the link. Its admin fallback uses PowerShell's
  `Remove-Item -Recurse`, which has a history of following junctions into their
  target. Neither path has been tested against a junction.

Release process:

1. Bump `bl_info["version"]` in `lightgroup_tools/__init__.py`.
2. Build the hand-install zip `lightgroup_tools_v{maj}_{min}_{patch}.zip` at the repo
   root (package at the zip root, no `__pycache__`). It's still the recovery path:
   Install from Disk, a new machine, or a broken install.
3. Build the IFTK zip (`addon/lightgroup_tools/...`) for Noah, or point him at the folder.
4. Commit, push, and tag `vX.Y.Z`. **Don't create a GitHub release.** v1.0.21 and
   older clients still check this repo's `/releases`. A release there would offer
   them a build with no updater.
5. Write the catalog `notes` line for Noah (one short line, same register as below).
6. Leave David on the released build with `.\dev_install.cmd prod`.

**Don't autonomously bump versions or build release zips after a code change.** Wait for David to explicitly say it's time to release ("bump and publish", "let's ship it", etc.). Multiple changes may land in the same release; some changes are exploratory and shouldn't ship at all.

**Committing and pushing are Claude's to do.** Match the terse repo style (`vX.Y.Z — short description`, or a plain short description for other work).

**Release notes:** one short line naming what changed, in terms an artist recognises. No prose, no AI talk, no co-author trailers. IFTK shows it beside the tool, and it's what the team reads before updating. Get David's approval on the line before every release.

**Dev install: use `dev_install.cmd`, and PROD is the default state.**

```bash
.\dev_install.cmd status    # which one am I on?
.\dev_install.cmd dev       # junction -> repo working tree
.\dev_install.cmd prod      # reinstall the newest release zip
```

**Always tell David the `.cmd`, never the `.ps1`.** Windows blocks `.ps1` files by default. The `.cmd` wrapper passes `-ExecutionPolicy Bypass` for that one process, so **nothing on his machine is changed**. Don't suggest `Set-ExecutionPolicy`.

**David is a working artist first.** He wants to run the same build as his team, and only dips into development for short sessions. So `prod` (a real installed copy of the newest `lightgroup_tools_v*.zip`) is where his machine should normally sit. `dev` is for the length of a test, then straight back. Leaving him on `dev` points his production Lightgroups tab at the working tree. When a change seems to have no effect, check `status` first. An IFTK install replaces the junction with a real folder.

`dev_install.ps1` deletes a junction with `Directory.Delete` rather than `Remove-Item -Recurse`, which has a history of following the link and eating the TARGET (here, the repo).

No CI. `tests/run_registration_test.sh` runs a headless registration/reload regression check against any installed Blender version. It should be green before any release.

## Leftovers from the self-updater (up to v1.0.21)

- Teammates' config dirs may still hold `lightgroup_tools_update/` (a staged build)
  and `lightgroup_tools_backup/` (the previous version). Nothing reads them any more.
  They are left alone on purpose: about 1-2 MB, and the add-on doesn't delete
  files on the team's machines.
- The old updater copied files over and never deleted, so long-lived installs may
  carry orphans such as `festoon/` or a flat `updater.py`. An IFTK install deletes
  the folder first, which clears them.
- **`__init__.py` keeps its reload guard** (`if "core" in locals(): importlib.reload(...)`).
  It covers Blender's **Install from Disk** over an already-enabled older version,
  which would otherwise hand `register()` stale cached modules. It still matters:
  someone may install the hand-built zip over an older copy.
- The updater's design notes and quirks are in git history (`core/updater.py` up to `v1.0.21`).

## Code-review notes when working on this addon

- This addon was iterated through several conversations before Claude Code. Some prior changes were claimed "fixed!" without verification against the live file (e.g., the black-emission detection landed for Principled BSDF but the equivalent fix for the standalone Emission shader was forgotten until now). When changing logic that has a paired/symmetric path, **verify both halves**.
- The `bl_info["version"]`, the zip filename (`lightgroup_tools_v{maj}_{min}_{patch}.zip`), the git tag (`vX.Y.Z`) and the IFTK catalog version all have to stay in sync — easy to bump one and forget another.

## Solo Light

`lightgroups/solo.py`, a MODE toggle in the Lightgroups tab (3D View +
Compositor; not the View Layer subset). While on, whatever lights are selected
are the only ones lit -- click lights in the viewport or outliner and the solo
follows. Clicking a non-light, or deselecting, keeps the current solo. The
World is off in every 3D viewport. Off: exactly what changed is restored.
(v1 was "select, click Solo, unsolo, repeat" with eye-hiding; David wanted a
mode, and hidden lights can't be clicked in the viewport.)

**Muting = ray visibility** (camera/diffuse/glossy/transmission/volume off).
Measured to silence point/area/spot/sun completely in Cycles AND EEVEE, and
the light stays visible and clickable. The selection is followed from
`depsgraph_update_post` (a click fires it; verified with real `view3d.select`
clicks in a GUI run). Each light's own switches are stored and restored
verbatim, as Object pointers (rename-safe).

**Ray visibility reaches the render, so it is never allowed to:**
`render_pre`/`save_pre` write every light's switches back, `render_post`/
`render_cancel`/`save_post` re-mute. A soloed F12 is pixel-identical to an
unsoloed one (headless AND GUI F12), and a file saved mid-solo has no muted
light on disk -- so the farm, or a machine without the addon, renders it
correctly. Re-muting in save_post does not mark the file dirty (verified).
These handlers are the safety story: don't drop any of them. The
registration suite asserts exactly one of each, and none after disable
(they're matched by name, so an importlib.reload can't leave a stale copy).

The World is muted via each 3D view's shading (Scene World off, studio-light
strength 0), never the World datablock -- viewport-only by construction, no
safety net needed. Viewports are recorded by screen name + area index; one
opened mid-mode isn't muted. Only LIGHT objects are muted; emissive meshes
are untouched.

## Camera Overlay

A reference image drawn over the camera frame in the viewport. Own sidebar
tab. Built from `SPEC_camera_image_overlay.md`, which exists because a
commercial addon (Camera Guides Pro) does this and **fails silently on some
machines** — guide lines draw, the image never appears, nothing in the
console. The design makes each of its root causes structurally impossible
rather than merely fixed.

**What David actually uses: load an image, Normal mode, opacity slider.** Mask
mode and the transform controls are built and tested, but they live in
sub-panels that start collapsed so the main panel is just the picker and the
opacity slider. Don't promote them without asking. David has since added two
things to the main panel by request: the active camera's passepartout (the
camera's real setting, usable with no image) and **Match File to Image
Resolution** (`camoverlay.match_resolution`, greyed by its poll when no image).
It sets resolution X/Y only and leaves Resolution % alone, and refuses a 0x0
(missing-file) image rather than writing Blender's 4x4 floor.

**Viewport only, and camera view only.** A `POST_PIXEL` draw handler never
touches the render pipeline, and drawing is gated on
`region_data.view_perspective == 'CAMERA'`. It is a working aid for matching a
shot, not a compositing feature. The panel used to carry a "Viewport only, in
camera view" line; David had it removed (the team knows), so don't put it back.
Picking an image switches `enabled` on (the `image` update callback); clearing
it never switches it off.

**The image is a `PointerProperty(type=bpy.types.Image)`, never a path
string.** This is the whole design. The original stores a
`StringProperty(subtype='FILE_PATH')`, feeds it to `os.path.exists()` and
calls `bpy.path.abspath()` nowhere, so a Blender-relative path (`//ref/shot.png`)
fails the check and the draw silently no-ops. An Image pointer deletes the bug
class outright: Blender resolves relative paths, packing and reloads,
`template_ID` gives the standard Open/unlink/pack widget for free, and there is
no format allow-list to fall out of date. A test pins the property to
`POINTER` — if it ever becomes a string, everything above comes back.

**Nothing reads `image.pixels`.** The original runs `list(image.pixels)`
unconditionally, before the mode branch, and Normal mode never uses it. A 4K
RGBA image is ~33M Python floats; 8K raises `MemoryError`, which a broad
`except` swallows into a blank frame. All per-pixel work is in the fragment
shader. Enforced by an **AST walk** in the test suite, not a grep — the source
comments explaining the rule would trip a substring match.

**Every bail-out sets a status string the panel renders in red.** The original
has three early returns that produce no output at all, which is the entire
reason its bug was unreportable. Diagnostics themselves now live in
`core/diagnostics.py` and cover the whole toolkit — see below.

**GPU state is saved and restored, not reset to assumed defaults.** The
original hardcodes the restore to `NONE`/`LESS` whatever the state was on
entry, which corrupts *other* addons' overlays.

**One shader, both modes, `GPUShaderCreateInfo` unconditionally.** No backend
branching: the original sniffs Metal from `platform.system()` and reads
`prefs.system.gpu_backend`, which reports the *pending* preference and
disagrees with reality until restart. `create_from_info` is correct on OpenGL,
Vulkan and Metal from 4.5 on.

Three places the spec had to be corrected, all verified against real Blender:

- **`texture.free()` does not exist.** `GPUTexture` has no `free` method on
  4.5, 5.0, 5.1 or 5.2 — the spec's cleanup step would raise `AttributeError`.
  `gpu.texture.from_image` returns *Blender's own* cached texture for that
  image (calling it twice returns the same object) and the memory is shared,
  so invalidation is done by dropping our reference. Never remove the image
  datablock either — that is the original's worst bug.
- **`TRI_FAN` still works but isn't used.** It draws fine on OpenGL in 5.2, but
  fans are unsupported by Vulkan and deprecated in Blender's GPU module, so the
  quad is `TRIS` with a two-triangle index buffer. One extra line.
- **`rotation` is an `ANGLE` property**, so Blender shows degrees and stores
  radians. `quad()` takes the value straight — converting again would be a
  silent 57x error.

**`bpy.data` is restricted during `register()`.** It is a `_RestrictData` with
no `scenes` attribute at all, so syncing the draw handler to the open file's
`enabled` state there raises and takes the whole addon's registration down with
it. The initial sync is deferred through a zero-interval `bpy.app.timers`
callback; `sync_handler` also backs off on `AttributeError` so it stays safe to
call from anywhere. The registration suite caught this.

**Handler lifetime:** `enabled` owns it, `enable_handler` is idempotent, and
the module's own `load_post` handler drops the texture cache and re-syncs
(because `enabled` is saved in the .blend, so the file being opened decides).
A test toggles 20 times and asserts no leak, per the spec's acceptance list.

**Colour space:** the image's own setting is used as-is; nothing mutates the
user's datablock. Noted in the Support sub-panel.

**Diagnostics: `core/diagnostics.py`, toolkit-wide.** One button
(`lightgroup.write_diagnostics`, on the Lightgroups tab and the Camera Overlay
Support sub-panel) writes a report and opens the folder holding it, so "it
doesn't work" arrives with a file attached. Report covers addon version,
Blender/build/platform, GPU backend/vendor/device, whether each tab actually
registered, scene/render settings, and a section per
tool. Tools contribute via `register_section` so core never imports them.

Rules it lives by, because it runs on the team's machines mid-season:

- **It never deletes, overwrites or moves anything.** Each run writes a NEW
  timestamped file and opens with mode `'x'` so it cannot clobber. Old reports
  stay until someone removes them -- they are a couple of KB, and "the addon
  deleted a file on my machine" is not a trade worth making. A static AST check
  in phase 7 fails the suite if `os.remove`/`shutil.rmtree`/etc. ever appears in
  the diagnostics or camera-overlay code.
- **It writes only under `<config>/lightgroup_tools_diagnostics/`** -- never near a .blend, a render, or `04_Renders/`. Phase 7
  snapshots the sandbox and asserts exactly one new file, nothing modified,
  nothing removed, and that the open .blend is not marked dirty.
- **It never opens a window in background mode.** `bpy.ops.wm.path_open` still
  asks the OS to open a file browser with no GUI running, so a headless test run
  spawned an Explorer window per Blender version on David's desktop. Guarded on
  `bpy.app.background`.
- Every probe is individually guarded; a broken section says so and the rest of
  the report still arrives. Section providers must be READ-ONLY -- camera
  overlay reports `shader_state()`, never `get_shader()`, which would attempt a
  compile and could create the fault it is describing.

**A failing building tool must not sink Lightgroups.** Blender aborts
`addon_enable` on the first exception out of `register()`, and the observed
result is not a clean failure: the addon is left marked **DISABLED while its
classes stay registered**, so Lightgroups half-works for that session and is
gone entirely after the next restart, preferences orphaned. `__init__.py`
therefore runs `camera_overlay.register()` through a
`_guarded()` wrapper that prints the full traceback and carries on.
`core/` and `lightgroups/` are deliberately NOT guarded — if those fail the
addon really is broken. Phase 6 of the registration suite breaks each building
tool in turn and asserts the denoise operator and Lightgroups panel are still
there. This matters because David is an artist on a deadline: a GPU quirk in a
convenience tool must never cost him his lightpass workflow.

**Nothing escapes the draw handler.** A handler that raises does so on *every*
redraw — console spam, a stuttering viewport, and GPU state possibly left as we
set it. `draw()` is a guard around `_draw()`: on failure it sets the status,
restores blend/depth by hand (the inner `finally` may not have run), and goes
**quiet** rather than failing sixty times a second. Toggling Enable is the
retry. Tested by making `_draw` raise and asserting nothing propagates.

**Platform coverage.** OpenGL and Vulkan are both verified green by the pixel
suite on David's own hardware profile (NVIDIA/Vulkan is what he runs). **Metal
is untested — there is no Mac here.** That is why `maskMode` and `invert` are
`INT` push constants rather than `BOOL`: a bool inside a push-constant block
has ambiguous size (1 byte or 4), Metal emulates push constants differently
again, and `uniform_int` has none of `uniform_bool`'s scalar-vs-sequence arity
history. Same behaviour, one less untestable assumption. If a Mac user reports
trouble, the Diagnostics button reports the backend and the guards above mean
the worst case is a missing overlay, not a broken addon.

Deliberately NOT built, per the spec: line guides of any kind, presets,
per-camera syncing, aspect masking, focal points, z-depth. There is no
`blender_manifest.toml` either — the spec asks for extension format, but this
repo ships one `bl_info` addon (now through IFTK's `addon/` layout), and that wins.

## Tests

No framework, no CI — four headless scripts, all of which sandbox Blender so they never touch the real install:

```bash
tests/run_registration_test.sh          # add "5.0" etc. for a specific Blender
tests/run_camera_overlay_test.sh
tests/run_solo_test.sh
tests/run_single_exr_test.sh
```

- **`run_registration_test.sh`** — every class/operator/panel/pref still resolves across a cold enable, an in-session reload (sys.modules eviction), and an `importlib.reload` over a live addon; plus a clean-teardown check, a static scan forbidding relative imports inside function bodies, and (phase 9) an AST scan forbidding network/thread imports and update-folder paths anywhere in the package. Sandboxes `BLENDER_USER_SCRIPTS` and `BLENDER_USER_CONFIG`.

- **`run_single_exr_test.sh`** — real Cycles renders read back from disk: one file per frame, the layer list, Crypto and `Image.A` against a lossless render output from the same render, and the output check against missing, stale, cut-off and short files. On 5.0/5.1 it pins the two-file setup and runs only the output check.
- **`run_camera_overlay_test.sh`** — the only suite that tests the GPU for real. On 5.2 it calls `gpu.init()` to get a headless GL context, compiles the overlay shader, draws into a `GPUOffScreen` and **reads the pixels back**. Add `--gpu-backend vulkan` to the Blender invocation to run the identical suite on Vulkan — **both backends verified green**, which is what makes the "no backend branching" rule safe to rely on (David's machine is Vulkan/NVIDIA; `BOOL` push constants were the specific worry and they are fine): opacity 0/0.5/1.0, mask above and below threshold, invert, per-channel selection, and tint. Also checks the fit/scale/offset/rotation/flip maths against a known frame, that 20 enable/disable cycles leak no handler, and (by AST walk) that nothing reads `.pixels`. On 4.5/5.0/5.1 there is no `gpu.init`, so the GPU phases are skipped with a printed NOTE and the rest still runs — a skip is reported, never silently passed.
- **Every runner must sandbox `BLENDER_USER_EXTENSIONS` too.** `read_factory_settings` syncs extension wheels against "no extensions enabled" and DELETES the real install's `extensions/.local` site-packages (it stripped psutil from David's 5.2 on 2026-10-11; Blender re-synced it on next start). Scripts + config sandboxing alone does not cover it.
- All four scripts install an atexit guard that forces a non-zero exit unless an explicit verdict line is reached. An uncaught exception aborts the Python script but Blender still exits 0, so a crashed run would otherwise look identical to a clean one.

**`bpy.ops` attribute access is entirely lazy** — `hasattr(bpy.ops.totally_fake, "nope")` is `True`, `dir(bpy.ops)` doesn't list registered categories, and even `.idname()` on a nonexistent operator returns without error. A `hasattr`-based existence check is therefore vacuous and will pass with every operator missing (this was live in the registration suite for several releases). Use `operator.get_rna_type().identifier`, which raises `KeyError` when unregistered and confirms the idname maps to the expected class.

The `EXPECTED_*` lists in `tests/test_registration.py` are a deliberate contract — when a change legitimately renames or moves something, edit them on purpose rather than letting them drift. Beyond these, real testing is still loading the addon in Blender against a curated test scene (`tests/build_test_scene.py`).

## Roadmap / deferred work

Don't start these without explicit ask, but they exist:

- **Mesh-attribute lightgroup creation** — operator that reads `Column`/`Row`/`Depth` mesh attributes (set in Geometry Nodes) and creates lightgroups like `Column_1`, `Column_2`. Has been prototyped as a standalone script outside this repo. See the `project_mesh_attribute_feature` memory for the design history and known caveats (each emission object can only be in one lightgroup at a time, so this needs to run once per attribute pass).
- **EEVEE hybrid pipeline** — see `project_eevee_hybrid_future` memory.
