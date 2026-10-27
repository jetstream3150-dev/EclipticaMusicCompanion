import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.package_release import package


class PackageReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'bundle'
        self.source.mkdir()
        self.exe = self.source / 'EclipticaMusicCompanion.exe'
        self.exe.write_bytes(b'test executable bytes')
        (self.source / '_internal').mkdir()
        self.asset = self.source / '_internal' / 'player.html'
        self.asset.write_bytes(b'test asset')
        lines = []
        for path in (self.exe, self.asset):
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(self.source).as_posix())
        (self.source / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf8')
        (self.source / 'BUNDLE_AUDIT.json').write_text('{}', encoding='utf8')
        (self.source / 'DEFENDER_SCAN.txt').write_text(
            'PASSED: Defender completed a custom scan with no matching detections.', encoding='utf8')
        self.output = self.root / 'test.zip'

    def test_package_preserves_audited_files(self):
        package(self.source, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read('EclipticaMusicCompanion.exe'), self.exe.read_bytes())
            self.assertEqual(archive.read('_internal/player.html'), self.asset.read_bytes())

    def test_changed_or_unlisted_file_is_rejected(self):
        self.asset.write_bytes(b'modified')
        with self.assertRaises(ValueError):
            package(self.source, self.output)
        self.asset.write_bytes(b'test asset')
        (self.source / 'unexpected.exe').write_bytes(b'unlisted')
        with self.assertRaises(ValueError):
            package(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_scan_report_and_nested_output_are_rejected(self):
        (self.source / 'DEFENDER_SCAN.txt').unlink()
        with self.assertRaises(ValueError):
            package(self.source, self.output)
        (self.source / 'DEFENDER_SCAN.txt').write_text('SCAN FAILED: unavailable', encoding='utf8')
        with self.assertRaises(ValueError):
            package(self.source, self.output)
        (self.source / 'DEFENDER_SCAN.txt').write_text(
            'PASSED: Defender completed a custom scan with no matching detections.', encoding='utf8')
        with self.assertRaises(ValueError):
            package(self.source, self.source / 'unsafe.zip')


if __name__ == '__main__':
    unittest.main()
