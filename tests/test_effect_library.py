from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from visual_fidelity.effect_library import analyze_reference, index, recommend, register, write


class EffectLibraryTest(unittest.TestCase):
    def test_same_version_is_idempotent_and_cannot_replace_media(self):
        with TemporaryDirectory() as work:
            root=Path(work)
            asset=root/'preview.mp4'
            asset.write_bytes(b'original')
            card={'id':'orbita','kind':'motion','title':'Órbita','description':'Texto na cena',
                  'version':'1.0.0','status':'pronto','tags':['corpo'],
                  'source':{'type':'autoral','details':'exemplo'},
                  'files':[asset.name],'recipe':{'engine':'test','entry':'render'}}
            manifest=root/'card.json'
            write(manifest,card)
            release=register(manifest,root/'catalog')
            self.assertEqual(register(manifest,root/'catalog'),release)
            found=recommend(index(root/'catalog'),'orbita CORPO','motion')
            self.assertEqual(found[0]['id'],'orbita')
            asset.write_bytes(b'variante')
            with self.assertRaisesRegex(ValueError,'versão'):
                register(manifest,root/'catalog')

    def test_index_verifies_integrity(self):
        with TemporaryDirectory() as work:
            root=Path(work)
            (root/'sample.wav').write_bytes(b'sound')
            card={'id':'toque','kind':'som','title':'Toque','description':'Clique curto',
                  'version':'1.0.0','status':'pronto','tags':['clique'],
                  'source':{'type':'licenciado','details':'ativo livre','usage':'CC0-1.0'},
                  'files':['sample.wav'],'recipe':{'engine':'test','entry':'mix'}}
            write(root/'card.json',card)
            release=register(root/'card.json',root/'compiled')
            (release/'sample.wav').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'alterado'):
                index(root/'compiled')

    def test_analysis_flags_bright_insert_as_candidate(self):
        with TemporaryDirectory() as work:
            video=Path(work)/'cuts.mp4'
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),30,(96,54))
            if not writer.isOpened():
                self.skipTest('OpenCV não dispõe do codec MP4 local.')
            try:
                for level in (0,)*12+(255,)*4+(0,)*13:
                    writer.write(np.full((54,96,3),level,dtype='uint8'))
            finally:
                writer.release()
            rows=analyze_reference(video)['candidates']
            bright=[row for row in rows if row['candidate']=='insert_claro_curto']
            self.assertEqual(bright[0]['frames'],[12,16])


if __name__=='__main__':
    unittest.main()
