"""Build a test scene for ribbonfy inside Maya: one mesh per case, laid out in two rows.

Run in Maya's Script Editor (Python):

    exec(open(r"C:/Depot/P4/3DAI/tools/ribbonfy/tests/maya_test_scene.py").read())

Then select the group (or any of its meshes) and click Straighten UVs.
Each mesh is named after what it tests. Expected results:

Front row: should straighten
  curved_strip      flat strip, UVs bent into an arc          -> straight strip
  open_ring         open-ended band, 1 row, donut UVs         -> ring cut open, straight strip
  open_ring_tall    same band, 4 rows                         -> ring cut open, straight strip
  bent_pipe         pipe bent 90 degrees, curved UVs          -> straight strip, real proportions
  cable             long thin S-curve cable, curved UVs       -> long straight strip
  mirrored_strip    strip whose UVs are flipped               -> straight, still flipped (never mirrored)
  three_strips      one mesh holding three separate shells    -> all three straightened in one click
  dense_strip       400 x 10 quads                            -> straightens in well under a second

Back row: should be skipped or asked about
  capped_cylinder   side straightens, n-gon caps skipped
  strip_with_tri    one face split into triangles             -> skipped: "2 triangles"
  torus             UVs already a rectangle                   -> straightens (seams already there)
  with_history      keeps construction history                -> the panel asks before deleting it
"""
import math

import maya.api.OpenMaya as om
import maya.cmds as cmds

GROUP = "ribbonfy_test_geo"


def _fn(mesh):
    sel = om.MSelectionList()
    sel.add(mesh)
    return om.MFnMesh(sel.getDagPath(0))


def _bend_uvs(mesh, sweep=math.pi / 2):
    """Bend the mesh's UVs into an arc (fast: one getUVs, one setUVs)."""
    fn = _fn(mesh)
    us, vs = fn.getUVs()
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    du = (u1 - u0) or 1.0
    dv = (v1 - v0) or 1.0
    long_u = du >= dv
    for i in range(len(us)):
        t = (us[i] - u0) / du if long_u else (vs[i] - v0) / dv
        s = (vs[i] - v0) / dv if long_u else (us[i] - u0) / du
        ang = t * sweep
        r = 0.45 + s * 0.12
        us[i] = 0.1 + r * math.cos(ang)
        vs[i] = 0.1 + r * math.sin(ang)
    fn.setUVs(us, vs)
    fn.updateSurface()


def _open_band(name, rows):
    """An open-ended tube band whose UVs are a donut with no seam.

    One UV per vertex, so the band wraps all the way round in UV space. Each
    height step sits on a wider circle, so the shell has real UV area.
    """
    mesh = cmds.polyCylinder(name=name, radius=1, height=0.4 * rows, subdivisionsAxis=20,
                             subdivisionsHeight=rows, subdivisionsCaps=0)[0]
    faces = cmds.polyEvaluate(mesh, face=True)
    side = 20 * rows
    if faces > side:
        cmds.delete("%s.f[%d:%d]" % (mesh, side, faces - 1))   # remove the caps
    cmds.delete(mesh, constructionHistory=True)
    fn = _fn(mesh)
    pts = fn.getPoints()
    ys = sorted(set(round(p.y, 4) for p in pts))
    us = om.MFloatArray()
    vs = om.MFloatArray()
    for p in pts:
        ang = math.atan2(p.z, p.x)
        r = 0.18 + 0.07 * ys.index(round(p.y, 4))
        us.append(0.5 + r * math.cos(ang))
        vs.append(0.5 + r * math.sin(ang))
    counts, verts = fn.getVertices()
    fn.clearUVs()
    fn.setUVs(us, vs)
    fn.assignUVs(counts, verts)
    return mesh


def _side_only_cylinder(name, radius, height, axis_divs, height_divs):
    """A cylinder with its caps removed, keeping the default side UVs (one seam)."""
    mesh = cmds.polyCylinder(name=name, radius=radius, height=height, subdivisionsAxis=axis_divs,
                             subdivisionsHeight=height_divs, subdivisionsCaps=0)[0]
    side = axis_divs * height_divs
    faces = cmds.polyEvaluate(mesh, face=True)
    if faces > side:
        cmds.delete("%s.f[%d:%d]" % (mesh, side, faces - 1))
    return mesh


def _bend(mesh, curvature, lo=-1.0, hi=1.0):
    deformer, handle = cmds.nonLinear(mesh, type="bend", curvature=curvature,
                                      lowBound=lo, highBound=hi)
    cmds.delete(mesh, constructionHistory=True)
    if cmds.objExists(handle):
        cmds.delete(handle)


def build():
    if cmds.objExists(GROUP):
        cmds.delete(GROUP)
    front, back = [], []

    # ---- should straighten ------------------------------------------------
    strip = cmds.polyPlane(name="curved_strip", width=6, height=1, subdivisionsX=16, subdivisionsY=2)[0]
    front.append(strip)

    front.append(_open_band("open_ring", 1))
    front.append(_open_band("open_ring_tall", 4))

    pipe = _side_only_cylinder("bent_pipe", 0.4, 6, 12, 24)
    _bend(pipe, 90)
    front.append(pipe)

    cable = _side_only_cylinder("cable", 0.08, 10, 8, 60)
    cmds.setAttr(cable + ".rotateZ", 90)                 # lie it along X so the wave bends it sideways
    cmds.makeIdentity(cable, apply=True, rotate=True)
    _, sine_handle = cmds.nonLinear(cable, type="sine", amplitude=0.25, wavelength=1.2)
    cmds.delete(cable, constructionHistory=True)         # bake the wave into the mesh
    if cmds.objExists(sine_handle):
        cmds.delete(sine_handle)
    front.append(cable)

    mirrored = cmds.polyPlane(name="mirrored_strip", width=6, height=1, subdivisionsX=16, subdivisionsY=2)[0]
    front.append(mirrored)

    parts = [cmds.polyPlane(width=4, height=0.6, subdivisionsX=10, subdivisionsY=2)[0] for _ in range(3)]
    for i, p in enumerate(parts):
        cmds.xform(p, translation=(0, 0, i * 0.9), worldSpace=True)
    three = cmds.polyUnite(parts, name="three_strips")[0]
    front.append(three)

    front.append(cmds.polyPlane(name="dense_strip", width=12, height=0.3, subdivisionsX=400, subdivisionsY=10)[0])

    # ---- should skip or ask -------------------------------------------------
    back.append(cmds.polyCylinder(name="capped_cylinder", radius=1, height=2,
                                  subdivisionsAxis=20, subdivisionsHeight=4)[0])
    tri = cmds.polyPlane(name="strip_with_tri", width=6, height=1, subdivisionsX=16, subdivisionsY=2)[0]
    cmds.polyTriangulate("%s.f[5]" % tri)
    back.append(tri)
    back.append(cmds.polyTorus(name="torus", radius=1.2, sectionRadius=0.35,
                               subdivisionsAxis=20, subdivisionsHeight=10)[0])

    # Clean every mesh so far, then bend the UVs that should start curved.
    # Use the names Maya actually gave the meshes: if the scene already has a
    # "curved_strip", the new one becomes "curved_strip1".
    cmds.delete(front + back, constructionHistory=True)
    for mesh in (strip, pipe, cable, mirrored, three, front[-1], tri):
        _bend_uvs(mesh)
    fn = _fn(mirrored)                                  # flip it: the result must stay flipped
    us, vs = fn.getUVs()
    for i in range(len(us)):
        us[i] = 1.0 - us[i]
    fn.setUVs(us, vs)
    fn.updateSurface()

    hist = cmds.polyPlane(name="with_history", width=6, height=1, subdivisionsX=16, subdivisionsY=2)[0]
    cmds.polyEditUV("%s.map[*]" % hist, angle=35)        # leaves a polyTweakUV node: real history
    back.append(hist)

    for i, mesh in enumerate(front):
        cmds.xform(mesh, translation=(i * 4.5 - 16.0, 0, 0), worldSpace=True)
    for i, mesh in enumerate(back):
        cmds.xform(mesh, translation=(i * 4.5 - 7.0, 0, -6), worldSpace=True)
    cmds.group(front + back, name=GROUP)
    cmds.select(GROUP)
    print("ribbonfy test scene: %d meshes in %s" % (len(front) + len(back), GROUP))
    return front + back


if globals().get("__name__") != "maya_test_scene":
    build()
