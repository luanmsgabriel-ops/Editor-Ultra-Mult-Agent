import copy,json,shutil,tempfile,unittest
from pathlib import Path
from visual_fidelity.reference_bundle import BundleError,freeze,verify

class ReferenceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'package';self.root.mkdir()
        (self.root/'media').mkdir();(self.root/'media/reference.mp4').write_bytes(b'original reference bytes')
        (self.root/'instructions.md').write_text('Keep source identity, geometry, and each reference binding.')
        self.manifest=self.root/'bundle.json'
        self.scene_map={'user_approval':'rejected','review_note':'Adaptation not accepted',
            'scenes':[{'id':'opening','required_slots':['reference','instructions'],'bindings':[
                {'slot':'reference','path':'media/reference.mp4','role':'reference-video','layer':'source','placement':{'frame_range':[0,24]}},
                {'slot':'instructions','path':'instructions.md','role':'constraints','layer':'metadata','placement':{}}]}]}
    def make(self):return freeze(self.root,self.manifest,self.scene_map)
    def edit_manifest(self,fn):
        data=json.loads(self.manifest.read_text());fn(data);self.manifest.write_text(json.dumps(data))
    def test_deterministic_portable_freeze_and_pending_review(self):
        self.make();first=self.manifest.read_bytes();self.make();self.assertEqual(first,self.manifest.read_bytes())
        newroot=Path(self.temp.name)/'moved';shutil.copytree(self.root,newroot)
        result=verify(newroot/'bundle.json',newroot)
        self.assertEqual(result['files_verified'],2);self.assertEqual(result['user_approval'],'rejected')
        self.assertFalse(result['user_approved']);self.assertFalse(result['visual_similarity_certified'])
        self.assertNotIn(str(self.root),first.decode())
    def test_changed_missing_and_unexpected_files_fail(self):
        self.make();p=self.root/'media/reference.mp4';original=p.read_bytes();p.write_bytes(b'changed')
        with self.assertRaisesRegex(BundleError,'Altered'):verify(self.manifest,self.root)
        p.unlink()
        with self.assertRaisesRegex(BundleError,'Missing'):verify(self.manifest,self.root)
        p.write_bytes(original);(self.root/'extra.png').write_bytes(b'new')
        with self.assertRaisesRegex(BundleError,'Unexpected'):verify(self.manifest,self.root)
        self.assertTrue(verify(self.manifest,self.root,strict=False)['integrity_verified'])
    def test_required_slots_paths_and_expected_binding_hash_checked(self):
        invalid=copy.deepcopy(self.scene_map);invalid['scenes'][0]['required_slots'].append('person')
        with self.assertRaisesRegex(BundleError,'required slots'):freeze(self.root,self.manifest,invalid)
        invalid=copy.deepcopy(self.scene_map);invalid['scenes'][0]['bindings'][0]['sha256']='0'*64
        with self.assertRaisesRegex(BundleError,'binding hash'):freeze(self.root,self.manifest,invalid)
        self.make()
        self.edit_manifest(lambda d:d['scenes'][0]['bindings'][0].update(sha256='0'*64))
        with self.assertRaisesRegex(BundleError,'binding hash'):verify(self.manifest,self.root)
    def test_traversal_and_absolute_paths_rejected(self):
        for path in ('../outside.txt','/tmp/outside.txt','C:/outside.txt','media/../../outside','media\\ref.mp4','./instructions.md'):
            invalid=copy.deepcopy(self.scene_map);invalid['scenes'][0]['bindings'][0]['path']=path
            with self.subTest(path=path),self.assertRaises(BundleError):freeze(self.root,self.manifest,invalid)
        self.make();self.edit_manifest(lambda d:d['files'][0].update(path='../outside.txt'))
        with self.assertRaises(BundleError):verify(self.manifest,self.root)
    def test_symlinks_cannot_escape_root_or_alias_assets(self):
        (self.root/'alias.mp4').symlink_to(self.root/'media/reference.mp4')
        with self.assertRaisesRegex(BundleError,'Symlink'):self.make()
    def test_exclusions_are_recorded_but_cannot_hide_required_binding(self):
        (self.root/'run.log').write_text('temporary');(self.root/'__pycache__').mkdir();(self.root/'__pycache__/x.pyc').write_bytes(b'cache')
        data=self.make();self.assertEqual(len(data['files']),2);self.assertTrue(verify(self.manifest,self.root)['integrity_verified'])
        invalid=copy.deepcopy(self.scene_map);invalid['scenes'][0]['bindings'][0]['path']='run.log'
        with self.assertRaisesRegex(BundleError,'excluded asset'):freeze(self.root,self.manifest,invalid)
    def test_no_implicit_or_forged_user_approval(self):
        invalid=copy.deepcopy(self.scene_map);invalid['user_approval']='approved'
        with self.assertRaisesRegex(BundleError,'cannot grant'):freeze(self.root,self.manifest,invalid)
        self.make();self.edit_manifest(lambda d:d.update(user_approved=True))
        with self.assertRaisesRegex(BundleError,'cannot certify'):verify(self.manifest,self.root)
    def test_manifest_glob_characters_excluded_exactly(self):
        self.manifest=self.root/'bundle[final].json';self.make();first=self.manifest.read_bytes();self.make()
        self.assertEqual(first,self.manifest.read_bytes());self.assertTrue(verify(self.manifest,self.root)['integrity_verified'])
    def test_nonfinite_placement_rejected(self):
        invalid=copy.deepcopy(self.scene_map);invalid['scenes'][0]['bindings'][0]['placement']['x']=float('nan')
        with self.assertRaisesRegex(BundleError,'finite JSON'):freeze(self.root,self.manifest,invalid)

if __name__=='__main__':unittest.main()
