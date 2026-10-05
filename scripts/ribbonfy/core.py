"""Straightening math. No Maya imports, so it runs and tests outside Maya.

Checks the shell is a quad grid, walks it to give every UV a lattice position,
spaces rows and columns by 3D edge length, keeps the original orientation and
winding, then scales back to the original UV area.
"""
from collections import deque
import math

__all__ = ["SkipShell", "straighten_shell", "open_ring", "is_closed_loop_skip"]

CLOSED_LOOP = "not a clean grid (closed loop or hidden pole)"

EPS = 1e-12


class SkipShell(Exception):
    """Raised when a shell can't be straightened. The message is shown to the artist."""


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _signed_area(loop, coords):
    area = 0.0
    n = len(loop)
    for k in range(n):
        u0, v0 = coords(loop[k])
        u1, v1 = coords(loop[(k + 1) % n])
        area += u0 * v1 - u1 * v0
    return 0.5 * area


def _bbox(coords, uv_ids):
    u0 = v0 = float("inf")
    u1 = v1 = float("-inf")
    for uv in uv_ids:
        u, v = coords(uv)
        if u < u0:
            u0 = u
        if u > u1:
            u1 = u
        if v < v0:
            v0 = v
        if v > v1:
            v1 = v
    return u0, v0, u1, v1


def straighten_shell(face_uvs, face_verts, us, vs, points=None,
                     direction="auto", spacing="edge",
                     keep_position=True, preserve_density=True):
    """Lay one UV shell out as a straight grid.

    face_uvs   -- list of UV-id loops, one per face in the shell
    face_verts -- matching vertex-id loops (only used for 3D edge lengths)
    us, vs     -- indexable U and V for every UV id on the mesh
    points     -- indexable (x, y, z) per vertex id; needed when spacing="edge"
    direction  -- "auto" follows the current layout; "u" / "v" put the long side on that axis
    spacing    -- "edge" uses averaged 3D edge lengths, "uniform" makes every step equal

    Returns {uv_id: (u, v)}. Raises SkipShell with a readable reason otherwise.
    """
    if not face_uvs:
        raise SkipShell("empty shell")

    # ---- 1. topology checks ------------------------------------------------
    n_tri = sum(1 for f in face_uvs if len(f) == 3)
    n_ngon = sum(1 for f in face_uvs if len(f) > 4)
    if n_tri or n_ngon:
        parts = []
        if n_tri:
            parts.append(_plural(n_tri, "triangle"))
        if n_ngon:
            parts.append(_plural(n_ngon, "n-gon"))
        raise SkipShell(" and ".join(parts))

    uv_vert = {}
    edges = {}
    valence = {}
    for fi, loop in enumerate(face_uvs):
        if len(set(loop)) != 4:
            raise SkipShell("degenerate face (repeated UV)")
        vloop = face_verts[fi]
        for k in range(4):
            a = loop[k]
            b = loop[(k + 1) % 4]
            uv_vert[a] = vloop[k]
            valence[a] = valence.get(a, 0) + 1
            key = (a, b) if a < b else (b, a)
            edges.setdefault(key, []).append(fi)

    boundary = set()
    for key, faces in edges.items():
        if len(faces) > 2:
            raise SkipShell("non-manifold UV edge")
        if len(faces) == 1:
            boundary.update(key)
    for uv, val in valence.items():
        if uv in boundary:
            if val > 3:
                raise SkipShell("pole (%d faces) on the border at UV %d" % (val, uv))
        elif val != 4:
            raise SkipShell("pole (%d-valence) at UV %d" % (val, uv))

    # ---- 2. grid walk ------------------------------------------------------
    lattice = {}
    occupied = {}

    def place(uv, ij):
        old = lattice.get(uv)
        if old is not None:
            if old != ij:
                raise SkipShell(CLOSED_LOOP)
            return
        other = occupied.get(ij)
        if other is not None and other != uv:
            raise SkipShell("shell overlaps itself in grid space")
        lattice[uv] = ij
        occupied[ij] = uv

    first = face_uvs[0]
    for uv, ij in zip(first, ((0, 0), (1, 0), (1, 1), (0, 1))):
        place(uv, ij)

    seen = [False] * len(face_uvs)
    seen[0] = True
    visited = 1
    queue = deque([0])
    while queue:
        fi = queue.popleft()
        loop = face_uvs[fi]
        for k in range(4):
            a = loop[k]
            b = loop[(k + 1) % 4]
            key = (a, b) if a < b else (b, a)
            for gi in edges[key]:
                if seen[gi]:
                    continue
                seen[gi] = True
                visited += 1
                pa = lattice[a]
                pb = lattice[b]
                pm = lattice[loop[(k - 1) % 4]]          # corner beside a, inside this face
                nx, ny = pa[0] - pm[0], pa[1] - pm[1]    # step away from this face
                g = face_uvs[gi]
                ia = g.index(a)
                ib = g.index(b)
                c = g[(ib + 1) % 4] if g[(ib + 1) % 4] != a else g[(ib - 1) % 4]
                d = g[(ia + 1) % 4] if g[(ia + 1) % 4] != b else g[(ia - 1) % 4]
                place(c, (pb[0] + nx, pb[1] + ny))
                place(d, (pa[0] + nx, pa[1] + ny))
                queue.append(gi)

    if visited != len(face_uvs):
        raise SkipShell("faces joined only at a corner")

    for loop in face_uvs:                                # every face must be a unit square
        for k in range(4):
            p = lattice[loop[k]]
            q = lattice[loop[(k + 1) % 4]]
            if abs(q[0] - p[0]) + abs(q[1] - p[1]) != 1:
                raise SkipShell(CLOSED_LOOP)

    min_i = min(p[0] for p in lattice.values())
    min_j = min(p[1] for p in lattice.values())
    lattice = dict((uv, (p[0] - min_i, p[1] - min_j)) for uv, p in lattice.items())
    n_cols = max(p[0] for p in lattice.values())
    n_rows = max(p[1] for p in lattice.values())

    # ---- 3. spacing --------------------------------------------------------
    if spacing == "uniform":
        widths = [1.0] * n_cols
        heights = [1.0] * n_rows
    else:
        if points is None:
            raise ValueError("points are required for spacing='edge'")
        w_sum = [0.0] * n_cols
        w_cnt = [0] * n_cols
        h_sum = [0.0] * n_rows
        h_cnt = [0] * n_rows
        for a, b in edges:
            pa = lattice[a]
            pb = lattice[b]
            xa, ya, za = points[uv_vert[a]]
            xb, yb, zb = points[uv_vert[b]]
            length = math.sqrt((xb - xa) ** 2 + (yb - ya) ** 2 + (zb - za) ** 2)
            if pa[1] == pb[1]:
                k = min(pa[0], pb[0])
                w_sum[k] += length
                w_cnt[k] += 1
            else:
                k = min(pa[1], pb[1])
                h_sum[k] += length
                h_cnt[k] += 1
        widths = [w_sum[k] / w_cnt[k] if w_cnt[k] else 0.0 for k in range(n_cols)]
        heights = [h_sum[k] / h_cnt[k] if h_cnt[k] else 0.0 for k in range(n_rows)]
        positive = [x for x in widths + heights if x > EPS]
        if not positive:
            raise SkipShell("shell has zero size in 3D")
        floor = min(positive)                            # never stack UVs on top of each other
        widths = [x if x > EPS else floor for x in widths]
        heights = [x if x > EPS else floor for x in heights]

    xs = [0.0]
    for w in widths:
        xs.append(xs[-1] + w)
    ys = [0.0]
    for h in heights:
        ys.append(ys[-1] + h)

    # ---- 4. orientation ----------------------------------------------------
    ai_u = ai_v = aj_u = aj_v = 0.0                      # how lattice axes run in the current UVs
    for a, b in edges:
        pa = lattice[a]
        pb = lattice[b]
        du = us[b] - us[a]
        dv = vs[b] - vs[a]
        if pa[1] == pb[1]:
            s = 1.0 if pb[0] > pa[0] else -1.0
            ai_u += s * du
            ai_v += s * dv
        else:
            s = 1.0 if pb[1] > pa[1] else -1.0
            aj_u += s * du
            aj_v += s * dv

    if direction == "u":
        i_on_u = xs[-1] >= ys[-1]
    elif direction == "v":
        i_on_u = xs[-1] < ys[-1]
    else:
        i_on_u = abs(ai_u) + abs(aj_v) >= abs(ai_v) + abs(aj_u)

    if i_on_u:
        su = -1.0 if ai_u < 0 else 1.0
        sv = -1.0 if aj_v < 0 else 1.0
    else:
        su = -1.0 if aj_u < 0 else 1.0
        sv = -1.0 if ai_v < 0 else 1.0

    def original(uv):
        return us[uv], vs[uv]

    signs = [su, sv]

    def raw(uv):
        i, j = lattice[uv]
        if i_on_u:
            return signs[0] * xs[i], signs[1] * ys[j]
        return signs[0] * ys[j], signs[1] * xs[i]

    # Match the shell's current winding so the texture is never mirrored.
    orig_signed = sum(_signed_area(loop, original) for loop in face_uvs)
    new_signed = sum(_signed_area(loop, raw) for loop in face_uvs)
    if abs(orig_signed) > EPS and (new_signed > 0) != (orig_signed > 0):
        signs[1] = -signs[1]

    # ---- 5. scale and position --------------------------------------------
    uv_ids = list(lattice)
    ou0, ov0, ou1, ov1 = _bbox(original, uv_ids)
    nu0, nv0, nu1, nv1 = _bbox(raw, uv_ids)
    orig_area = sum(abs(_signed_area(loop, original)) for loop in face_uvs)
    new_area = sum(abs(_signed_area(loop, raw)) for loop in face_uvs)

    # Original UVs with no real area (rows stacked on top of each other, e.g. a
    # planar projection down a tube) give no texel density to preserve. Scaling
    # to that area would collapse the shell to a point, so size it from the
    # original outline instead.
    orig_box = (ou1 - ou0) * (ov1 - ov0)
    degenerate = orig_area <= max(EPS, 1e-3 * orig_box)
    if preserve_density and not degenerate:
        scale = math.sqrt(orig_area / new_area)
    else:
        orig_long = max(ou1 - ou0, ov1 - ov0)
        new_long = max(nu1 - nu0, nv1 - nv0)
        scale = orig_long / new_long if orig_long > EPS else 1.0 / new_long

    if keep_position:
        cu = 0.5 * (ou0 + ou1) - 0.5 * (nu0 + nu1) * scale
        cv = 0.5 * (ov0 + ov1) - 0.5 * (nv0 + nv1) * scale
    else:
        cu = -nu0 * scale
        cv = -nv0 * scale

    result = {}
    for uv in uv_ids:
        u, v = raw(uv)
        result[uv] = (u * scale + cu, v * scale + cv)
    return result


# Closed rings: a quad band that wraps all the way round (open end of a pipe)
# has no start or end, so it gets one seam cut before straightening.

def is_closed_loop_skip(exc):
    """True when a SkipShell came from the grid walk meeting itself."""
    return str(exc) == CLOSED_LOOP


def _edge_faces(face_uvs):
    edges = {}
    for fi, loop in enumerate(face_uvs):
        n = len(loop)
        for k in range(n):
            a = loop[k]
            b = loop[(k + 1) % n]
            key = (a, b) if a < b else (b, a)
            edges.setdefault(key, []).append(fi)
    return edges


def _border_loops(edges):
    """Groups of UV ids, one per separate border of the shell."""
    adj = {}
    for (a, b), faces in edges.items():
        if len(faces) == 1:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    loops = []
    seen = set()
    for start in adj:
        if start in seen:
            continue
        group = set()
        stack = [start]
        while stack:
            x = stack.pop()
            if x in group:
                continue
            group.add(x)
            stack.extend(adj[x])
        seen |= group
        loops.append(group)
    return loops


def _other_neighbour(loop, uv, not_this):
    """In a quad, the corner next to `uv` that isn't `not_this`."""
    i = loop.index(uv)
    after = loop[(i + 1) % 4]
    return after if after != not_this else loop[(i - 1) % 4]


def open_ring(face_uvs, next_id):
    """Cut a closed ring of quads open so straighten_shell() can lay it flat.

    face_uvs -- UV-id loops for the shell (all quads)
    next_id  -- first unused UV id on the mesh; new UVs are numbered from here

    Returns (cut_face_uvs, copies). copies maps each new UV id to the existing
    UV id it duplicates, so the caller can give it the same starting position.
    Raises SkipShell with a readable reason when the shell isn't a simple ring.
    """
    if any(len(loop) != 4 for loop in face_uvs):
        raise SkipShell(CLOSED_LOOP)
    edges = _edge_faces(face_uvs)
    borders = _border_loops(edges)
    if len(borders) != 2:
        raise SkipShell(CLOSED_LOOP)
    rim_a, rim_b = borders

    start = None
    for key in sorted(edges):
        if len(edges[key]) == 1 and key[0] in rim_a and key[1] in rim_a:
            start = key
            break
    if start is None:
        raise SkipShell(CLOSED_LOOP)

    # Walk across the band: from a border corner, step along the edge that leaves
    # the border, then keep going through the face on the far side of each row.
    face = edges[start][0]
    p = start[0]
    q = _other_neighbour(face_uvs[face], p, start[1])
    seam = [p, q]
    walk = [face]
    while q not in rim_b:
        if len(walk) > len(face_uvs):
            raise SkipShell("closed ring: couldn't find a line of edges to cut along")
        c = _other_neighbour(face_uvs[face], q, p)          # edge across the row
        key = (q, c) if q < c else (c, q)
        beyond = [g for g in edges[key] if g != face]
        if not beyond:
            raise SkipShell("closed ring: couldn't find a line of edges to cut along")
        face = beyond[0]
        nxt = _other_neighbour(face_uvs[face], q, c)
        seam.append(nxt)
        walk.append(face)
        p, q = q, nxt

    copies = {}
    renamed = {}
    for offset, uv in enumerate(seam):
        renamed[uv] = next_id + offset
        copies[next_id + offset] = uv
    cut = [list(loop) for loop in face_uvs]
    for fi in walk:
        cut[fi] = [renamed.get(uv, uv) for uv in cut[fi]]
    return cut, copies
