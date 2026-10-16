import unittest

from app.serve import parse_threshold


class ServeCliTests(unittest.TestCase):
    def test_parse_threshold(self) -> None:
        self.assertEqual(parse_threshold("bottle:0.2:0.8"), ("bottle", (0.2, 0.8)))

    def test_parse_threshold_rejects_bad_order(self) -> None:
        with self.assertRaisesRegex(Exception, "less than"):
            parse_threshold("bottle:0.8:0.2")

    def test_parse_threshold_rejects_bad_shape(self) -> None:
        with self.assertRaisesRegex(Exception, "category"):
            parse_threshold("bottle:0.8")


if __name__ == "__main__":
    unittest.main()
