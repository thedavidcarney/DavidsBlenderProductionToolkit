# Festoon Clicker (archived)

Click-to-place festoon light strings for Blender: three clicks for start, end and
sag, plus a spiral mode that wraps a string round a trunk. It was a sidebar tab
in Lightgroup Tools up to v1.0.20, and was removed in Nov 2026 because the team
never used it in production. Kept here as an idea, not shipped.

Layout:
- `festoon/`: the package as it was at `lightgroup_tools/festoon/`. Its bundled
  bulb is `festoon/assets/marquee_bulb.blend`.
- `core_tags.py`: the old `lightgroup_tools/core/tags.py`, which festoon imports
  as `..core.tags`.
- `tests/`: the headless suite (`run_festoon_test.sh`, `test_festoon.py`). It expects
  the package inside `lightgroup_tools/`.

To revive it: copy `festoon/` back to `lightgroup_tools/festoon/`, and
`core_tags.py` back to `lightgroup_tools/core/tags.py`. Then restore the import,
the `_guarded()` register/unregister calls and the reload lines in `__init__.py`.
`git log --follow archive/festoon_clicker/festoon/rig.py` shows the history.
The last shipped version with it is tag `v1.0.20`.

Scenes that already hold strands keep working without the add-on. The geometry
node group is saved in each .blend, and Festoon registered no handlers or drivers.

## Design notes

Click-to-place festoon light strings. Own sidebar tab, deliberately separate
from Lightgroups (that one is a per-job workhorse; this is a building tool).

Three clicks: start, end, sag. The sag shape carries to the next strand, and
placement stays active until you escape, so a run of similar strands is fast.
Scroll during the sag step adjusts flatness.

**Scene layout** — `Festoons/` holds the strands you placed (the three control
empties are parented to the strand mesh whose modifier reads them);
`Festoon Bulbs/` holds the bulb SOURCES, hidden with the eye. Sources are kept
out of `Festoons` so the strand list stays readable, but they must stay IN the
view layer — Collection Info instances what the depsgraph evaluates, so
excluding them (monitor icon / exclude checkbox) empties every strand. The eye
is viewport-only and safe. Not a dependency cycle:
Blender models object transform and object geometry as separate depsgraph
components (verified). Each strand collapses to one outliner row, and moving
the strand mesh moves the whole thing rigidly.

**The sag curve is not a real catenary, deliberately.** Straight chord plus an
offset following `shape(t) = 1 - |(t-tc)/tc|^p` (mirrored past `tc`). It is 0
at both ends and exactly 1 at the sag empty, so **the curve passes through the
empty at any `p`** — position and flatness never fight. `p` comes from the sag
empty's SCALE: 1 is a sharp V, ~2.2 reads as a catenary, 5-6 is a flat-bottomed
swag. Not length-conserving: moving an endpoint leaves the sag where you put it.

**Placement draws a live preview.** `overlay.py` adds a `POST_VIEW` draw handler for the duration of the operator: a cursor marker snapped to the surface under the mouse (so you see where a click lands *before* committing to it), the placed anchors, the straight chord for reference, the actual sag curve, and bulb positions along it. Depth test off, so it isn't hidden behind the truss you're hanging from.

The preview calls `shape.curve_points()` — a second implementation of the maths the node group runs. To stop the two drifting, `FLATNESS_TO_EXPONENT` and friends live in `shape.py` and `nodes.py` imports them, and a test pins the preview curve to the generated geometry to within vertex-sampling precision (0.022m measured against a 0.0218m sampling floor). A preview that quietly disagrees with the result is worse than no preview.

Drawing is best-effort: any GPU error disables the overlay and lets placement continue rather than taking the operator down mid-strand. The drawing itself is verified by eye — the geometry it *would* draw is what's under test. (That was once a hard limit: no GL context in background mode. **It no longer is on 5.2** — `gpu.init()` brings up a real offscreen OpenGL backend headlessly, which is how the Camera Overlay suite compiles its shader and checks actual pixels. Festoon's overlay could be tested the same way if it ever misbehaves; nobody has needed to.)

**Cable types** are `Cable Strands` (1-6) plus `Cable Twist` (turns per metre).
1 is a plain cable, 2-3 reads as twisted christmas-light flex, 4+ as braided.
Built by DUPLICATING the spine per strand, tilting each copy along its length,
and sweeping an off-centre profile — Curve to Mesh rotates the profile by the
tilt, so an off-centre circle plus a winding tilt traces a helix in a handful
of nodes rather than per-point frame maths. The bundle radius is
`r / sin(pi/N)`, the radius at which N circles of radius r just touch; a flat
`r` makes 3+ strands interpenetrate into a blob. At 1 strand the offset
collapses to zero so a plain cable stays a plain tube and the twist is inert.

**Spiral mode** (`Wrap Object`) wraps a string around a trunk or column. Two
clicks give base and top; **the object hit by the first click is the wrap
target**, so that click must land on real geometry rather than the empty-space
fallback. A helix is laid out around the axis and every point is raycast
*inward* onto the target, then pushed back out by `Surface Offset` — which is
what lets it follow a tapered trunk instead of floating off a cylinder that
only matches at one height. Points that miss fall back to the search radius so
the curve stays continuous.

Two traps in there. The target's Object Info must be **RELATIVE**, not
ORIGINAL: ORIGINAL means "the target's own local coordinates, ignoring its
transform", so a trunk standing at z=2 gets raycast against a copy of itself
back at the origin — the wrap still looks like a spiral, just the wrong size.
And `Search Radius` must clear the object, or every ray starts inside it and
the helix collapses onto the axis; `create_spiral` sizes it from the target's
dimensions.

**Wraps are set by dragging, not typing.** Three clicks: base, top, then move
the mouse up/down to set the wrap count and click to confirm — the same shape of
interaction as the strand's sag step. Hard-capped at 50 (`MAX_WRAPS`) at
15px per wrap, so a mouse slip costs a turn or two rather than asking Blender
for hundreds of turns and thousands of bulbs. Scroll still nudges by exactly
one. The overlay draws a nominal-radius helix while dragging so the density is
readable; it is deliberately NOT the shrinkwrapped result, which would need a
raycast per point on every mouse move.

**The wrap is sized by PROBING what you clicked, never from the bounding box.**
`estimate_trunk_axis` fires a ray back into the surface at each click, along the
inward normal: the far wall gives the local centre (midpoint) and the local
radius (half the span). Both the axis and the radius come from that.

This exists because bounding boxes are catastrophic on a real tree. A birch is
~7x8m across its canopy and ~0.3m across its trunk, so box-derived numbers gave
a ~4m fallback radius and a ~18m search radius — rays started outside the
foliage and hit leaves and branches long before the trunk, and the wrap ended up
out in the canopy. Probing the click gives 0.159m on the same tree, a search
radius of 0.478m, and a wrap that hugs the trunk.

Consequence worth knowing: the probe measures whatever the click LANDED on. Click
a spot where foliage overlaps the trunk and it measures foliage. Click visible
trunk.

**Rays only accept NEAR-side hits.** The ray is fired from `Search Radius` out
and travels twice that, so it passes through the axis and can strike the back
of the object — the point then lands diametrically opposite where it belongs
and the string appears to jump across. A near-side hit is always closer than
`Search Radius`, which is the discriminator. Misses fall back to
`Fallback Radius` (sized from the target's girth by `create_spiral`) rather
than collapsing onto the axis, because a run of axis-collapsed points is
exactly what reads as a vertical spike.

**The wrap axis is re-centred on the target.** Both clicks land on the object's
SURFACE, so the raw base-to-top line runs up one side rather than through the
middle. Rays cast inward from an off-centre axis reach the surface at angles
that don't advance evenly with the helix parameter — the wrap crawls around one
side and then lurches to catch up, once per turn, which reads in the viewport
as the string shooting straight up before starting the next loop. `create_spiral`
projects both clicks onto the line through the object's bounding-box centre,
keeping the height range and tilt the user chose. Pinned by a test that measures
the angular step between consecutive spine points and fails if the largest is
more than 1.6x the median.

Sample count scales with `Turns` (24 per turn), because a 64-point curve at 6
turns is ten points per turn and reads as a polygon.

The spine is chosen at BUILD time (`create_group(mode=...)`), not with a
runtime Menu Switch — affordable only because every strand already gets its own
group. Everything downstream of the spine is shared between the two modes.

**The cable carries UVs.** `UVMap`, written on the corner domain: **U runs
start to stop along the strand**, V wraps around the tube. Not an area-correct
unwrap — the tube is never flattened — but a stable 0..1 along the run, which
is what a shader wants for chases, gradients or masking part of a strand. Built
by capturing the spline parameter on the spine and on the profile BEFORE Curve
to Mesh, since that is the only way to recover "how far along" once the geometry
is a tube. V stops short of 1.0 because the profile is a cyclic curve whose last
segment closes back onto 0.

**Cable material: a shared `Festoon Cable` datablock by default**, so restyling
one restyles every festoon in the scene. Getting both a working default AND a
modifier slot needs a `Use Custom Cable Material` toggle feeding a Switch,
because of a three-way squeeze: the modifier input can't be written from Python
(it hangs 5.2), a linked group input's interface default stores but never
applies, and an *empty* Material socket CLEARS the material rather than leaving
it alone — so the override can't simply be wired straight in. The default lives
on the Switch's False socket, which is a plain node socket and does work.

**Bulb sources are instanced in ORIGINAL space, the empties in RELATIVE.** The
distinction is load-bearing. RELATIVE delivers a source's geometry transformed
into the strand's space, which bakes the source's world position into the
instance — the bulbs then sit offset from the cable, and moving the strand
changes that offset so they visibly fly off. For instancing you want the
source's own local geometry, which is ORIGINAL. For the control empties the
point genuinely IS their position relative to the strand, so those stay
RELATIVE. The bug hid while the strand and the bulb collection both sat at the
origin.

**Bulbs are instanced, uniform scale, no size randomness** — real bulbs are
manufactured identical. Rotation randomness (tilt + spin) is wanted and is
there.

**The default bulb is a bundled COLLECTION**, `assets/marquee_bulb.blend`,
appended on first use. Real bulb assets are multi-object (glass, filament,
fixture, metal, plus separate Cycles and EEVEE glass variants — the EEVEE one
ships `hide_render=True` so Cycles picks the right one on its own), so the node
group takes both a Collection Info and an Object Info and joins them: fill
either socket, or neither for bare cable. `Separate Children` is OFF, so the
whole collection is ONE bulb rather than each object becoming its own.

Stripped from David's 33MB asset-library file to 654KB by dropping a packed
environment EXR the bulb never referenced. A bulb is ~0.14m wide and 0.24m
tall, which is what makes the 0.5m default spacing sensible.

**Bulb Rotation** is the base orientation applied on Instance on Points, so
random tilt/spin compose on top of a correctly-facing bulb (adding Eulers
instead would be wrong -- Euler addition isn't rotation composition). The
bundled bulb's default is a 180 degree flip about X, **measured, not derived**:
the asset models the bulb along +Y, but that +Y already arrives at world +Z
once instanced, so the obvious-looking -90 about X is wrong. Random Spin
defaults to 0 -- a marquee bulb is radially symmetric apart from its fixture.

Because one bulb emits N depsgraph instances, tests count distinct instance
POSITIONS, not raw instances — otherwise bulb counts would depend on how the
asset happens to be modelled.

**Lightgroups: wired up.** `create_for_each_light` now finds festoon strands
via the `festoon_strand` tag, giving one lightgroup per strand named after it
(`Festoon`, `Festoon_001`). Necessary because a strand emits through INSTANCED
bulbs and so has no material slots of its own — the slot-based scan cannot see
it, and without the tag every festoon would be silently missing from the
compositor and only noticed in the EXR.

Bulb SOURCE objects are tagged `festoon_bulb_source` and skipped by that same
scan. They do carry emissive materials (the bundled bulb's `Coils` is emissive),
but they are excluded from the view layer and render nothing — a lightgroup per
bulb part would be pure noise.

Still nothing is auto-assigned at placement; the end-of-scene button does the
work. See [[feedback-no-intermediate-automation]].

Tags live in `core/tags.py`, not in `festoon/`, because `lightgroups/` is what
reads them and importing festoon from lightgroups would couple two tools that
are otherwise independent.


## Blender 5.2 landmines (found building this)

Found the hard way while building Festoon Clicker. All verified by reducing to
a minimal repro; several are 5.2-only regressions.

- **ASSIGNING a datablock to a modifier input FROM PYTHON hangs Blender.**
  `modifier.properties.inputs[identifier] = <Object|Material|Collection>`
  then evaluating is a hard hang, no error, GUI and background alike.
  
  The socket itself is fine, and this is narrower than it first looked:
  datablock sockets CAN be exposed as modifier inputs, assigned through
  the interface default (`item.default_value = ...`), and edited by the
  user in the modifier panel. All verified. Only the Python write to
  `properties.inputs` is poisoned. Reduces to five nodes (Object Info
  → Curve Line → Resample). 5.0 and 5.1 run the identical setup fine. Setting
  the object straight onto the Object Info node avoids it. **This is why each
  strand gets its own node group** — node datablocks are per-tree. If this is
  ever fixed, a single group can be shared again.
  
  Consequence for festoon: **Cable Material IS a normal modifier input**,
  because nothing assigns it from Python. Bulb Object and Bulb Collection are
  not — those are set at creation time, which is exactly the poisoned write —
  so they live on nodes and are exposed through the sidebar. That asymmetry is
  deliberate, not an oversight.
- **Modifier inputs cannot be written from Python at all on 5.2.**
  `modifier.properties.inputs.<Socket_N>` is a read-only RNA *pointer*;
  `modifier[identifier]` raises (it worked on 5.0/5.1); and the IDProperty
  underneath accepts a write the evaluator then ignores — a cube driven by a
  modifier input stayed at its interface default after being assigned a new
  value. **Drive the node group's INTERFACE DEFAULT instead** (`rig.set_parameter`),
  which only works because groups are per-strand. Both are written so 5.0/5.1
  keep using the modifier value they honour.
- **Multi-type nodes rebuild their sockets from `data_type`.** `Random Value`
  exposes only the active variant in 5.2 (5.1 kept all of them, disabled), so
  **set `data_type` before assigning Min/Max** or the sockets don't exist yet.
- **MENU sockets take display-cased strings**: `'Count'` / `'Length'`, not
  `'COUNT'`. Wrong case raises with the valid list, so this one fails loudly.
- **`nodes.remove()` invalidates Python references to sibling nodes** in the
  same tree. Fetch handles *after* removals, not before.
- **Node group parameters only apply at creation.** `rig.set_parameter` writes
  an interface default, which the evaluator honours the first time and then
  freezes: later changes from Python are stored but ignored. Confirmed for
  vector inputs against `tree.update_tag()`, object `update_tag()` and
  reassigning `node_group` -- none help. Panel edits go through RNA rather than
  plain assignment and behave normally. **Tests must build a fresh strand per
  parameter value**; an in-place loop silently measures the first value over
  and over, which is exactly how the bulb orientation first appeared to pass.
- **Instance ordering is not stable between evaluations.** `depsgraph.object_instances`
  hands back a bulb's child objects in varying order, so "the first instance"
  is a different part each run. Pin the child by name. Centroids are no help
  either -- the meshes are origin-centred, so a centroid can't see rotation.
- **Resample-by-length near zero locks Blender up** trying to make unbounded
  points. The node tree hard-floors the spacing input; a user typing 0 must not
  be able to hang the app.
- `Material.use_nodes` is deprecated in 5.x (removal slated for 6.0) but still
  needed for 5.0/5.1.


## Test notes

- `reset_scene()` in the festoon suite re-enables the addon: `read_factory_settings` resets PREFERENCES too, which disables it, and anything calling `bpy.ops.lightgroup.*` afterwards fails with "operator could not be found".
- **`run_festoon_test.sh`** — builds real strands and inspects the evaluated geometry: the depth-peeling raycast skips hidden objects and festoon's own strands, the curve passes through the sag empty at every flatness, flatness broadens the bottom without moving the low point, bulb spacing responds, a parent move stays rigid, and each strand gets its own node group.
