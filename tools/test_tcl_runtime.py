import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from EclipticaMusic import verify_frozen_tk_assets


class Interpreter:
    def __init__(self, library):
        self.library = library

    def eval(self, command):
        assert command == 'info library'
        return self.library


class FrozenTkAssetTests(unittest.TestCase):
    def test_embedded_dll_libraries_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for dll, filename in (('tcl90.dll', 'tcl_library/init.tcl'),
                                  ('tcl9tk90.dll', 'tk_library/tk.tcl')):
                with ZipFile(root / dll, 'w') as archive:
                    archive.writestr(filename, 'content')
            interp = Interpreter('//zipfs:/lib/tcl/tcl_library')
            verify_frozen_tk_assets(interp, root)
            (root / 'tcl9tk90.dll').unlink()
            with self.assertRaises(FileNotFoundError):
                verify_frozen_tk_assets(interp, root)

    def test_filesystem_libraries_are_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('_tcl_data/init.tcl', '_tk_data/tk.tcl'):
                file = root / name
                file.parent.mkdir(exist_ok=True)
                file.write_text('content')
            interp = Interpreter('C:/Python/tcl/tcl8.6')
            verify_frozen_tk_assets(interp, root)
            (root / '_tcl_data/init.tcl').unlink()
            with self.assertRaises(FileNotFoundError):
                verify_frozen_tk_assets(interp, root)


if __name__ == '__main__':
    unittest.main()
