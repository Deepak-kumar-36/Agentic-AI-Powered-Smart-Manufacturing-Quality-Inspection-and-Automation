from pathlib import Path
import shutil
import subprocess
import unittest


class DashboardAnalyticsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable; dashboard analytics tests not run")
    def test_node_analytics(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run(
            [shutil.which("node"), "--test", "tests/dashboard_analytics.test.cjs"],
            cwd=root,
            check=True,
        )
