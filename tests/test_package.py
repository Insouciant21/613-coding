import unittest


class PackageTests(unittest.TestCase):
    def test_package_exposes_version(self) -> None:
        import coding613

        self.assertTrue(coding613.__version__)
