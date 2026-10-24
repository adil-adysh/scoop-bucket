#!/usr/bin/env python3
"""Tests for Scoop git-explain manifest updater and metadata verification.

No network calls are made; all external interactions use mocks and fixtures.
"""

import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import update_git_explain


SAMPLE_MANIFEST = {
    "version": "0.2.1",
    "description": "Accessible local explanations for changed source code",
    "homepage": "https://github.com/adil-adysh/git-explain",
    "license": "Apache-2.0",
    "depends": "git",
    "bin": "git-explain.exe",
    "architecture": {
        "64bit": {
            "url": "https://github.com/adil-adysh/git-explain/releases/download/v0.2.1/git-explain-v0.2.1-windows-x86_64.zip",
            "hash": "daa417569bb5e5035a8aeb15db81c71d462a20d8623c4d90f743e02b07a6b06c",
        }
    },
    "checkver": "github",
    "autoupdate": {
        "architecture": {
            "64bit": {
                "url": "https://github.com/adil-adysh/git-explain/releases/download/v$version/git-explain-v$version-windows-x86_64.zip",
                "hash": {
                    "url": "https://github.com/adil-adysh/git-explain/releases/download/v$version/SHA256SUMS.txt"
                },
            }
        },
    },
}


def make_release_payload(tag="v0.2.2", draft=False, prerelease=False, zip_url=None, sums_url=None):
    if zip_url is None:
        zip_url = f"https://github.com/adil-adysh/git-explain/releases/download/{tag}/git-explain-{tag}-windows-x86_64.zip"
    if sums_url is None:
        sums_url = f"https://github.com/adil-adysh/git-explain/releases/download/{tag}/SHA256SUMS.txt"
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {
                "name": f"git-explain-{tag}-windows-x86_64.zip",
                "browser_download_url": zip_url,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": sums_url,
            },
        ],
    }


class TestGitExplainScoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manifest_path = os.path.join(self.temp_dir.name, "git-explain.json")
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_MANIFEST, f, indent=4)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_manifest_file_metadata(self):
        """Verify the actual bucket/git-explain.json in the repository has exact required metadata."""
        repo_manifest = os.path.join(REPO_ROOT, "bucket", "git-explain.json")
        self.assertTrue(os.path.isfile(repo_manifest), "bucket/git-explain.json must exist")
        with open(repo_manifest, "r", encoding="utf-8") as f:
            data = json.load(f)

        version = data.get("version")
        self.assertIsInstance(version, str)
        self.assertIsNotNone(
            re.fullmatch(update_git_explain.VERSION_PATTERN, version),
            f"Manifest version '{version}' must be a valid plain stable semver",
        )
        self.assertEqual(data.get("homepage"), "https://github.com/adil-adysh/git-explain")
        self.assertEqual(data.get("license"), "Apache-2.0")
        self.assertEqual(data.get("description"), "Accessible local explanations for changed source code")
        self.assertEqual(data.get("depends"), "git")
        self.assertIn(data.get("bin"), ["git-explain.exe", ["git-explain.exe"]])

        arch = data.get("architecture", {}).get("64bit", {})
        expected_zip_url = (
            f"https://github.com/adil-adysh/git-explain/releases/download/v{version}/"
            f"git-explain-v{version}-windows-x86_64.zip"
        )
        self.assertEqual(arch.get("url"), expected_zip_url)

        arch_hash = arch.get("hash", "")
        self.assertIsInstance(arch_hash, str)
        self.assertIsNotNone(
            re.fullmatch(r"^[0-9a-f]{64}$", arch_hash),
            f"Manifest hash '{arch_hash}' must be a 64-character lowercase hex string",
        )

        self.assertEqual(data.get("checkver"), "github")
        auto_arch = data.get("autoupdate", {}).get("architecture", {}).get("64bit", {})
        self.assertEqual(
            auto_arch.get("url"),
            "https://github.com/adil-adysh/git-explain/releases/download/v$version/git-explain-v$version-windows-x86_64.zip",
        )
        auto_hash = auto_arch.get("hash", {})
        self.assertEqual(
            auto_hash.get("url"),
            "https://github.com/adil-adysh/git-explain/releases/download/v$version/SHA256SUMS.txt",
        )
        self.assertNotIn("hash", data.get("autoupdate", {}))

    def test_badversion_draft_prerelease(self):
        """Reject draft, prerelease, or malformed/non-stable version tags."""
        # Draft release
        draft_release = make_release_payload(tag="v0.2.2", draft=True)
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.validate_release(draft_release)
        self.assertIn("draft", str(ctx.exception).lower())

        # Prerelease
        prerelease = make_release_payload(tag="v0.2.2", prerelease=True)
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.validate_release(prerelease)
        self.assertIn("prerelease", str(ctx.exception).lower())

        # Bad version tags
        bad_tags = [
            "0.2.2",
            "v0.2.2-rc1",
            "v0.2.2-beta",
            "v0.2.2.1",
            "latest",
            "v1.0",
            "vA.B.C",
            "v0.02.2",
            "v01.2.2",
            "v1.2.00",
            "v0.2.2\n",
            "v0.2.2 ",
            " v0.2.2",
            "v0.2.\uff12",
        ]
        for tag in bad_tags:
            bad_release = make_release_payload(tag=tag)
            with self.assertRaises(ValueError):
                update_git_explain.validate_release(bad_release)

    def test_wrongrepo_url(self):
        """Reject download URLs outside the allowlisted repo or mismatching expected pattern."""
        wrong_repo = make_release_payload(
            tag="v0.2.2",
            zip_url="https://github.com/other-org/git-explain/releases/download/v0.2.2/git-explain-v0.2.2-windows-x86_64.zip",
        )
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.validate_release(wrong_repo)
        self.assertIn("url", str(ctx.exception).lower())

        wrong_scheme = make_release_payload(
            tag="v0.2.2",
            sums_url="http://github.com/adil-adysh/git-explain/releases/download/v0.2.2/SHA256SUMS.txt",
        )
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.validate_release(wrong_scheme)
        self.assertIn("url", str(ctx.exception).lower())

    def test_checksum_missing_duplicate_mismatch(self):
        """Reject missing archive record, duplicate records, malformed hashes, or payload mismatch."""
        filename = "git-explain-v0.2.2-windows-x86_64.zip"
        dummy_zip_content = b"fake-zip-binary-content-v0.2.2"
        correct_hash = hashlib.sha256(dummy_zip_content).hexdigest()

        # Missing
        sums_missing = f"1111111111111111111111111111111111111111111111111111111111111111  other-file.zip\n"
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.parse_checksum(sums_missing, filename)
        self.assertIn("missing", str(ctx.exception).lower())

        # Duplicate
        sums_duplicate = (
            f"{correct_hash}  {filename}\n"
            f"{correct_hash}  {filename}\n"
        )
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.parse_checksum(sums_duplicate, filename)
        self.assertIn("duplicate", str(ctx.exception).lower())

        # Malformed hash length or characters
        sums_malformed = f"not-a-valid-sha256-hash  {filename}\n"
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.parse_checksum(sums_malformed, filename)
        self.assertIn("malformed", str(ctx.exception).lower())

        # Hash mismatch against downloaded archive content
        sums_valid = f"{correct_hash}  {filename}\n"
        parsed_hash = update_git_explain.parse_checksum(sums_valid, filename)
        self.assertEqual(parsed_hash, correct_hash)

        mismatched_content = b"corrupted-or-tampered-content"
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.verify_archive_hash(mismatched_content, parsed_hash)
        self.assertIn("mismatch", str(ctx.exception).lower())

    def test_expected_executable_shim_and_dependency(self):
        """Manifest must maintain bin shim and git dependency."""
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest.get("depends"), "git")
        self.assertIn(manifest.get("bin"), ["git-explain.exe", ["git-explain.exe"]])

    def test_no_downgrade(self):
        """Reject updates where release version is lower than current manifest version."""
        # Current manifest is 0.2.1, release is 0.2.0
        downgrade_release = make_release_payload(tag="v0.2.0")
        with self.assertRaises(ValueError) as ctx:
            update_git_explain.check_version_order("0.2.1", "0.2.0")
        self.assertIn("downgrade", str(ctx.exception).lower())

    def test_idempotent_sameversion(self):
        """Updating to the same version performs no write and returns clean status."""
        same_release = make_release_payload(tag="v0.2.1")
        zip_bytes = b"git-explain-0.2.1-zip-bytes"
        zip_hash = hashlib.sha256(zip_bytes).hexdigest()
        sums_content = f"{zip_hash}  git-explain-v0.2.1-windows-x86_64.zip\n"

        def mock_fetch(url):
            if "releases/latest" in url:
                return json.dumps(same_release).encode("utf-8")
            if "SHA256SUMS.txt" in url:
                return sums_content.encode("utf-8")
            if url.endswith(".zip"):
                return zip_bytes
            raise ValueError(f"Unexpected url {url}")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        updated = update_git_explain.run_update(
            manifest_path=self.manifest_path,
            fetcher=mock_fetch,
        )
        self.assertFalse(updated, "Same version should not perform update")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)

    def test_preservation_on_write_replace_failure(self):
        """If atomic write/replace fails, the original manifest is preserved and temp file cleaned up."""
        tag = "v0.2.2"
        zip_bytes = b"valid-zip-binary-data"
        expected_hash = hashlib.sha256(zip_bytes).hexdigest()
        sums_content = f"{expected_hash}  git-explain-{tag}-windows-x86_64.zip\n"
        release = make_release_payload(tag=tag)

        def mock_fetch(url):
            if "releases/latest" in url:
                return json.dumps(release).encode("utf-8")
            if "SHA256SUMS.txt" in url:
                return sums_content.encode("utf-8")
            if url.endswith(".zip"):
                return zip_bytes
            raise ValueError(f"Unexpected url {url}")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        manifest_dir = os.path.dirname(self.manifest_path)
        before_files = set(os.listdir(manifest_dir))

        with patch("os.replace", side_effect=OSError("Mock disk failure")):
            with self.assertRaises(OSError):
                update_git_explain.run_update(
                    manifest_path=self.manifest_path,
                    fetcher=mock_fetch,
                )

        # Manifest untouched
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)

        # Temp files cleaned up
        after_files = set(os.listdir(manifest_dir))
        self.assertEqual(before_files, after_files)

    def test_preservation_existing_manifest_on_failure(self):
        """If verification fails (e.g., checksum mismatch), original manifest is untouched."""
        release = make_release_payload(tag="v0.2.2")
        sums_content = "1111111111111111111111111111111111111111111111111111111111111111  git-explain-v0.2.2-windows-x86_64.zip\n"
        tampered_zip = b"mismatched-content"

        def mock_fetch(url):
            if "releases/latest" in url:
                return json.dumps(release).encode("utf-8")
            if "SHA256SUMS.txt" in url:
                return sums_content.encode("utf-8")
            if url.endswith(".zip"):
                return tampered_zip
            raise ValueError(f"Unexpected url {url}")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        with self.assertRaises(ValueError):
            update_git_explain.run_update(
                manifest_path=self.manifest_path,
                fetcher=mock_fetch,
            )

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)

    def test_successful_update(self):
        """Valid release v0.2.2 updates version, url, and hash cleanly."""
        tag = "v0.2.2"
        zip_bytes = b"new-release-v0.2.2-archive-bytes"
        expected_hash = hashlib.sha256(zip_bytes).hexdigest()
        sums_content = f"{expected_hash}  git-explain-{tag}-windows-x86_64.zip\n"
        release = make_release_payload(tag=tag)

        def mock_fetch(url):
            if "releases/latest" in url:
                return json.dumps(release).encode("utf-8")
            if "SHA256SUMS.txt" in url:
                return sums_content.encode("utf-8")
            if url.endswith(".zip"):
                return zip_bytes
            raise ValueError(f"Unexpected url {url}")

        updated = update_git_explain.run_update(
            manifest_path=self.manifest_path,
            fetcher=mock_fetch,
        )
        self.assertTrue(updated)

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["version"], "0.2.2")
        self.assertEqual(
            data["architecture"]["64bit"]["url"],
            f"https://github.com/adil-adysh/git-explain/releases/download/{tag}/git-explain-{tag}-windows-x86_64.zip",
        )
        self.assertEqual(data["architecture"]["64bit"]["hash"], expected_hash)
        # Preserved fields
        self.assertEqual(data["homepage"], "https://github.com/adil-adysh/git-explain")
        self.assertEqual(data["license"], "Apache-2.0")
        self.assertEqual(data["description"], "Accessible local explanations for changed source code")
        self.assertEqual(data["depends"], "git")
        self.assertEqual(data["bin"], "git-explain.exe")
        self.assertEqual(data["checkver"], "github")

    def test_check_mode(self):
        """Check mode reports whether an update is available without writing to disk."""
        tag = "v0.2.2"
        release = make_release_payload(tag=tag)

        def mock_fetch(url):
            if "releases/latest" in url:
                return json.dumps(release).encode("utf-8")
            raise ValueError("Should not fetch assets in check mode")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        status = update_git_explain.check_update_available(
            manifest_path=self.manifest_path,
            fetcher=mock_fetch,
        )
        self.assertTrue(status.update_available)
        self.assertEqual(status.current_version, "0.2.1")
        self.assertEqual(status.latest_version, "0.2.2")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)

    def test_refuse_unrelated_files(self):
        """Updater must strictly refuse to operate on non-git-explain.json manifests."""
        hn_path = os.path.join(self.temp_dir.name, "hn.json")
        with open(hn_path, "w", encoding="utf-8") as f:
            f.write("{}")

        with self.assertRaises(ValueError) as ctx:
            update_git_explain.run_update(hn_path)
        self.assertIn("git-explain.json", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            update_git_explain.check_update_available(hn_path)
        self.assertIn("git-explain.json", str(ctx.exception))

    def test_cli_check_flag(self):
        """Test CLI main() with --check and --output."""
        tag = "v0.2.2"
        release = make_release_payload(tag=tag)

        def mock_fetch(url):
            return json.dumps(release).encode("utf-8")

        test_args = ["update_git_explain.py", "--output", self.manifest_path, "--check"]
        with patch.object(sys, "argv", test_args):
            with patch("update_git_explain.default_fetcher", side_effect=mock_fetch):
                with self.assertRaises(SystemExit) as cm:
                    update_git_explain.main()
                self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
