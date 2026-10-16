import unittest

from app.efficientad.native import EfficientADDependencyError, pdn_small


class NativeEfficientADTests(unittest.TestCase):
    def test_native_module_is_dependency_lazy(self) -> None:
        try:
            model = pdn_small()
        except EfficientADDependencyError:
            self.skipTest("torch is not installed in the system test interpreter")
        self.assertEqual(model[-1].out_channels, 384)


if __name__ == "__main__":
    unittest.main()
