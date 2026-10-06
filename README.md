# Ribbonfy

One-click UV straightening for Maya. Select curved quad strips (pipes, cables, trims, belts) and turn them into straight, grid-aligned UV shells in one click.

<p>
  <img src="docs/hero.gif" width="49%" alt="Ribbonfy straightening 150 UV shells in one click, then laying them out">
  <img src="docs/organic_head.gif" width="49%" alt="Ribbonfy straightening the strip shells of an organic head">
</p>

Left: 150 curved strips straightened and laid out in one click. Right: an organic head split into strip shells.

## Features (v0.1)

- **One click, many shells.** Works on whole meshes, groups, or selected faces, UVs, edges or vertices, across several meshes at once.
- **Real proportions.** Rows and columns are spaced by averaged 3D edge lengths, so textures don't stretch. Uniform spacing is one toggle away.
- **Direction control.** Auto follows each shell's current layout; U or V forces the long side onto that axis.
- **Keeps your layout.** Texel density and shell position are preserved, and shells are never mirrored.
- **Optional layout.** Turn on *Lay out shells* to pack the straightened shells into 0-1 with Maya's Layout right after, so they don't overlap. Off by default, so shells you've already arranged stay put.
- **Closed rings.** Bands that wrap all the way around, like the open end of a pipe, are cut open along one line of edges and straightened in the same click. No history is added, and Ctrl+Z puts the seam back.
- **Safe.** Shells that aren't clean quad grids are skipped and left unchanged. After a run they're selected so you can see them, and the reasons are printed in the Script Editor. One Ctrl+Z undoes the whole run.
- **Fast.** Bulk API reads and writes, one linear pass per shell. A 100,000-quad shell takes about 1.5 s, and a 324,000-face asset with 380 shells about 10 s; typical game strips take milliseconds.

## Install

1. Unzip `ribbonfy-v0.1.0.zip` anywhere.
2. Drag `drag_to_install.mel` into the Maya viewport.

That's it. Ribbonfy copies itself into your Maya modules folder (`Documents/maya/modules/ribbonfy`), loads, and creates a **Ribbonfy** shelf with its button. Click the button to open the panel. It loads automatically every time Maya starts, and you can delete the unzipped folder afterwards.

To update, drag the new version's `drag_to_install.mel` in the same way; it replaces the old copy.

To uninstall, delete `Documents/maya/modules/ribbonfy` and `Documents/maya/modules/ribbonfy.mod`, then remove the Ribbonfy shelf (right-click the shelf tab > Delete Shelf).

Open the panel any time from the shelf, or with:

```python
import ribbonfy.ui; ribbonfy.ui.show()
```

Scripting:

```python
cmds.ribbonfy(direction="auto", spacing="edge", keepPosition=True, preserveDensity=True)
```

*Lay out shells* is a panel option; from a script, run Maya's Layout after the command.

Tested on Maya 2026. Written for PySide6 (Maya 2025 and later) and PySide2 (Maya 2022 to 2024); the older versions haven't been tested yet. No extra packages needed.

## How it works

1. **Validate.** The shell must be all quads with no interior poles. Anything else is skipped and left as it is.
2. **Grid walk.** The first face gets lattice corners (0,0), (1,0), (1,1), (0,1). A breadth-first walk crosses shared UV edges; each neighbour's two free corners land one lattice step beyond the shared edge, away from the face it came from. This works regardless of face winding. If a UV would land on two different lattice points, the shell is a closed loop or hides a pole, so it's skipped.
3. **Space.** Each lattice column gets the mean 3D length of the edges that span it (each row likewise). A running sum turns that into U and V.
4. **Orient.** The lattice axes are matched to how the shell currently runs in UV space, and the total signed area is checked so the result is never mirrored.
5. **Fit.** Scale to the original UV area (same texel density) and re-centre on the original bounds.

Closed rings get one extra step first: Ribbonfy walks a line of edges from one border of the band to the other and splits the UVs there, which turns the ring into an ordinary strip.

The math lives in `scripts/ribbonfy/core.py` with no Maya imports.

## Limitations

- Quad-grid shells only. Shells with triangles, n-gons or poles are skipped. On hard-surface models, bevel corners often leave an n-gon attached to a strip; cut the corner into its own shell and the strip straightens.
- When Ribbonfy opens a ring it picks the seam itself. If the seam's position matters, cut it yourself first and Ribbonfy keeps it.
- With *Keep shell position* on, shells go back where their curved versions were, so shells that overlapped before still overlap. Turn on *Lay out shells*, or run Maya's Layout afterwards.
- Meshes with construction history: the panel asks whether to delete non-deformer history first (the `ribbonfy` command on its own skips them).
- Skinned or blend-shaped meshes are skipped; straighten their UVs before binding.
- Works on the current UV set.

## License

MIT. Made by Brayan Fernandez, [brayanuno.com](https://brayanuno.com).
