import unittest


class PackageTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        import coding_harness

        self.assertTrue(coding_harness.__version__)
