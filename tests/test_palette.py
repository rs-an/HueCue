import importlib.util
from pathlib import Path
import tempfile
import subprocess
import sys
import json
import unittest
from PIL import Image

spec = importlib.util.spec_from_file_location("palette", Path(__file__).resolve().parents[1] / "scripts/extract.py")
palette = importlib.util.module_from_spec(spec)
spec.loader.exec_module(palette)


class PaletteTests(unittest.TestCase):
    def test_known_shares(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "colors.png"
            im = Image.new("RGB", (100, 100), "red")
            im.paste("blue", (75, 0, 100, 100))
            im.save(path)
            colors = palette.extract(path, 2)
            self.assertEqual([(c["hex"], c["percent"]) for c in colors], [("#FF0000", 75.0), ("#0000FF", 25.0)])

    def test_rejects_transparent_and_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.png"
            Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(path)
            with self.assertRaises(ValueError):
                palette.extract(path, 6)
            link = Path(folder) / "link.png"
            try:
                link.symlink_to(path)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows account lacks symlink privilege")
                raise
            with self.assertRaises(OSError):
                palette.extract(link, 6)

    def test_cli_exports_with_unicode_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "цвета sample.png"
            Image.new("RGB", (8, 8), (255, 10, 26)).save(source)
            result = subprocess.run(
                [sys.executable, str(Path(palette.__file__)), str(source),
                 "--output-root", str(root)], capture_output=True, text=True, check=True)
            output = Path(json.loads(result.stdout)["folder"])
            data = json.loads((output / "palette.json").read_text())
            self.assertEqual(data["colors"][0]["hex"], "#FF0A1A")
            self.assertIn("#FF0A1A", (output / "palette.css").read_text())
            with Image.open(output / "palette.png") as preview:
                self.assertEqual(preview.size, (1200, 800))

    def test_rejects_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises((ValueError, OSError)):
                palette.extract(Path(folder), 6)

    def test_ui_keeps_surfaces_and_accents(self):
        pixels = [(32,33,36)]*5000 + [(41,42,45)]*4500 + [(232,234,237)]*400 + [(255,110,63)]*50 + [(120,163,209)]*30 + [(130,173,130)]*20
        colors = palette.ui_palette(pixels, 8)
        self.assertEqual(len(colors), 6)
        self.assertAlmostEqual(sum(c["percent"] for c in colors), 100, places=2)

    def test_centering_and_plain_margins(self):
        source = Image.new("RGBA", (640,200), (32,33,36,255))
        colors = [{"hex":"#202124", "rgb":(32,33,36), "percent":100}]
        im = palette.preview(colors, source)
        self.assertEqual(im.getpixel((40,110)), (248,247,252))
        self.assertEqual(im.getpixel((40,420)), (32,33,36))
        self.assertEqual(im.getpixel((40,730)), (248,247,252))
