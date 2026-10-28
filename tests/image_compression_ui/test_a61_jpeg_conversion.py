import hashlib
import io
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from tests.image_compression.test_a03_single_winner import _business_image
from tests.image_compression_ui import test_image_compression_api as api_tests
from engine.image_compression.delivery_options import generate_delivery_candidates
from engine.image_compression.common import CompressionRuntimeError
from engine.output.metadata_writer import read_hdde_metadata
from tests.image_compression_ui import test_a06_batch_stability as batch_tests


class JpegConversionTests(unittest.TestCase):
    setUp = api_tests.ImageCompressionApiStage4Tests.setUp
    tearDown = api_tests.ImageCompressionApiStage4Tests.tearDown
    intake_bytes = api_tests.ImageCompressionApiStage4Tests.intake_bytes

    def convert(self, fmt, *, image=None, params=None, expected_status=200):
        stream = io.BytesIO()
        image = image or _business_image()
        image.save(stream, format=fmt, **({'lossless': True} if fmt == 'WEBP' else {}))
        data = stream.getvalue()
        intake = self.intake_bytes(data, 'source.' + {'JPEG':'jpg','PNG':'png','WEBP':'webp'}[fmt])
        response = self.client.post('/api/image-compression/run', json={
            'source_token': intake['source_token'], 'operation_mode': 'DELIVERY_OPTIMIZATION',
            'params': {'target_format':'JPEG'} if params is None else params,
        })
        self.assertEqual(response.status_code, expected_status, response.text)
        return response.json()['data' if expected_status == 200 else 'detail'], data

    def test_png_and_webp_larger_jpeg_still_publish_one_real_jpeg(self):
        for fmt in ('PNG', 'WEBP'):
            with self.subTest(fmt=fmt):
                data, source = self.convert(fmt)
                result = data['result']
                self.assertTrue(result['output_created'], result)
                record = self.state['task_registry'][result['task_id']]
                output = Path(record['output_path'])
                with Image.open(output) as decoded:
                    decoded.load()
                    self.assertEqual(decoded.format, 'JPEG')
                    self.assertEqual(decoded.size, (640,360))
                self.assertEqual(result['output_format'], 'JPEG')
                self.assertEqual(result['output_size_bytes'], output.stat().st_size)
                self.assertEqual(result['winner']['file_size'], output.stat().st_size)
                self.assertGreater(output.stat().st_size, len(source))
                self.assertLess(result['size_reduction_ratio'], 0)
                self.assertEqual(result['size_reduction_ratio'], 1-output.stat().st_size/len(source))
                self.assertEqual(result['winner']['quality_gate']['status'], 'PASS')
                self.assertEqual(result['public_output_count'], 1)
                self.assertEqual(len(result['candidates']), 1)
                self.assertTrue(result['delivery_eligible'])
                self.assertEqual(result['source_sha256'], hashlib.sha256(source).hexdigest())
                self.assertEqual(Path(record['source_path']).read_bytes(), source)
                self.assertTrue(all(c['format']=='JPG' for c in record['candidate_options']))
                self.assertTrue(read_hdde_metadata(output)['software'])

    def test_jpeg_keep_original_and_smart_matches_omitted_target(self):
        data, original = self.convert('JPEG')
        result = data['result']
        self.assertEqual(result['winner']['scheme_id'], 'keep_original')
        self.assertEqual(result['public_output_count'], 0)
        self.assertEqual(result['output_size_bytes'], len(original))
        automatic, _ = self.convert('JPEG', params={'target_format':'SMART_COMPRESSION'})
        default, _ = self.convert('JPEG', params={})
        for key in ('output_format', 'output_size_bytes', 'size_reduction_ratio'):
            self.assertEqual(automatic['result'][key], default['result'][key])
        self.assertEqual(automatic['result']['winner']['scheme_id'], default['result']['winner']['scheme_id'])

    def test_real_transparency_is_flattened_on_white_for_explicit_jpg(self):
        image = _business_image().convert('RGBA')
        image.putpixel((0,0), (255,0,0,0))
        data, _ = self.convert('PNG', image=image)
        result = data['result']
        self.assertEqual(result['output_format'], 'JPEG')
        self.assertFalse(result['alpha_preserved'])
        self.assertEqual(result['alpha_details']['conversion_action'], 'FLATTEN_ON_WHITE')
        self.assertEqual(result['alpha_details']['conversion_background_rgb'], [255,255,255])
        with Image.open(result['output_path']) as output:
            output.load()
            self.assertTrue(all(channel >= 245 for channel in output.convert('RGB').getpixel((0,0))))

    def test_animated_webp_and_disguised_extension_rejected(self):
        stream = io.BytesIO()
        _business_image().save(stream, format='WEBP', save_all=True,
                               append_images=[_business_image().transpose(Image.Transpose.FLIP_LEFT_RIGHT)], duration=100)
        response = self.client.post('/api/image-compression/intake', files={'file':('animated.webp',stream.getvalue(),'image/webp')})
        self.assertEqual(response.status_code,400)
        stream = io.BytesIO()
        _business_image().save(stream,format='PNG')
        response = self.client.post('/api/image-compression/intake', files={'file':('fake.webp',stream.getvalue(),'image/webp')})
        self.assertEqual(response.status_code,400)

    def test_no_passing_jpeg_does_not_fall_back_to_png(self):
        import engine.image_compression.delivery_options as core
        source = self.root/'source.png'
        _business_image().save(source)
        evaluate = core.evaluate_jpg_quality
        def rejected(*args, **kwargs):
            gate = evaluate(*args, **kwargs)
            gate.update(status='FAIL', failure_reasons=['CONTROLLED_QUALITY_FAILURE'])
            return gate
        output = self.root/'candidate-failure'
        with patch.object(core,'evaluate_jpg_quality',rejected):
            with self.assertRaises(CompressionRuntimeError) as raised:
                generate_delivery_candidates(source,output,source_filename=source.name,
                                             moment=datetime(2026,9,14),target_format='JPEG')
        self.assertEqual(raised.exception.failure_code,'JPG_NO_VALID_CANDIDATE')
        self.assertEqual(list(output.iterdir()),[])

    def test_normal_search_evaluates_full_pixels_above_analysis_bound(self):
        # Exercise the old 4 MP failure branch with a small, fast fixture.
        # Lower only the analysis dispatch boundary, never quality thresholds.
        with patch('engine.image_compression.jpg_quality_gate.MAX_ANALYSIS_PIXELS', 200_000):
            data, _ = self.convert('PNG')
        result = data['result']
        self.assertTrue(result['output_created'])
        self.assertEqual(result['winner']['quality_gate']['status'], 'PASS')
        self.assertEqual(result['output_dimensions'], {'width':640,'height':360})

    def test_metadata_reader_avoids_jpeg_pixel_decode_but_writer_still_checks_pixels(self):
        import engine.output.metadata_writer as writer
        from PIL.JpegImagePlugin import JpegImageFile
        stream = io.BytesIO()
        exif = Image.Exif()
        exif[270], exif[315], exif[274] = 'Source title', 'Source author', 6
        _business_image().save(stream,format='JPEG',exif=exif)
        data = stream.getvalue()
        with patch.object(JpegImageFile,'load',side_effect=AssertionError('metadata-only decode')):
            self.assertEqual(writer._read_exif(data).get(274),6)
            self.assertEqual(writer.read_hdde_metadata(data)['author'],'Source author')
        updated, report = writer.write_hdde_metadata_bytes(data,source_data=data)
        self.assertTrue(report['decoded_pixel_content_unchanged'])
        with Image.open(io.BytesIO(updated)) as decoded:
            decoded.load()
            self.assertEqual(decoded.getexif().get(274),6)


class WebpBatchConversionTests(unittest.TestCase):
    setUp = batch_tests.BatchStabilityTests.setUp
    tearDown = batch_tests.BatchStabilityTests.tearDown
    open = batch_tests.BatchStabilityTests.open
    close = batch_tests.BatchStabilityTests.close
    create = batch_tests.BatchStabilityTests.create
    status = batch_tests.BatchStabilityTests.status
    until = batch_tests.BatchStabilityTests.until
    assert_outputs = batch_tests.BatchStabilityTests.assert_outputs
    assert_items_stable_across_restart = batch_tests.BatchStabilityTests.assert_items_stable_across_restart

    def test_webp_larger_conversion_survives_restart_and_keeps_one_result(self):
        self.open()
        stream = io.BytesIO()
        _business_image().save(stream,format='WEBP',lossless=True)
        batch_id = self.create([('graphic.webp',stream.getvalue(),'image/webp')], target_format='JPEG')
        data = self.until(batch_id)
        item = data['items'][0]
        self.assertEqual(item['status'],'COMPLETED',item)
        self.assertTrue(item['formatConversion'])
        self.assertGreater(item['finalBytes'],item['originalBytes'])
        self.assertLess(item['savedPercent'],0)
        self.assert_outputs(data)
        self.close()
        self.open()
        self.assert_items_stable_across_restart(data['items'],self.status(batch_id)['items'])
        self.assert_outputs(data)
        # Emulate a lost final batch save while the registered Result survives.
        batch = self.service.batches[batch_id]
        batch['items'][0].update(status='PROCESSING', result_id='', final_bytes=None, output_sha256='')
        self.service.persist(batch)
        self.assertTrue(self.registry.delete_task_fact(item['taskId'])['result_preserved'])
        self.close()
        self.open()
        self.assert_items_stable_across_restart(data['items'],self.status(batch_id)['items'])
        self.assertNotIn(item['taskId'], self.registry)
        self.assert_outputs(data)


if __name__ == '__main__':
    unittest.main()
