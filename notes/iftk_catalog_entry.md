# Lightgroup Tools in IFTK: catalog entry and notes for Noah

Proposed for a PR to `noschmo-catalog`. Not added yet. Noah publishes.

## tools/lightgroup_tools.json (source fields)

```json
{
  "id": "lightgroup_tools",
  "name": "Lightgroup Tools",
  "host": "blender",
  "channel": "release",
  "description": "Lightgroups, per-pass denoise EXR, Camera Overlay.",
  "thumbnail": "thumbnails/lightgroup_tools.jpg",
  "version": "1.1.0",
  "notes": "Now installed and updated through IFTK."
}
```

- `id` must stay `lightgroup_tools` forever. It matches the add-on folder name, so an
  IFTK install replaces the copy people already have.
- Build: the plain `lightgroup_tools/` folder at tag `v1.1.0`. `publish.py` wraps it as
  `addon/lightgroup_tools/` because it has no `blender_manifest.toml`. Or use
  `dist/lightgroup_tools-1.1.0-blender.zip`, built locally with that exact layout.
  The same zip works on Mac and Windows (pure Python).
- Thumbnail: still needed (a frame of the Lightgroups tab works).
- Guide: optional. `guides/lightgroup_tools.md` from `_TEMPLATE.md`, if wanted.

## Verified locally (2026-11-18, Blender 5.2, sandboxed)

I unzipped the IFTK zip and copied it the way `installer.js` does (delete the folder,
then copy) on top of a v1.0.20 install that had a staged update waiting. Results:
- Blender loads 1.1.0.
- The old `festoon/` folder is gone.
- The staged update was ignored.
- No update operators and no threads.
- The only handlers are Solo Light, the output check and Camera Overlay.

## IFTK issues to raise with Noah (PRs from his repo, not this one)

1. **Hand-installed copies show "Not installed".** `installer.js` `presentByHand()`
   returns false for any tool that isn't AE. Teammates who already have
   Lightgroup Tools will see "Not installed" rather than "Installed (unknown
   version)". Installing still overwrites the same folder, so it's cosmetic. A fix
   would check `<blender>/scripts/addons/<id>` for `host: "blender"`.
2. **Junctions and symlinks in `scripts/addons/`.** The install deletes the existing
   folder first. The direct path (`fs.rmSync` recursive) should remove only a
   junction or symlink, not its target. The Windows admin fallback uses
   `Remove-Item -LiteralPath ... -Recurse -Force`, and on Windows PowerShell 5.1
   that command has a history of following junctions into their target. Neither
   path has been tested against a junction. A developer with a dev junction into a
   git checkout could lose source files. Suggest checking `lstat` for a
   link/junction first and unlinking it without recursing.
