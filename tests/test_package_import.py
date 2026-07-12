"""Import-boundary checks for the S0-T01 project skeleton."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
APPROVED_STAGE_ZERO_TOP_LEVEL_PACKAGES = frozenset({"contracts", "foundation", "spike"})


def assert_only_approved_top_level_packages(discovered: set[str]) -> None:
    unexpected = discovered - APPROVED_STAGE_ZERO_TOP_LEVEL_PACKAGES
    if unexpected:
        raise AssertionError(f"unapproved top-level packages: {sorted(unexpected)}")
    missing = APPROVED_STAGE_ZERO_TOP_LEVEL_PACKAGES - discovered
    if missing:
        raise AssertionError(f"missing approved top-level packages: {sorted(missing)}")


class PackageImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(SOURCE_ROOT))

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(SOURCE_ROOT))

    def test_top_level_package_imports_with_expected_metadata(self) -> None:
        package = importlib.import_module("era100x")

        self.assertEqual(sys.version_info[:2], (3, 12))
        self.assertEqual(package.__version__, "0.0.0")
        self.assertEqual(package.SPECIFICATION_VERSION, "V1.3.4")
        self.assertTrue(Path(package.__file__).resolve().is_relative_to(SOURCE_ROOT))

    def test_package_contains_only_approved_stage_zero_submodules(self) -> None:
        package = importlib.import_module("era100x")
        discovered = {module.name for module in pkgutil.iter_modules(package.__path__)}
        assert_only_approved_top_level_packages(discovered)

    def test_unknown_top_level_package_is_rejected(self) -> None:
        with self.assertRaisesRegex(AssertionError, "unapproved top-level packages"):
            assert_only_approved_top_level_packages(
                {*APPROVED_STAGE_ZERO_TOP_LEVEL_PACKAGES, "unapproved_package"}
            )

    def test_unapproved_business_packages_cannot_be_imported(self) -> None:
        forbidden_modules = (
            "era100x.adapters",
            "era100x.analytics",
            "era100x.data",
            "era100x.domain",
            "era100x.execution",
            "era100x.research",
            "era100x.risk",
            "era100x.state",
            "era100x.strategy",
        )

        for module_name in forbidden_modules:
            with self.subTest(module_name=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
