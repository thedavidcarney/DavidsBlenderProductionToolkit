# DavidsBlenderProductionToolkit

A repo of Blender addons for David Carney's team. Currently contains one addon (`lightgroup_tools/`); the "toolkit" name is **aspirational** — more addons are intended to live here over time. One repo by design, so all addons can share one update mechanism (the GitHub-release-based updater in `lightgroup_tools/updater.py`). Don't suggest splitting addons into separate repos.

## Production context

The team renders motion graphics for LED screens behind performers at concerts. Pipeline is Blender → After Effects, where renders get animated/keyed to the music beat per layer. Because of that beat-syncing, almost every render has to be split into separate light passes (Blender lightgroups) so each light can be controlled independently in post.

Typical scenes: hundreds of lights, 30+ lightgroups. An "ambient" layer is needed on almost every render — sometimes that's the World HDRI alone, sometimes World combined with fill lights (handled in AE).

## What `lightgroup_tools` does

Sidebar panel in 3D View, Compositor, and View Layer properties. The 3D View and Compositor panels share one `_draw_tools()` helper in `__init__.py` and show an identical button set — add new buttons there, not per-panel. (The compositor panel originally showed a deliberate subset; David changed his mind in Aug 2026 and wants full parity.) The View Layer properties panel is deliberately still a short subset — leave it that way. Four operators:

- **Create Lightgroups for Each Light** (`LIGHTGROUP_OT_create_for_each_light`) — auto-creates one lightgroup per light, per emissive material's host objects, plus a `World` group. Shortcut for simple, well-named scenes; not used for big scenes. Includes black-emission-color filtering for both Principled BSDF (`Emission Color`/`Emission Strength`) and standalone Emission shader nodes — a material with strength > 0 but pure black color does NOT get a lightgroup. Color sockets that are linked count as emissive (we can't evaluate textures statically).
- **Add Selected to Lightgroup** (`LIGHTGROUP_OT_assign_to_lightgroup`) — primary daily-use operator for complex scenes. Dropdown picker of existing lightgroups + "New Lightgroup..." option. Fills a real gap in Blender (no built-in bulk-assign-selected exists).
- **Clear All Lightgroups** (`LIGHTGROUP_OT_clear_all_lightgroups`) — wipes lightgroups from the active view layer.
- **Setup Denoise Compositor** (`LIGHTGROUP_OT_denoise_all_cycles`) — wipes the compositor and rebuilds it: one Denoise node per lightgroup, then writes a multilayer EXR with all groups + remaining passes as layers. **This step is non-negotiable** — Blender's render-time denoiser flattens the image, so per-pass denoising has to happen here, and it's the accepted Cycles workflow even though it scales to N denoise nodes (related: [Cycles T101418](https://developer.blender.org/T101418)).
  - Output: `//../../04_Renders/01_Components/{blend_name}_`
  - Format: `OPEN_EXR_MULTILAYER`, 16-bit half, DWAB codec, Filmic sRGB
  - Cycles only — hard-checks `render.engine == 'CYCLES'` and bails otherwise

A self-updater (`updater.py`) checks GitHub releases, downloads on demand into `<config>/lightgroup_tools_update/`, and installs on next Blender startup via a `load_post` handler that backs up the current addon folder to `<config>/lightgroup_tools_backup/`, copies the staged files into the addon dir, clears `__pycache__`, cleans up the staging dir, and attempts an in-session reload (`addon_disable` → `addon_enable`) with a restart fallback. A "Restore Previous Version" button is exposed in the panel when a backup exists.

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

In 5.0, `compositing_node_group` may be `None` until you create it — `operators.py` handles this via `bpy.data.node_groups.new(name="Compositor", type='CompositorNodeTree')` then assigning to `scene.compositing_node_group`.

## Release + dev workflow

David tests changes by **cutting a real GitHub release and using the in-addon updater to install it in Blender** — deliberately, to validate the user-facing experience including the updater itself on every change. The updater needs to be **rock-solid** because a broken updater strands existing users.

Release process:

1. Bump `bl_info["version"]` in `lightgroup_tools/__init__.py`
2. Zip the `lightgroup_tools/` folder as `lightgroup_tools_v{maj}_{min}_{patch}.zip` at repo root
3. Commit and push
4. Tag a GitHub release with `vX.Y.Z` (the updater parses `tag_name` and expects exactly that format — see `updater.py:57`)
5. Test in Blender: "Check for Updates" → "Download Update" → restart

**Don't autonomously bump versions or build release zips after a code change.** Wait for David to explicitly say it's time to release ("bump and publish", "let's ship it", etc.). Multiple changes may land in the same release; some changes are exploratory and shouldn't ship at all. After a code change, just make the change and stop — don't proactively bump `bl_info["version"]` or rebuild the zip.

**When David does call for a release: always provide both a commit message AND a release message in the same response, ready to copy-paste.** He uses GitHub Desktop for the commit and the GitHub web UI for the release, so he needs them as two distinct ready-to-go strings:
- Commit message: short, matches the existing terse repo style (`vX.Y.Z — short description`)
- Release message: richer prose for the GitHub release notes box, explaining what changed, why it matters, and any user-visible impact (especially migration caveats — e.g. "this fix only takes effect for X → X+1 transitions").

No CI, no test framework. Blender addons are tested by loading them in Blender.

## Updater quirks worth knowing

- The `install_update_on_load` handler hardcodes `addon_name = "lightgroup_tools"` as a string literal. When new addons get added to this repo, the updater will need a generalization story — flagged in the toolkit-naming memory but worth noting here too.
- Update files are staged in `<config>/lightgroup_tools_update/`; rollback backups live in `<config>/lightgroup_tools_backup/`. Both paths are produced by `_get_update_dir()` / `_get_backup_dir()` helpers — change them in one place if needed.
- The handler registers ONLY on `load_post` (which fires after the startup .blend loads, plus any subsequent file open). Earlier code also registered `load_factory_startup_post` based on a misdiagnosis — that event only fires for File > New / factory settings load, not regular Blender startup.
- Update download uses GitHub's `zipball_url` (source archive at the tag), not a release asset. The archive's top-level folder name is unpredictable (`thedavidcarney-DavidsBlenderProductionToolkit-<sha>`) — handled by searching the extracted entries for one that contains a `lightgroup_tools/` subdirectory.
- Tag parsing requires strict `vX.Y.Z` (digits only). Non-numeric tags like `v1.0.11-beta` are rejected with a clear error; keep release tags clean.
- Downloads are validated with `zipfile.is_zipfile` and a non-zero size check before extraction so a truncated download doesn't silently stage garbage.
- Backup is best-effort: if it fails, the install still proceeds (the user just won't have rollback for that version). The backup is created on every successful update; only the most recent backup is retained.
- The "Update vX installed — restart Blender for full effect" banner is sticky (lives in `update_just_installed` pref); the user dismisses it via a button or by ignoring it. It does not auto-clear on restart since prefs persist; user has to dismiss explicitly.
- **In-session reload requires `sys.modules` eviction before `addon_enable`.** Without it, Python returns the OLD module objects from cache and the addon re-registers the OLD code even though new files are on disk. This bit a real user (v1.0.11 → v1.0.12 transition): after restart Blender disabled the addon and re-enabling it raised `module 'lightgroup_tools.updater' has no attribute '<new_class>'`, requiring manual folder delete + zip reinstall. The eviction loop is in `install_update_on_load` between `addon_disable` and `addon_enable` — don't remove it. We also call `bpy.ops.preferences.addon_refresh()` between the eviction and `addon_enable` as belt-and-suspenders. (CGCookie's `blender-addon-updater` relies on `addon_refresh()` alone, no sys.modules eviction — empirically that works for them but our combined approach is more direct.)
- **Auto-check on Blender startup.** The `load_post` handler triggers a once-per-session check (guarded by `_auto_check_done_this_session`), throttled by the `last_auto_check` pref to once per 24 hours. The HTTP call runs in a background thread (`_perform_check_in_thread`) so it doesn't block startup at all; results are applied on the main thread via a `bpy.app.timers` callback (`_apply_check_result`). If a new version is found, an "Update Available" popup appears with **Update Now** and **Ignore** buttons.
- **Manual Check is deliberately decoupled from auto-check.** The "Check for Updates" button hits GitHub every time regardless of throttle (David's explicit choice). It does NOT update `last_auto_check`, so it doesn't affect the auto-check schedule. Don't "fix" this to share state.
- **The "Ignore" button just closes the popup — it does NOT mark the version as dismissed.** Intentional: David wants to nag the team about updates. The popup reappears next Blender session. Don't "improve" this to a per-version dismiss without asking him.
- **After a successful download, a "Restart Blender" popup appears.** "Restart Now" calls `bpy.ops.wm.quit_blender()` (which prompts about unsaved changes); "Later" just closes the popup, and the existing "restart to install" banner in the panel remains.
- **Three operator names that are invoked programmatically, not from panel buttons:** `LIGHTGROUP_OT_update_dialog`, `LIGHTGROUP_OT_restart_dialog`, `LIGHTGROUP_OT_close_dialog`. The first two are popups; `close_dialog` is a no-op used as the dismiss button inside both popups. They're scheduled via the `_schedule_dialog()` helper which defers via timer (calling popup operators directly from a thread/handler context is unreliable).

## Code-review notes when working on this addon

- This addon was iterated through several conversations before Claude Code. Some prior changes were claimed "fixed!" without verification against the live file (e.g., the black-emission detection landed for Principled BSDF but the equivalent fix for the standalone Emission shader was forgotten until now). When changing logic that has a paired/symmetric path, **verify both halves**.
- The `bl_info["version"]` and the zip filename (`lightgroup_tools_v{maj}_{min}_{patch}.zip`) and the GitHub release tag (`vX.Y.Z`) all have to stay in sync — easy to bump one and forget another.

## Roadmap / deferred work

Don't start these without explicit ask, but they exist:

- **Mesh-attribute lightgroup creation** — operator that reads `Column`/`Row`/`Depth` mesh attributes (set in Geometry Nodes) and creates lightgroups like `Column_1`, `Column_2`. Has been prototyped as a standalone script outside this repo. See the `project_mesh_attribute_feature` memory for the design history and known caveats (each emission object can only be in one lightgroup at a time, so this needs to run once per attribute pass).
- **EEVEE hybrid pipeline** — see `project_eevee_hybrid_future` memory.
