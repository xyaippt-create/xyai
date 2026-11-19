"""Real image/API regressions for unlimited-byte, strictly lossless compression."""
import hashlib
import io
import struct
import time
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from engine.image_compression.delivery_options import generate_delivery_candidates
from tests.image_compression_ui import test_a06_batch_stability as batch_tests


class LosslessLargeIntakeTests(unittest.TestCase):
    setUp = batch_tests.BatchStabilityTests.setUp
    tearDown = batch_tests.BatchStabilityTests.tearDown
    open = batch_tests.BatchStabilityTests.open
    close = batch_tests.BatchStabilityTests.close
    create = batch_tests.BatchStabilityTests.create
    status = batch_tests.BatchStabilityTests.status

    def test_over_50mb_single_batch_and_result_reuse_keep_exact_pixels(self):
        self.open()
        stream = io.BytesIO()
        # Real decoded pixels, not padding appended to a tiny image.
        Image.new('RGB', (4300, 4100), (32, 104, 187)).save(stream, format='PNG', compress_level=0)
        payload = stream.getvalue()
        self.assertGreater(len(payload), 50 * 1024 * 1024)
        digest = hashlib.sha256(payload).hexdigest()
        caps = self.client.get('/api/image-compression/capabilities').json()['data']
        self.assertIsNone(caps['limits']['max_upload_bytes'])
        file = ('large.png', payload, 'image/png')
        response = self.client.post('/api/image-compression/intake', files={'file': file})
        self.assertEqual(response.status_code, 200, response.text)
        intake = response.json()['data']
        self.assertEqual(intake['size_bytes'], len(payload))
        batch_id = self.create([file], target_format='SMART_COMPRESSION')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            data = self.status(batch_id)
            if not data['running']:
                break
            time.sleep(.05)
        item = data['items'][0]
        self.assertEqual(item['status'], 'COMPLETED', data)
        record = self.registry[item['taskId']]
        output = Path(record['output_path'])
        self.assertEqual(item['sourceSha256'], digest)
        self.assertLess(output.stat().st_size, len(payload))
        with Image.open(output) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (4300, 4100))
            self.assertEqual(decoded.convert('RGB').getextrema(), ((32, 32), (104, 104), (187, 187)))
        # A real >50MB registered Result must also be eligible for compression.
        source = self.root / 'large-existing-result.png'
        source.write_bytes(payload)
        self.registry['source-task'] = {
            'task_id': 'source-task', 'result_id': 'source-result', 'feature_key': 'image_processing',
            'status': 'completed', 'task_status': 'completed', 'source_path': str(source),
            'output_path': str(source), 'result_file': str(source), 'output_sha256': digest,
        }
        reused = self.client.post('/api/image-compression/intake-result', json={'result_id': 'source-result'})
        self.assertEqual(reused.status_code, 200, reused.text)
        self.assertEqual(reused.json()['data']['source_result_sha256'], digest)
        color = self.client.post('/api/color-correction/intake-result', json={'result_id': 'source-result'})
        self.assertEqual(color.status_code, 413, color.text)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)

    def test_gamma_palette_and_transparent_rgb_survive_lossless_png(self):
        source = self.root / 'palette.png'
        image = Image.new('P', (320, 240))
        image.putpalette([i for c in range(256) for i in (c, 255-c, c//2)])
        image.paste(1, (10, 10, 120, 80))
        info = PngInfo()
        info.add(b'gAMA', struct.pack('>I', 45455))
        image.save(source, pnginfo=info, transparency=bytes([0, 128]+[255]*254), compress_level=0)
        before = source.read_bytes()
        generated = generate_delivery_candidates(source, self.output, source_filename=source.name, moment=datetime(2026, 11, 1))
        winner = generated['winner']
        self.assertTrue(winner['lossless_verified'])
        self.assertTrue(winner['metadata_details']['lossless_verification']['color_rendering_preserved'])
        with Image.open(source) as a, Image.open(winner['output_path']) as b:
            self.assertEqual(a.info['gamma'], b.info['gamma'])
            np.testing.assert_array_equal(np.asarray(a.convert('RGBA')), np.asarray(b.convert('RGBA')))
        self.assertEqual(source.read_bytes(), before)

    def test_oriented_png_keeps_display_pixels_and_gamma(self):
        source = self.root / 'rotated.png'
        image = Image.new('RGB', (240, 120), 'blue')
        image.paste('red', (0, 0, 80, 30))
        exif = Image.Exif(); exif[274] = 6
        info = PngInfo(); info.add(b'gAMA', struct.pack('>I', 45455))
        image.save(source, exif=exif, pnginfo=info, compress_level=0)
        result = generate_delivery_candidates(source, self.output, source_filename=source.name, moment=datetime(2026, 11, 1))
        with Image.open(source) as a, Image.open(result['winner']['output_path']) as b:
            np.testing.assert_array_equal(np.asarray(ImageOps.exif_transpose(a)), np.asarray(ImageOps.exif_transpose(b)))
            self.assertEqual(a.info['gamma'], b.info['gamma'])


if __name__ == '__main__':
    unittest.main()
