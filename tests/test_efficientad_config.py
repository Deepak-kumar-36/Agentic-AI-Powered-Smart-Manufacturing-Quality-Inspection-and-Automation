import unittest

from app.efficientad.config import EfficientADConfig


class EfficientADConfigTests(unittest.TestCase):
    def test_serialization_is_stable(self) -> None:
        first = EfficientADConfig()
        second = EfficientADConfig()
        self.assertEqual(first.stable_json(), second.stable_json())
        self.assertEqual(first.digest(), second.digest())

    def test_only_small_variant_is_supported(self) -> None:
        with self.assertRaises(ValueError):
            EfficientADConfig(model_size="medium")
