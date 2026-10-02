import io
import unittest
from PIL import Image, ImageDraw
from local_cutout import cutout_png


class LocalCutoutContracts(unittest.TestCase):
    def sample(self, alpha=255):
        image=Image.new('RGBA',(240,180),(170,205,215,alpha))
        ImageDraw.Draw(image).ellipse((75,20,165,160),fill=(176,70,51,alpha))
        buffer=io.BytesIO();image.save(buffer,'PNG')
        return buffer.getvalue()

    def test_subject_alpha_and_original_pixels(self):
        source=self.sample();result=Image.open(io.BytesIO(cutout_png(source)))
        self.assertEqual(result.size,(240,180))
        self.assertEqual(result.getpixel((0,0))[3],0)
        self.assertEqual(result.getpixel((120,90)),(176,70,51,255))
        self.assertEqual(Image.open(io.BytesIO(source)).getpixel((0,0)),(170,205,215,255))

    def test_existing_transparency_survives(self):
        result=Image.open(io.BytesIO(cutout_png(self.sample(128))))
        self.assertLessEqual(result.getchannel('A').getextrema()[1],128)
        self.assertEqual(result.getpixel((120,90))[3],128)

    def test_invalid_regions_and_invalid_image(self):
        for region in [{'x':.9,'y':0,'width':.5,'height':1},{'x':0,'y':0,'width':0,'height':1},{'x':float('nan'),'y':0,'width':.5,'height':1}]:
            with self.assertRaises(ValueError):cutout_png(self.sample(),region)
        with self.assertRaises(OSError):cutout_png(b'not an image')


if __name__=='__main__':unittest.main()
