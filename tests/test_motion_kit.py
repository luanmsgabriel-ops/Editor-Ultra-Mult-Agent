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

if __name__=='__main__':unittest.main()
