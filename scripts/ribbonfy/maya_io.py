"""Maya side: read the selection and meshes, write UVs back.

One bulk read and one setUVs per mesh. Undo swaps cached arrays. Rings are cut
with new UV ids and assignUVs (not polyMapCut) so no history is added.
"""
from collections import OrderedDict, defaultdict

import maya.api.OpenMaya as om
import maya.cmds as cmds

from ribbonfy import core

LAST_REPORT = None   # read by the UI after each run


class Report(object):
    def __init__(self):
        self.meshes = 0
        self.straightened = 0
        self.rings_opened = 0
        self.skipped = []   # dicts: mesh, shell, reason, faces
        self.done = {}      # mesh path -> faces of the shells that were straightened
        self.whole = set()  # meshes selected whole: lay out every shell, not just the straightened ones

    def skip(self, mesh, shell, reason, faces):
        self.skipped.append({"mesh": mesh, "shell": shell, "reason": reason, "faces": faces})

    def summary(self):
        text = "%d shell%s straightened" % (self.straightened, "" if self.straightened == 1 else "s")
        if self.rings_opened:
            text += " (%d ring%s cut open)" % (self.rings_opened, "" if self.rings_opened == 1 else "s")
        if self.skipped:
            text += " / %d skipped" % len(self.skipped)
        return text


class UVEdit(object):
    """Old and new UV arrays for one mesh, so undo/redo are a single setUVs each.

    When a closed ring was cut open, the face-to-UV assignment changes too, so
    the old and new assignments are cached as well.
    """

    def __init__(self, dag, uv_set, old_u, old_v, new_u, new_v, old_assign=None, new_assign=None):
        self.dag = dag
        self.uv_set = uv_set
        self.old = (old_u, old_v)
        self.new = (new_u, new_v)
        self.old_assign = old_assign
        self.new_assign = new_assign

    def redo(self):
        fn = om.MFnMesh(self.dag)
        fn.setUVs(self.new[0], self.new[1], self.uv_set)      # grows the array first
        if self.new_assign:
            fn.assignUVs(self.new_assign[0], self.new_assign[1], self.uv_set)
        fn.updateSurface()

    def undo(self):
        fn = om.MFnMesh(self.dag)
        if self.old_assign:
            # setUVs can't shrink the UV array back after a ring cut added UVs,
            # so clear it and rebuild the original UVs and assignment exactly.
            fn.clearUVs(self.uv_set)
            fn.setUVs(self.old[0], self.old[1], self.uv_set)
            fn.assignUVs(self.old_assign[0], self.old_assign[1], self.uv_set)
        else:
            fn.setUVs(self.old[0], self.old[1], self.uv_set)
        fn.updateSurface()


class _Target(object):
    def __init__(self, dag):
        self.dag = dag
        self.whole = False
        self.faces = set()
        self.uvs = set()


def _dag_from_path(path):
    sel = om.MSelectionList()
    sel.add(path)
    return sel.getDagPath(0)


def _mesh_dags(dag):
    """The mesh shape(s) under a selected DAG path (handles groups and transforms)."""
    if dag.hasFn(om.MFn.kMesh) and dag.apiType() == om.MFn.kMesh:
        return [dag]
    shapes = cmds.listRelatives(dag.fullPathName(), allDescendents=True, type="mesh",
                                fullPath=True, noIntermediate=True) or []
    return [_dag_from_path(p) for p in shapes]


def _gather_targets():
    sel = om.MGlobal.getActiveSelectionList()
    targets = OrderedDict()
    for idx in range(sel.length()):
        try:
            dag, comp = sel.getComponent(idx)
        except (RuntimeError, TypeError):
            continue                                    # not a DAG item
        if comp.isNull():
            for mesh in _mesh_dags(dag):
                key = mesh.fullPathName()
                targets.setdefault(key, _Target(mesh)).whole = True
            continue
        if dag.apiType() != om.MFn.kMesh:
            try:
                dag.extendToShape()
            except RuntimeError:
                continue
        if dag.apiType() != om.MFn.kMesh:
            continue
        key = dag.fullPathName()
        target = targets.setdefault(key, _Target(om.MDagPath(dag)))
        ids = om.MFnSingleIndexedComponent(comp).getElements()
        if comp.hasFn(om.MFn.kMeshPolygonComponent):
            target.faces.update(ids)
        elif comp.hasFn(om.MFn.kMeshMapComponent):
            target.uvs.update(ids)
        elif comp.hasFn(om.MFn.kMeshVertComponent):
            it = om.MItMeshVertex(dag)
            for i in ids:
                it.setIndex(i)
                target.faces.update(it.getConnectedFaces())
        elif comp.hasFn(om.MFn.kMeshEdgeComponent):
            it = om.MItMeshEdge(dag)
            for i in ids:
                it.setIndex(i)
                target.faces.update(it.getConnectedFaces())
    return targets


def _has_history(shape_path):
    return bool(cmds.listConnections(shape_path + ".inMesh", source=True, destination=False))


def _is_deformed(shape_path):
    """True when skin, blend shapes or other deformers feed the mesh. Deleting
    non-deformer history leaves those in place, so the mesh still can't be edited."""
    history = cmds.listHistory(shape_path, pruneDagObjects=True) or []
    return bool(cmds.ls(history, type="geometryFilter"))


def meshes_with_history():
    """Shape paths in the selection whose history can be deleted (deformed meshes excluded)."""
    return [path for path in _gather_targets() if _has_history(path) and not _is_deformed(path)]


def delete_history(shape_paths):
    """Delete non-deformer history (same as Edit > Delete by Type > Non-Deformer History)."""
    for path in shape_paths:
        parent = cmds.listRelatives(path, parent=True, fullPath=True)
        cmds.bakePartialHistory(parent[0] if parent else path, prePostDeformers=True)


def _assignment(face_uvs):
    counts = om.MIntArray()
    ids = om.MIntArray()
    for loop in face_uvs:
        if loop is None:
            counts.append(0)
            continue
        counts.append(len(loop))
        for uv in loop:
            ids.append(uv)
    return counts, ids


def _shells_wanted(target, face_uvs, shell_ids):
    if target.whole:
        return None
    wanted = set(shell_ids[uv] for uv in target.uvs)
    for f in target.faces:
        loop = face_uvs[f]
        if loop:
            wanted.add(shell_ids[loop[0]])
    return wanted


def _face_loops(fn, uv_set):
    uv_counts, uv_ids = fn.getAssignedUVs(uv_set)
    v_counts, v_ids = fn.getVertices()
    uv_ids = list(uv_ids)
    v_ids = list(v_ids)
    face_uvs, face_verts = [], []
    uo = vo = 0
    for f in range(len(v_counts)):
        nv = v_counts[f]
        nu = uv_counts[f]
        face_verts.append(v_ids[vo:vo + nv])
        vo += nv
        if nu:
            face_uvs.append(uv_ids[uo:uo + nu])
            uo += nu
        else:
            face_uvs.append(None)                       # unmapped face
    return face_uvs, face_verts


def selection_summary():
    """(meshes, shells) touched by the current selection, for the UI header."""
    meshes = shells = 0
    for path, target in _gather_targets().items():
        fn = om.MFnMesh(target.dag)
        uv_set = fn.currentUVSetName()
        n, shell_ids = fn.getUvShellsIds(uv_set)
        meshes += 1
        if target.whole:
            shells += n
            continue
        wanted = set(shell_ids[uv] for uv in target.uvs)
        for f in target.faces:
            try:
                wanted.add(shell_ids[fn.getPolygonUVid(f, 0, uv_set)])
            except RuntimeError:
                pass                                    # unmapped face
        shells += len(wanted)
    return meshes, shells


def compute(direction="auto", spacing="edge", keep_position=True, preserve_density=True):
    """Straighten every shell in the selection. Returns (edits, report); nothing is written yet."""
    report = Report()
    edits = []
    for path, target in _gather_targets().items():
        dag = target.dag
        name = dag.partialPathName()
        report.meshes += 1
        if target.whole:
            report.whole.add(dag.fullPathName())
        if _has_history(path):
            if _is_deformed(path):
                report.skip(name, None, "is deformed (skin or blend shape); straighten its UVs before binding", [])
            else:
                report.skip(name, None, "has construction history (run again and choose Delete history)", [])
            continue

        fn = om.MFnMesh(dag)
        uv_set = fn.currentUVSetName()
        old_u, old_v = fn.getUVs(uv_set)
        if not len(old_u):
            report.skip(name, None, "no UVs in the current UV set", [])
            continue
        us = list(old_u)
        vs = list(old_v)
        face_uvs, face_verts = _face_loops(fn, uv_set)
        _, shell_ids = fn.getUvShellsIds(uv_set)
        points = None
        if spacing == "edge":
            points = [(p.x, p.y, p.z) for p in fn.getPoints(om.MSpace.kWorld)]

        wanted = _shells_wanted(target, face_uvs, shell_ids)
        shells = defaultdict(list)
        for f, loop in enumerate(face_uvs):
            if loop is None:
                continue
            s = shell_ids[loop[0]]
            if wanted is None or s in wanted:
                shells[s].append(f)

        old_assign = _assignment(face_uvs)
        new_u = list(us)
        new_v = list(vs)
        changed = False
        rings_cut = False
        kwargs = dict(direction=direction, spacing=spacing,
                      keep_position=keep_position, preserve_density=preserve_density)
        for s in sorted(shells):
            faces = shells[s]
            loops = [face_uvs[f] for f in faces]
            verts = [face_verts[f] for f in faces]
            try:
                result = core.straighten_shell(loops, verts, us, vs, points, **kwargs)
            except core.SkipShell as exc:
                if not core.is_closed_loop_skip(exc):
                    report.skip(name, s, str(exc), faces)
                    continue
                # A closed ring: cut it open along one line of edges, then retry.
                base = len(us)
                try:
                    cut, copies = core.open_ring(loops, len(us))
                    for new_id in sorted(copies):
                        src = copies[new_id]
                        us.append(us[src])
                        vs.append(vs[src])
                        new_u.append(us[src])
                        new_v.append(vs[src])
                    result = core.straighten_shell(cut, verts, us, vs, points, **kwargs)
                except core.SkipShell as ring_exc:
                    del us[base:], vs[base:], new_u[base:], new_v[base:]   # drop the unused copies
                    reason = str(ring_exc)
                    if core.is_closed_loop_skip(ring_exc):
                        reason = "closed loop that isn't a simple ring; cut one edge across it"
                    report.skip(name, s, reason, faces)
                    continue
                for f, loop in zip(faces, cut):
                    face_uvs[f] = loop
                rings_cut = True
                report.rings_opened += 1
            for uv, (u, v) in result.items():
                new_u[uv] = u
                new_v[uv] = v
            report.straightened += 1
            report.done.setdefault(dag.fullPathName(), []).extend(faces)
            changed = True

        if changed:
            edits.append(UVEdit(om.MDagPath(dag), uv_set, old_u, old_v,
                                om.MFloatArray(new_u), om.MFloatArray(new_v),
                                old_assign if rings_cut else None,
                                _assignment(face_uvs) if rings_cut else None))
    return edits, report


def layout(report, spacing=0.004):
    """Pack the straightened shells into 0-1 with Maya's Layout (Unfold3D).

    Texel density is kept relative between shells and only 90-degree turns are
    allowed, so the strips stay straight and axis-aligned.
    """
    if not report or not report.done:
        return 0
    if not cmds.pluginInfo("Unfold3D", query=True, loaded=True):
        cmds.loadPlugin("Unfold3D", quiet=True)
    faces = []
    for mesh, ids in report.done.items():
        if mesh in report.whole:
            faces.append(mesh + ".f[*]")       # pack skipped shells too, so nothing lands on top of them
        else:
            faces.extend(face_ranges(mesh, sorted(set(ids))))
    # preScaleMode 1 keeps relative 3D density; layoutScaleMode 2 scales the result to fit 0-1.
    cmds.u3dLayout(faces, resolution=1024, preScaleMode=1, layoutScaleMode=2,
                   shellSpacing=spacing, tileMargin=spacing, packBox=[0, 1, 0, 1],
                   preRotateMode=0, rotateStep=90, rotateMin=0, rotateMax=360)
    return len(faces)


def face_ranges(mesh, faces):
    """['pCube1.f[0:4]', 'pCube1.f[9]'] - compact component strings for cmds.select."""
    out = []
    faces = sorted(faces)
    start = prev = None
    for f in faces:
        if start is None:
            start = prev = f
        elif f == prev + 1:
            prev = f
        else:
            out.append("%s.f[%d:%d]" % (mesh, start, prev) if prev != start else "%s.f[%d]" % (mesh, start))
            start = prev = f
    if start is not None:
        out.append("%s.f[%d:%d]" % (mesh, start, prev) if prev != start else "%s.f[%d]" % (mesh, start))
    return out
