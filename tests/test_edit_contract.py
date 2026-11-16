import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from visual_fidelity.edit_contract import validate_edit

class EditContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'audio.wav').write_bytes(b'audio-a')
        (self.root/'image.png').write_bytes(b'image')
        self.data = {'fps':24,'frames':24,
            'assets':{'a':{'path':'image.png'}},
            'audio':{'path':'audio.wav','start':0,'speed':1},
            'music_sync':{'audio_sha256':hashlib.sha256(b'audio-a').hexdigest(),
                'clock':{'start':0,'speed':1},
                'events':[{'event_id':'hit','cue_time':.5,'frame':12}]},
            'asset_plan':{'slots':[{'id':'insert','role':'road','evidence':'reference frame20',
                'status':'ready','asset_ids':['a'],'interval':[0,24]}]},
            'frame_bindings':[{'frame':i,'base':{'source':'a'},'music_events':['hit'] if i==12 else []} for i in range(24)]}
    def tearDown(self): self.tmp.cleanup()
    def test_valid_bound_event_and_asset(self):
        r=validate_edit(self.data,self.root)
        self.assertEqual(r['music'],'bound')
        self.assertEqual(r['asset_slots'][0]['bound_frames'],24)
    def test_audio_replacement_invalidates_map(self):
        (self.root/'audio.wav').write_bytes(b'audio-b')
        with self.assertRaisesRegex(ValueError,'another audio'):validate_edit(self.data,self.root)
    def test_offset_invalidates_map(self):
        self.data['audio']['start']=1
        with self.assertRaisesRegex(ValueError,'clock'):validate_edit(self.data,self.root)
    def test_event_must_bind_and_quantize(self):
        self.data['music_sync']['events'][0]['frame']=14
        with self.assertRaisesRegex(ValueError,'nearest'):validate_edit(self.data,self.root)
        self.data['music_sync']['events'][0]['frame']=12
        self.data['frame_bindings'][12]['music_events']=[]
        with self.assertRaisesRegex(ValueError,'binding'):validate_edit(self.data,self.root)
    def test_asset_file_alone_does_not_satisfy_slot(self):
        for b in self.data['frame_bindings']:b['base']['source']='other'
        with self.assertRaisesRegex(ValueError,'consumed'):validate_edit(self.data,self.root)
    def test_generated_asset_requires_provenance(self):
        self.data['assets']['a']['origin']='generated'
        with self.assertRaisesRegex(ValueError,'provenance'):validate_edit(self.data,self.root)
    def test_silent_bypass_forbidden_explicit_exception_allowed(self):
        del self.data['music_sync']
        with self.assertRaisesRegex(ValueError,'requires'):validate_edit(self.data,self.root)
        self.data['music_sync']={'mode':'editorial_override','reason':'dialogue scene, no musical editing intended'}
        self.assertEqual(validate_edit(self.data,self.root)['music'],'unsynchronized_override')

if __name__=='__main__':unittest.main()
