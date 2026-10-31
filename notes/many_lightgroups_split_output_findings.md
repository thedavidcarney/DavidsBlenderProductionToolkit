# Many light groups, split File Outputs: RAM, linear output, stability (Oct 2026)

Findings from the neon arches colonnade job, for a future Toolkit session. Nothing in
`lightgroup_tools/` was changed. Related: section 6 of
`heart_stage_carousel_lightpass_findings.md` (false EXR OOM at 65 parts).

- **Blender:** 5.2 LTS, `lightgroup_tools` denoise compositor.
- **Scene:** 7700x1440, **123 light groups**, split across **8 File Output nodes**
  (a main EXR plus one EXR per neon row). CPU compositor, CPU render denoise.

## 1. RAM: the split denoise compositor needs ~42 GB, and failures are silent
- **Peak:** about 42 GB with the machine otherwise idle.
- **Failure:** a second render ran with David's other apps open. Allocations failed at about
  49 GB total: `Calloc returns null: len=133056000 in Combined_NeonR5_04` ... through `R7_23`,
  58 layers in all. (133 MB = one 7700x1440 RGBA float buffer.)
- **What Blender reported:** still logged `Saved:` for the files, and the process **exited 0**.
- **What was actually on disk:** the NeonR5 EXR was 0.7 MB (truncated). The R6 and R7 EXRs were
  never written.
- **Caught by:** the job's wrapper script, which checks file sizes after the render and exits 1.
  Without that check the render looks successful.
- **Rule of thumb:** budget ~133 MB per denoised layer at this resolution, times the layers held at
  once, and close other apps (AE in particular) before a big light-pass render.

## 2. Linear output: FOLLOW_SCENE File Outputs are tone-mapped, even into EXR
- A File Output with colour management on **FOLLOW_SCENE** writes **Filmic tone-mapped values clipped
  at 1.0**, even to a half-float EXR.
- Only **OVERRIDE with view transform Standard / Linear Rec.709** writes scene-linear values.
- With linear output the light groups **sum to Combined at +0.000%**. With tone-mapped output they
  can't (Filmic per layer isn't additive).
- This touches the shipped convention (EXR "Filmic sRGB") and the AE side's additive math. Any change
  to the default must be agreed with the `ae-expert` (EXRDemux/ChaseMaker) first. See also
  `notes/toolkit_lightgroup_sum_vs_combined.md` in BlenderExpert.

## 3. GPU compositor is not an option at this size
- At full res with 123 denoised groups it would need about **40 GB of VRAM**. It doesn't fit a 24 GB card.
- Stay on the CPU compositor for big light-pass jobs.

## 4. Light groups aren't bit-stable across renders with different lighting
- Adding a world light shifted the neon groups' sums by **+1 to 5%**, even though the neon lights
  themselves didn't change. Likely cause: adaptive sampling stops at different sample counts per pixel.
- **Don't mix group files from renders with different lighting.** Re-render the whole set, or keep
  every group file from one render.

## Suggested feature (future Toolkit session)
A guard around the denoise render, so a silent truncation can't ship:
1. **Before the render: RAM check.** Estimate `width * height * 4 ch * 4 bytes * (denoised layers + buffers)`
   and compare against free RAM (e.g. `psutil.virtual_memory().available`, or a platform fallback).
   Warn in the panel when the estimate is close to or above free memory, and suggest closing apps or
   splitting the render.
2. **After the render: output check.** For each File Output node, confirm the file exists, its size is
   plausible (not a sub-MB stub), and its EXR layer/part count matches the node's input count.
   Report missing or short files loudly instead of trusting `Saved:` and exit code 0.
   A `render_complete` handler, or a small "Verify Outputs" button, would cover both GUI and headless use.

Layer naming is untouched by these findings. If a fix changes names or pass structure, the
`ae-expert` side (EXRDemux picks layers by name) must be checked.
