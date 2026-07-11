"""Import-boundary checks for the S0-T01 project skeleton."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"


class PackageImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(SOURCE_ROOT))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(SOURCE_ROOT))

    def test_top_level_package_imports_with_expected_metadata(self) -> None:
        package = importlib.import_module("era100x")

        self.assertEqual(package.__version__, "0.0.0")
        self.assertEqual(package.SPECIFICATION_VERSION, "V1.3.4")
        self.assertTrue(Path(package.__file__).resolve().is_relative_to(SOURCE_ROOT))

    def test_skeleton_contains_no_business_submodules(self) -> None:
        package = importlib.import_module("era100x")
        discovered = sorted(module.name for module in pkgutil.iter_modules(package.__path__))

        self.assertEqual(discovered, [])


if __name__ == "__main__":
    unittest.main()

