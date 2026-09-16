import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE_DIR / "deploy" / "deploy.sh"


class DeploymentScriptTests(unittest.TestCase):
    def run_script(self, *args, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            env = {"PATH": os.environ["PATH"], "PROJECT_ID": "test-project", **overrides}
            # dry-run에서 gcloud를 호출하면 실패하도록 하는 스텁.
            fake = Path(directory) / "gcloud"
            marker = Path(directory) / "unexpected-call"
            fake.write_text('#!/bin/sh\ntouch "$TEST_MARKER"\nexit 91\n')
            fake.chmod(0o755)
            env["PATH"] = f"{directory}:{env['PATH']}"
            env["TEST_MARKER"] = str(marker)
            result = subprocess.run(
                ["bash", str(SCRIPT), *args], cwd=directory, env=env,
                capture_output=True, text=True, timeout=10,
            )
            self.assertFalse(marker.exists(), "dry-run/help must not invoke gcloud")
            return result

    def test_dry_run_from_another_directory_builds_only_cloud_run_source(self):
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"--source={SOURCE_DIR}", result.stdout)
        self.assertIn("GEMINI_API_KEY=GEMINI_API_KEY:1", result.stdout)
        self.assertIn("roles/secretmanager.secretAccessor", result.stdout)
        self.assertIn("roles/run.builder", result.stdout)
        self.assertIn("--no-allow-unauthenticated", result.stdout)
        self.assertIn("--invoker-iam-check", result.stdout)
        self.assertNotIn("versions access", result.stdout)

    def test_public_access_requires_explicit_option(self):
        result = self.run_script("--dry-run", ALLOW_UNAUTHENTICATED="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--allow-unauthenticated", result.stdout)
        self.assertNotIn("--no-allow-unauthenticated", result.stdout)

    def test_invalid_timeout_or_auth_configuration_fails_before_gcloud(self):
        for values in (
            {"CHAT_TIMEOUT_SECONDS": "300", "REQUEST_TIMEOUT_SECONDS": "300"},
            {"REQUEST_TIMEOUT_SECONDS": "3601"},
            {"CHAT_TIMEOUT_SECONDS": "invalid"},
            {"ALLOW_UNAUTHENTICATED": "yes"},
            {"SERVICE_ACCOUNT_ID": "same", "BUILD_SERVICE_ACCOUNT_ID": "same"},
        ):
            with self.subTest(values=values):
                self.assertNotEqual(self.run_script("--dry-run", **values).returncode, 0)

    def test_help_needs_no_project_or_gcloud(self):
        result = self.run_script("--help", PROJECT_ID="")
        self.assertEqual(result.returncode, 0)
        self.assertIn("PROJECT_ID", result.stdout)


if __name__ == "__main__":
    unittest.main()
