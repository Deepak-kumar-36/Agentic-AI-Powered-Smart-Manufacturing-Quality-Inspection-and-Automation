import unittest

from app.patchcore.core import PatchCoreDependencyError
from app.patchcore.runtime import WideResNetPatchCore


class RuntimeTests(unittest.TestCase):
    def test_runtime_requires_inference_dependencies(self) -> None:
        try:
            runtime = WideResNetPatchCore()
        except PatchCoreDependencyError:
            self.skipTest("torch and torchvision are not installed in the test interpreter")
        self.assertEqual(runtime.device.type, "cpu")


if __name__ == "__main__":
    unittest.main()
