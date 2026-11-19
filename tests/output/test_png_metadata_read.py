"""PNG metadata reads preserve tail chunks without re-decoding the raster."""
import io
import unittest
from unittest.mock import patch

from PIL import Image, ImageFile, PngImagePlugin

from engine.output import metadata_writer as writer


def tail_metadata_png():
    image = Image.new("RGB", (32, 24), (61, 121, 183))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_itxt("Title", "原始标题")
    metadata.add_itxt("Author", "原始作者", zip=True)
    metadata.add_text("Comment", "original comment", zip=True)
    metadata.add_itxt("XML:com.adobe.xmp", '<x:xmpmeta xmlns:x="adobe:ns:meta/"/>', zip=True)
    exif = Image.Exif()
    exif[271], exif[315], exif[274] = "camera", "artist", 6
    stream = io.BytesIO()
    image.save(stream, format="PNG", pnginfo=metadata, exif=exif, dpi=(96.012,96.012))
    chunks = writer._png_chunks(stream.getvalue())
    tail = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"pHYs"}
    return writer.PNG_SIGNATURE + b"".join(
        raw for kind, _, raw in chunks if kind not in tail and kind != b"IEND"
    ) + b"".join(raw for kind, _, raw in chunks if kind in tail) + chunks[-1][2]


class PngMetadataReadTests(unittest.TestCase):
    def test_tail_metadata_matches_full_decoder_without_raster_load(self):
        data = tail_metadata_png()
        with Image.open(io.BytesIO(data)) as reference:
            reference.load()
            expected = dict(reference.info)
            exif = dict(reference.getexif())
        with patch.object(ImageFile.ImageFile, "load", side_effect=AssertionError("unexpected pixel decode")):
            metadata = writer.read_hdde_metadata(data)
            self.assertEqual(metadata["title"], expected["Title"])
            self.assertEqual(metadata["author"], expected["Author"])
            self.assertEqual(metadata["comment"], expected["Comment"])
            self.assertEqual(dict(writer._read_exif(data)), exif)
            self.assertEqual(writer._read_effective_dpi(data), expected["dpi"])
            self.assertEqual(writer._extract_xmp(data), expected["XML:com.adobe.xmp"].encode())

    def test_tail_metadata_bad_crc_is_rejected(self):
        data = tail_metadata_png()
        chunks = writer._png_chunks(data)
        changed = []
        for kind, _, raw in chunks:
            if kind == b"eXIf":
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
            changed.append(raw)
        with self.assertRaisesRegex(SyntaxError, "checksum"):
            writer.read_hdde_metadata(writer.PNG_SIGNATURE + b"".join(changed))

    def test_real_corrupt_raster_still_fails_full_metadata_write(self):
        data = tail_metadata_png()
        chunks = writer._png_chunks(data)
        changed = []
        for kind, payload, raw in chunks:
            if kind == b"IDAT":
                payload = payload[:-1] + bytes([payload[-1] ^ 1])
                raw = writer._png_chunk(kind, payload)
            changed.append(raw)
        with self.assertRaises(OSError):
            writer.write_hdde_metadata_bytes(writer.PNG_SIGNATURE + b"".join(changed))
        self.assertFalse(ImageFile.LOAD_TRUNCATED_IMAGES)

    def test_animated_png_metadata_keeps_existing_full_decode_path(self):
        stream = io.BytesIO()
        frames = [Image.new("RGBA",(16,16),color) for color in ["red","blue"]]
        info = PngImagePlugin.PngInfo()
        info.add_text("Title","animated source")
        frames[0].save(stream,format="PNG",save_all=True,append_images=frames[1:],pnginfo=info)
        self.assertEqual(writer.read_hdde_metadata(stream.getvalue())["title"],"animated source")
