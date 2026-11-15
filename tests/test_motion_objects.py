import unittest
from visual_fidelity.blender_motion_objects import keyhole_outline, ring_mesh, validate_config

class MotionObjectGeometryTests(unittest.TestCase):
    def test_ring_is_closed_manifold_with_open_center(self):
        points=keyhole_outline();vertices,faces=ring_mesh(points)
        edges={}
        for face in faces:
            for a,b in zip(face,face[1:]+face[:1]):
                edge=tuple(sorted((a,b)));edges[edge]=edges.get(edge,0)+1
        self.assertTrue(all(count==2 for count in edges.values()))
        # No face spans the aperture; all polygons are shell quads.
        self.assertTrue(all(len(face)==4 for face in faces))
        self.assertEqual(len(vertices),len(points)*4)
    def test_keyhole_has_round_head_and_flared_base(self):
        p=keyhole_outline()
        self.assertGreater(max(y for x,y in p),1.4)
        self.assertEqual(p[-2:], [(-.9,-1.5),(.9,-1.5)])
        self.assertGreater(abs(p[-2][0]),abs(p[-3][0]))
    def test_invalid_configs_rejected(self):
        for c in [{'kind':'fake'},{'kind':'target','frames':0},{'kind':'keyhole','resolution':[1,2]}]:
            with self.assertRaises(ValueError):validate_config(c)
        for inset in [0,1,2]:
            with self.assertRaises(ValueError):ring_mesh(keyhole_outline(),inset=inset)

if __name__=='__main__':unittest.main()
