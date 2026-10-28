from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "public" / "branding" / "hdde"
EXPECTED_HASHES = {
    "app-icon.png": "91765705ECEF90B45DC41C8DF63D9E295CF7CC5EB30FA82EBB82ED32EED7200B",
    "ASSET_MANIFEST.txt": "C6CF3D3653B00FF0506329E745A0A2325E531E9682546CB4AFEDEE1BF5DBB8EB",
    "desktop-icon-master.png": "C662E4576588EB2ADEDB03CC337044AA8ED2B2D9DADCF5C61297F348BCDBE926",
    "hdde.ico": "9BD49B548FE7D1C448CABB323BA9A12BD9807ECC058EA4BCCF6E3E9FDD883510",
    "logo-dark.png": "7CCD12B91658151F5C992D9EF12BF89045D393509A631EC27FA3792A0DCE30B6",
    "logo-light.png": "95777225DEBC5D918CB944A356CAD60DF3E1F5D588E08828AB9D647EB9EE82CF",
    "splash-dark.png": "9AA15F7B71291AD692D1558BA476461F9E9875F66B4278432B22A66B65462728",
    "splash-light.png": "1FF0AE8A9D73AA1ED6FFB5180ABB01D788E7F22F0931DAB8D733793745974CC3",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class BrandAssetTests(unittest.TestCase):
    def test_official_asset_bytes_and_dimensions_are_preserved(self):
        self.assertEqual({path.name for path in ASSET_ROOT.iterdir()}, set(EXPECTED_HASHES))
        for name, expected in EXPECTED_HASHES.items():
            self.assertEqual(sha256(ASSET_ROOT / name), expected, name)

        expected_dimensions = {
            "app-icon.png": (1024, 1024),
            "desktop-icon-master.png": (1254, 1254),
            "logo-dark.png": (2254, 698),
            "logo-light.png": (1221, 378),
            "splash-dark.png": (1448, 1086),
            "splash-light.png": (1448, 1086),
        }
        for name, dimensions in expected_dimensions.items():
            with Image.open(ASSET_ROOT / name) as image:
                self.assertEqual(image.size, dimensions, name)
                image.verify()

        for name in ("app-icon.png", "desktop-icon-master.png", "logo-light.png"):
            with Image.open(ASSET_ROOT / name) as image:
                self.assertIn("A", image.getbands(), name)
                self.assertIsNotNone(image.getchannel("A").getbbox(), name)

    def test_windows_icon_contains_all_manifest_sizes(self):
        with Image.open(ASSET_ROOT / "hdde.ico") as image:
            self.assertEqual(
                set(image.ico.sizes()),
                {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)},
            )

    def test_frontend_and_pyinstaller_reference_only_official_assets(self):
        shell = (ROOT / "src" / "AppShell.jsx").read_text(encoding="utf-8")
        main = (ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "src" / "index.css").read_text(encoding="utf-8")
        spec = (ROOT / "VisualMasterPro.spec").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn('/branding/hdde/logo-light.png', shell)
        self.assertIn('/branding/hdde/logo-dark.png', shell)
        self.assertIn('/branding/hdde/splash-light.png', main)
        self.assertIn('/branding/hdde/splash-dark.png', main)
        self.assertIn('/branding/hdde/app-icon.png', index)
        self.assertNotIn('/favicon.svg', index)
        self.assertIn(':root[data-theme="light"] .hdde-app-shell .hdde-brand-logo--light', styles)
        self.assertIn(':root[data-theme="dark"] .hdde-app-shell .hdde-brand-logo--dark', styles)
        self.assertIn(':root[data-theme="light"] .hdde-startup-splash__image--light', styles)
        self.assertIn(':root[data-theme="dark"] .hdde-startup-splash__image--dark', styles)
        splash_rule = re.search(r"\.hdde-startup-splash__image\s*\{(?P<body>[^}]*)\}", styles, re.DOTALL)
        self.assertIsNotNone(splash_rule)
        self.assertIn("object-fit: contain", splash_rule.group("body"))
        self.assertNotIn("object-fit: cover", splash_rule.group("body"))
        self.assertIn("width: min(84vw, 112vh, 1280px)", splash_rule.group("body"))
        self.assertIn("height: auto", splash_rule.group("body"))
        self.assertIn("max-height: 84vh", splash_rule.group("body"))
        self.assertIn("aspect-ratio: 4 / 3", splash_rule.group("body"))
        self.assertIn("--splash-background: #fefefe", styles)
        self.assertIn("--splash-background: #01081e", styles)
        dark_brand_rule = re.search(
            r':root\[data-theme="dark"\] \.hdde-app-shell \.hdde-sidebar-brand\s*\{(?P<body>[^}]*)\}',
            styles,
            re.DOTALL,
        )
        self.assertIsNotNone(dark_brand_rule)
        self.assertNotIn("height:", dark_brand_rule.group("body"))
        self.assertNotIn("min-height:", dark_brand_rule.group("body"))
        self.assertNotIn("flex-basis:", dark_brand_rule.group("body"))
        self.assertIn("padding: 6px 18px", dark_brand_rule.group("body"))
        dark_logo_rule = re.search(
            r':root\[data-theme="dark"\] \.hdde-app-shell \.hdde-brand-logo--dark\s*\{(?P<body>[^}]*)\}',
            styles,
            re.DOTALL,
        )
        self.assertIsNotNone(dark_logo_rule)
        self.assertIn("width: min(100%, 176px)", dark_logo_rule.group("body"))
        self.assertIn("height: 52px", dark_logo_rule.group("body"))
        self.assertIn("('public/branding/hdde', 'public/branding/hdde')", spec)
        self.assertIn("icon='public/branding/hdde/hdde.ico'", spec)
        self.assertIn("!VisualMasterPro.spec", gitignore)

    def test_manifest_identifies_every_formal_asset(self):
        manifest = (ASSET_ROOT / "ASSET_MANIFEST.txt").read_text(encoding="utf-8")
        for name in EXPECTED_HASHES:
            if name != "ASSET_MANIFEST.txt":
                self.assertIn(name, manifest)


if __name__ == "__main__":
    unittest.main()
