import unittest
from visual_fidelity.motion_kit import VERSION,CAPABILITIES,validate_manifest

class MotionKitContractTests(unittest.TestCase):
    def manifest(self):
        return {'engine_version':VERSION,'required_features':list(CAPABILITIES),'features':{
            key:{'module':value['module'],'controls':dict.fromkeys(value['requires'],True),'status':'implemented'}
            for key,value in CAPABILITIES.items()}}
    def test_contract_does_not_claim_visual_approval(self):
        result=validate_manifest(self.manifest());self.assertTrue(result['contract_valid'])
        self.assertFalse(result['visual_similarity_certified']);self.assertFalse(result['user_approved'])
    def test_missing_engine_route_and_occluder_rejected(self):
        for key in ['module','controls']:
            m=self.manifest();del m['features']['orbit-occlusion'][key]
            with self.assertRaises(ValueError):validate_manifest(m)
    def test_fragment_cannot_masquerade_as_complete(self):
        m=self.manifest();m['lettering_assets']=[{'id':'word','used_as_complete':True,'coverage':'visible-fragment'}]
        with self.assertRaisesRegex(ValueError,'fragments'):validate_manifest(m)
    def test_review_requires_evidence(self):
        m=self.manifest();m['features']['light-sweep']['status']='reviewed'
        with self.assertRaisesRegex(ValueError,'evidence'):validate_manifest(m)
    def test_legacy_manifest_keeps_original_capability_contract(self):
        m=self.manifest();m['engine_version']='0.7.0';m['required_features']=['orbit-occlusion']
        result=validate_manifest(m)
        self.assertEqual(result['engine_version'],'0.7.0')
        self.assertEqual(result['validator_version'],VERSION)
    def test_new_geometry_cannot_claim_legacy_implementation(self):
        m=self.manifest();m['engine_version']='0.7.0';m['required_features']=['device-screen-stage']
        with self.assertRaisesRegex(ValueError,'requires motion-kit'):validate_manifest(m)

if __name__=='__main__':unittest.main()
