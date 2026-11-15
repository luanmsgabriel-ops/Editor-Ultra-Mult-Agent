import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from visual_fidelity.effect_presets import apply_cube, fit_anchor, transition, write_cube


class AnchorFitTest(unittest.TestCase):
    def test_anchor_matches_different_source_and_canvas(self):
        source=(1920,1080)
        canvas=(720,1280)
        anchor=(.37,.66)
        target=(.48,.42)
        w,h,x,y=fit_anchor(source,canvas,anchor,target)
        self.assertLessEqual(abs(w*anchor[0]-x-canvas[0]*target[0]),1)
        self.assertLessEqual(abs(h*anchor[1]-y-canvas[1]*target[1]),1)
        self.assertLess(abs(w/h-source[0]/source[1]),.004)

    def test_edge_is_rejected_if_cannot_be_aligned(self):
        with self.assertRaisesRegex(ValueError,'borda'):
            fit_anchor((540,960),(720,1280),(0,.5),(.5,.5))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools are needed')
class EffectsRenderTest(unittest.TestCase):
    def plate(self, path, color, frames):
        subprocess.run([
            'ffmpeg','-v','error','-f','lavfi','-i',f'color={color}:size=36x64:rate=30',
            '-frames:v',str(frames),'-c:v','libx264','-threads','1',str(path),
        ], check=True)

    def video_info(self,path):
        return json.loads(subprocess.check_output([
            'ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,avg_frame_rate',
            '-of','json',str(path),
        ]))['streams'][0]

    def sample(self,path,pixfmt):
        return subprocess.check_output([
            'ffmpeg','-v','error','-i',str(path),'-vf','scale=2:2','-pix_fmt',pixfmt,'-f','rawvideo','-',
        ])

    def test_flash_has_exact_video_frames(self):
        with TemporaryDirectory() as working:
            folder=Path(working)
            a,b,target=(folder/name for name in ('a.mp4','b.mp4','joined.mp4'))
            self.plate(a,'black',3)
            self.plate(b,'navy',2)
            transition(a,b,target,(36,64),30,((.5,.5),(.5,.5)),(.5,.5),4)
            self.assertEqual(self.video_info(target),{'avg_frame_rate':'30/1','nb_frames':'9'})
            pixels=self.sample(target,'gray')
            white=[frame for frame,value in enumerate(pixels[::4]) if value>225]
            self.assertEqual(white,[3,4,5,6])

    def test_cube_render_is_neutral_and_preserves_length(self):
        with TemporaryDirectory() as working:
            folder=Path(working)
            source,lut,out=(folder/name for name in ('red.mp4','look.cube','graded.mp4'))
            self.plate(source,'red',5)
            write_cube(lut,side=3)
            self.assertEqual(len(lut.read_text().splitlines()),31)
            apply_cube(source,lut,out)
            self.assertEqual(self.video_info(out),{'avg_frame_rate':'30/1','nb_frames':'5'})
            pixels=self.sample(out,'rgb24')
            self.assertTrue(all(max(pixels[i:i+3])-min(pixels[i:i+3])<4 for i in range(0,len(pixels),3)))


if __name__=='__main__':
    unittest.main()
