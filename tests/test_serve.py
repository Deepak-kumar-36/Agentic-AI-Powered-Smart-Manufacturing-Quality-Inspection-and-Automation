import unittest
from pathlib import Path
import tempfile

from app.serve import build_parser, environment_flag, parse_threshold


class ServeCliTests(unittest.TestCase):
    def test_parse_threshold(self) -> None:
        self.assertEqual(parse_threshold("bottle:0.2:0.8"), ("bottle", (0.2, 0.8)))

    def test_parse_threshold_rejects_bad_order(self) -> None:
        with self.assertRaisesRegex(Exception, "less than"):
            parse_threshold("bottle:0.8:0.2")

    def test_parse_threshold_rejects_bad_shape(self) -> None:
        with self.assertRaisesRegex(Exception, "category"):
            parse_threshold("bottle:0.8")

    def test_parser_has_durable_database_default(self) -> None:
        args = build_parser().parse_args([
            "--metadata", "metadata.json",
            "--artifacts", "artifacts",
            "--teacher", "teacher.pth",
            "--image-root", "images",
            "--threshold", "bottle:0.2:0.8",
        ])
        self.assertEqual(args.db, Path("data/inspection.sqlite3"))

    def test_hardware_is_explicitly_opt_in(self) -> None:
        args = build_parser().parse_args([
            "--metadata", "metadata.json", "--artifacts", "artifacts", "--teacher", "teacher.pth",
            "--image-root", "images", "--threshold", "bottle:0.2:0.8",
        ])
        self.assertIsNone(args.hardware_serial_port)

    def test_auto_capture_environment_flag_is_disabled_by_default_and_strict(self) -> None:
        self.assertFalse(environment_flag("AUTO_CAPTURE_ON_IR", {}))
        self.assertTrue(environment_flag("AUTO_CAPTURE_ON_IR", {"AUTO_CAPTURE_ON_IR": "true"}))
        with self.assertRaisesRegex(ValueError, "true or false"):
            environment_flag("AUTO_CAPTURE_ON_IR", {"AUTO_CAPTURE_ON_IR": "sometimes"})


if __name__ == "__main__":
    unittest.main()
