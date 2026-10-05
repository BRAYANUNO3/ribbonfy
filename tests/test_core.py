"""Run with:  python -m unittest discover tests   (no Maya needed)"""
import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ribbonfy.core import SkipShell, is_closed_loop_skip, open_ring, straighten_shell  # noqa: E402


def bent_strip(cols, rows, mirror=False, reverse_some=False):
    """A quad strip bent along an arc in 3D, with messy curved UVs."""
    points, us, vs = [], [], []
    for j in range(rows + 1):
        for i in range(cols + 1):
            t = i / float(cols)
            ang = t * math.pi * 0.8
            r = 5.0 + j * 0.4
            points.append((r * math.cos(ang), j * 0.3, r * math.sin(ang)))
            ur = 0.2 + j * 0.03
            u = 0.5 + ur * math.cos(ang + 0.3) + 0.01 * math.sin(i * 1.7)
            v = 0.4 + ur * math.sin(ang + 0.3)
            us.append(1.0 - u if mirror else u)
            vs.append(v)

    def vid(i, j):
        return j * (cols + 1) + i

    faces = []
    for j in range(rows):
        for i in range(cols):
            loop = [vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)]
            if reverse_some and (i + j) % 3 == 0:
                loop.reverse()
            faces.append(loop)
    return faces, us, vs, points


def signed_area(loop, res):
    a = 0.0
    for k in range(len(loop)):
        u0, v0 = res[loop[k]]
        u1, v1 = res[loop[(k + 1) % len(loop)]]
        a += u0 * v1 - u1 * v0
    return 0.5 * a


class StraightenTests(unittest.TestCase):

    def assertGrid(self, faces, res):
        """Every face edge must be exactly horizontal or vertical."""
        for loop in faces:
            for k in range(4):
                u0, v0 = res[loop[k]]
                u1, v1 = res[loop[(k + 1) % 4]]
                self.assertTrue(abs(u1 - u0) < 1e-9 or abs(v1 - v0) < 1e-9)

    def test_bent_strip_becomes_grid(self):
        faces, us, vs, pts = bent_strip(12, 3)
        res = straighten_shell(faces, faces, us, vs, pts)
        self.assertGrid(faces, res)

    def test_density_and_winding_preserved(self):
        for mirror in (False, True):
            faces, us, vs, pts = bent_strip(10, 2, mirror=mirror)
            res = straighten_shell(faces, faces, us, vs, pts)
            orig = dict((i, (us[i], vs[i])) for i in range(len(us)))
            a0 = sum(signed_area(f, orig) for f in faces)
            a1 = sum(signed_area(f, res) for f in faces)
            self.assertAlmostEqual(abs(a0), abs(a1), places=9)
            self.assertEqual(a0 > 0, a1 > 0, "texture would be mirrored")

    def test_mixed_face_winding(self):
        faces, us, vs, pts = bent_strip(8, 3, reverse_some=True)
        res = straighten_shell(faces, faces, us, vs, pts)
        self.assertGrid(faces, res)

    def test_position_kept(self):
        faces, us, vs, pts = bent_strip(8, 2)
        res = straighten_shell(faces, faces, us, vs, pts)
        cu0 = (min(us) + max(us)) / 2
        cu1 = (min(u for u, v in res.values()) + max(u for u, v in res.values())) / 2
        self.assertAlmostEqual(cu0, cu1, places=9)

    def test_forced_directions(self):
        faces, us, vs, pts = bent_strip(12, 2)
        for d, long_axis in (("u", 0), ("v", 1)):
            res = straighten_shell(faces, faces, us, vs, pts, direction=d)
            spans = [max(p[a] for p in res.values()) - min(p[a] for p in res.values()) for a in (0, 1)]
            self.assertGreater(spans[long_axis], spans[1 - long_axis])

    def test_uniform_spacing(self):
        faces, us, vs, pts = bent_strip(6, 2)
        res = straighten_shell(faces, faces, us, vs, None, spacing="uniform")
        steps = set()
        for loop in faces:
            u0, v0 = res[loop[0]]
            u1, v1 = res[loop[1]]
            steps.add(round(abs(u1 - u0) + abs(v1 - v0), 9))
        self.assertEqual(len(steps), 1)

    def test_l_shape(self):
        # 2x2 block with the top-right face removed
        def vid(i, j):
            return j * 3 + i
        faces = [[vid(0, 0), vid(1, 0), vid(1, 1), vid(0, 1)],
                 [vid(1, 0), vid(2, 0), vid(2, 1), vid(1, 1)],
                 [vid(0, 1), vid(1, 1), vid(1, 2), vid(0, 2)]]
        us = [0.1 * (k % 3) + 0.02 * (k // 3) for k in range(9)]
        vs = [0.1 * (k // 3) for k in range(9)]
        pts = [(k % 3, k // 3, 0.0) for k in range(9)]
        res = straighten_shell(faces, faces, us, vs, pts)
        self.assertGrid(faces, res)

    def test_skips(self):
        faces, us, vs, pts = bent_strip(4, 2)
        tri = faces[:-1] + [faces[-1][:3]]
        with self.assertRaisesRegex(SkipShell, "triangle"):
            straighten_shell(tri, tri, us, vs, pts)

        # closed ring: last column welded back to the first, no UV seam
        cols = 6
        ring = [[i, (i + 1) % cols, cols + (i + 1) % cols, cols + i] for i in range(cols)]
        rus = [math.cos(k) for k in range(2 * cols)]
        rvs = [math.sin(k) for k in range(2 * cols)]
        rpts = [(math.cos(k), math.sin(k), k // cols) for k in range(2 * cols)]
        with self.assertRaisesRegex(SkipShell, "clean grid"):
            straighten_shell(ring, ring, rus, rvs, rpts)

        # three quads around one UV: an interior pole
        pole = [[0, 1, 2, 3], [0, 3, 4, 5], [0, 5, 6, 1]]
        pus = [0.5, 1, 1, 0.5, 0, 0, 0.5]
        pvs = [0.5, 0.5, 1, 1, 1, 0.5, 0]
        ppts = [(u, v, 0.0) for u, v in zip(pus, pvs)]
        with self.assertRaisesRegex(SkipShell, "pole"):
            straighten_shell(pole, pole, pus, pvs, ppts)

    def test_speed(self):
        faces, us, vs, pts = bent_strip(400, 250)   # 100k quads
        t0 = time.perf_counter()
        straighten_shell(faces, faces, us, vs, pts)
        dt = time.perf_counter() - t0
        print("\n100k-quad shell straightened in %.2fs" % dt)
        self.assertLess(dt, 5.0)


if __name__ == "__main__":
    unittest.main()


def closed_ring(cols, rows):
    """A tube band with no UV seam: column `cols` wraps back onto column 0,
    laid out in UV as a donut, like the open end of a cylinder."""
    points, us, vs = [], [], []
    for j in range(rows + 1):
        for i in range(cols):
            ang = 2.0 * math.pi * i / cols
            points.append((math.cos(ang), j * 0.25, math.sin(ang)))
            r = 0.2 + j * 0.05
            us.append(0.5 + r * math.cos(ang))
            vs.append(0.5 + r * math.sin(ang))

    def vid(i, j):
        return j * cols + (i % cols)

    faces = [[vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)]
             for j in range(rows) for i in range(cols)]
    return faces, us, vs, points


class RingTests(unittest.TestCase):

    def _straighten_ring(self, cols, rows):
        faces, us, vs, points = closed_ring(cols, rows)
        with self.assertRaises(SkipShell) as ctx:
            straighten_shell(faces, faces, us, vs, points)
        self.assertTrue(is_closed_loop_skip(ctx.exception))
        cut, copies = open_ring(faces, len(us))
        self.assertEqual(len(copies), rows + 1)          # one seam UV per border-to-border vertex
        us2, vs2 = list(us), list(vs)
        pts = list(points)
        for new, old in sorted(copies.items()):
            us2.append(us[old])
            vs2.append(vs[old])
        vert_of = {}
        for fl, vl in zip(cut, faces):
            for uv, v in zip(fl, vl):
                vert_of[uv] = v
        res = straighten_shell(cut, faces, us2, vs2, pts)
        return res, cut, copies

    def test_single_row_ring_opens(self):
        res, cut, copies = self._straighten_ring(20, 1)
        self.assertEqual(len(res), 2 * 21)                # 21 columns x 2 rows of UVs after the cut
        rows = sorted(set(round(v, 6) for u, v in res.values()))
        cols = sorted(set(round(u, 6) for u, v in res.values()))
        self.assertEqual(sorted([len(rows), len(cols)]), [2, 21])

    def test_multi_row_ring_opens(self):
        res, cut, copies = self._straighten_ring(16, 4)
        rows = sorted(set(round(v, 6) for u, v in res.values()))
        cols = sorted(set(round(u, 6) for u, v in res.values()))
        self.assertEqual(sorted([len(rows), len(cols)]), [5, 17])

    def test_cut_only_touches_one_side(self):
        faces, us, vs, points = closed_ring(12, 3)
        cut, copies = open_ring(faces, len(us))
        changed = [i for i, (a, b) in enumerate(zip(faces, cut)) if a != b]
        self.assertEqual(len(changed), 3)                 # one face per row
        for i in changed:
            self.assertTrue(set(cut[i]) & set(copies))

    def test_disc_is_not_a_ring(self):
        faces, us, vs, points = bent_strip(6, 2)
        with self.assertRaises(SkipShell):
            open_ring(faces, len(us))                      # one border, nothing to cut


class DegenerateTests(unittest.TestCase):

    def test_stacked_rows_never_collapse(self):
        """Rows sitting on top of each other in UV (zero area) must not shrink to a point."""
        faces, us, vs, points = closed_ring(20, 4)
        for i in range(len(us)):                       # stack every row onto the first ring
            ang = 2.0 * math.pi * (i % 20) / 20
            us[i] = 0.5 + 0.3 * math.cos(ang)
            vs[i] = 0.5 + 0.3 * math.sin(ang)
        cut, copies = open_ring(faces, len(us))
        for new, old in sorted(copies.items()):
            us.append(us[old])
            vs.append(vs[old])
        res = straighten_shell(cut, faces, us, vs, points)
        width = max(u for u, v in res.values()) - min(u for u, v in res.values())
        height = max(v for u, v in res.values()) - min(v for u, v in res.values())
        self.assertGreater(max(width, height), 0.1)
        self.assertGreater(min(width, height), 0.01)
