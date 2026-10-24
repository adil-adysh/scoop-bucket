#!/usr/bin/env python3
"""Scoop manifest updater for git-explain.

Interacts with the public GitHub releases API for adil-adysh/git-explain,
verifies release metadata, download URLs, SHA256 checksums, and updates
bucket/git-explain.json.
"""

from collections import namedtuple
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request

OWNER = "adil-adysh"
REPO = "git-explain"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"

SEMVER_COMPONENT = r"(?:0|[1-9][0-9]*)"
TAG_PATTERN = re.compile(
    rf"^v{SEMVER_COMPONENT}\.{SEMVER_COMPONENT}\.{SEMVER_COMPONENT}$",
    flags=re.ASCII,
)
VERSION_PATTERN = re.compile(
    rf"^{SEMVER_COMPONENT}\.{SEMVER_COMPONENT}\.{SEMVER_COMPONENT}$",
    flags=re.ASCII,
)

UpdateStatus = namedtuple(
    "UpdateStatus", ["update_available", "current_version", "latest_version"]
)


def default_fetcher(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "git-explain-scoop-updater/1.0",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def validate_release(release: dict) -> dict:
    if release.get("draft") is True:
        raise ValueError("Release is marked as draft; cannot update to draft releases")
    if release.get("prerelease") is True:
        raise ValueError("Release is marked as prerelease; cannot update to prerelease")

    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not re.fullmatch(TAG_PATTERN, tag):
        raise ValueError(
            f"Release tag '{tag}' is not a plain stable semantic version (expected vX.Y.Z without leading zeros or non-ASCII characters)"
        )

    version = tag[1:]
    expected_zip_name = f"git-explain-{tag}-windows-x86_64.zip"
    expected_sums_name = "SHA256SUMS.txt"

    expected_zip_url = f"https://github.com/{OWNER}/{REPO}/releases/download/{tag}/{expected_zip_name}"
    expected_sums_url = f"https://github.com/{OWNER}/{REPO}/releases/download/{tag}/{expected_sums_name}"

    assets = release.get("assets", [])
    zip_asset = None
    sums_asset = None
    for asset in assets:
        if asset.get("name") == expected_zip_name:
            zip_asset = asset
        elif asset.get("name") == expected_sums_name:
            sums_asset = asset

    if not zip_asset:
        raise ValueError(f"Missing required release archive asset: {expected_zip_name}")
    if not sums_asset:
        raise ValueError(f"Missing required checksums asset: {expected_sums_name}")

    zip_url = zip_asset.get("browser_download_url", "")
    if zip_url != expected_zip_url:
        raise ValueError(f"Disallowed archive download URL: {zip_url} (expected {expected_zip_url})")

    sums_url = sums_asset.get("browser_download_url", "")
    if sums_url != expected_sums_url:
        raise ValueError(f"Disallowed checksums download URL: {sums_url} (expected {expected_sums_url})")

    return {
        "tag": tag,
        "version": version,
        "zip_name": expected_zip_name,
        "zip_url": zip_url,
        "sums_url": sums_url,
    }


def parse_checksum(sums_text: str, filename: str) -> str:
    found_matches = []
    for line_num, line in enumerate(sums_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Malformed checksum line at line {line_num}: {line}")
        h, fn = parts[0], parts[1].lstrip("*").strip()
        if len(h) != 64 or not all(c in "0123456789abcdefABCDEF" for c in h):
            raise ValueError(f"Malformed sha256 checksum at line {line_num}: {h}")
        if fn == filename:
            found_matches.append(h.lower())

    if len(found_matches) == 0:
        raise ValueError(f"Missing checksum record for archive: {filename}")
    if len(found_matches) > 1:
        raise ValueError(f"Duplicate checksum records found for archive: {filename}")

    return found_matches[0]


def verify_archive_hash(archive_bytes: bytes, expected_hash: str) -> str:
    actual_hash = hashlib.sha256(archive_bytes).hexdigest().lower()
    if actual_hash != expected_hash.lower():
        raise ValueError(
            f"Checksum mismatch: expected {expected_hash.lower()}, got {actual_hash}"
        )
    return actual_hash


def parse_semver(v: str) -> tuple:
    if not isinstance(v, str) or not re.fullmatch(VERSION_PATTERN, v):
        raise ValueError(
            f"Invalid plain semver version string: '{v}' (expected X.Y.Z without leading zeros)"
        )
    return tuple(int(x) for x in v.split("."))


def check_version_order(current_version: str, new_version: str) -> bool:
    c_ver = parse_semver(current_version)
    n_ver = parse_semver(new_version)
    if n_ver < c_ver:
        raise ValueError(
            f"Release version {new_version} is a downgrade from current version {current_version}"
        )
    return n_ver > c_ver


def _check_manifest_path(manifest_path: str):
    base = os.path.basename(manifest_path)
    if base != "git-explain.json":
        raise ValueError(
            f"Updater only supports modifying git-explain.json, refusing to operate on {manifest_path}"
        )


def check_update_available(manifest_path: str, fetcher=None) -> UpdateStatus:
    _check_manifest_path(manifest_path)
    if fetcher is None:
        fetcher = default_fetcher

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    current_version = data.get("version")
    if not current_version:
        raise ValueError("Current manifest lacks a version string")

    release_payload = json.loads(fetcher(LATEST_RELEASE_API_URL).decode("utf-8"))
    validated = validate_release(release_payload)
    latest_version = validated["version"]

    is_newer = check_version_order(current_version, latest_version)
    return UpdateStatus(
        update_available=is_newer,
        current_version=current_version,
        latest_version=latest_version,
    )


def run_update(manifest_path: str, fetcher=None) -> bool:
    _check_manifest_path(manifest_path)
    if fetcher is None:
        fetcher = default_fetcher

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    current_version = data.get("version")
    if not current_version:
        raise ValueError("Current manifest lacks a version string")

    release_payload = json.loads(fetcher(LATEST_RELEASE_API_URL).decode("utf-8"))
    validated = validate_release(release_payload)
    latest_version = validated["version"]

    check_version_order(current_version, latest_version)
    if latest_version == current_version:
        return False

    sums_data = fetcher(validated["sums_url"]).decode("utf-8")
    expected_hash = parse_checksum(sums_data, validated["zip_name"])

    archive_bytes = fetcher(validated["zip_url"])
    verify_archive_hash(archive_bytes, expected_hash)

    # All validations and integrity checks passed, now update manifest data
    data["version"] = latest_version
    if "architecture" not in data:
        data["architecture"] = {}
    if "64bit" not in data["architecture"]:
        data["architecture"]["64bit"] = {}

    data["architecture"]["64bit"]["url"] = validated["zip_url"]
    data["architecture"]["64bit"]["hash"] = expected_hash

    # Atomic write using same-directory temporary file and os.replace
    output_content = json.dumps(data, indent=4) + "\n"
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=manifest_dir,
        prefix="git-explain-tmp-",
        delete=False,
    )
    temp_path = temp_file.name
    try:
        temp_file.write(output_content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()
        os.replace(temp_path, manifest_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Update git-explain Scoop manifest to latest stable GitHub release"
    )
    parser.add_argument(
        "--output",
        default=os.path.join("bucket", "git-explain.json"),
        help="Path to manifest file (default: bucket/git-explain.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether an update is available without writing manifest",
    )
    args = parser.parse_args()

    manifest_path = os.path.abspath(args.output)
    if not os.path.isfile(manifest_path):
        print(f"Error: Manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.check:
            status = check_update_available(manifest_path)
            if status.update_available:
                print(
                    f"Update available: {status.current_version} -> {status.latest_version}"
                )
            else:
                print(f"Manifest is up to date at version {status.current_version}")
            sys.exit(0)
        else:
            updated = run_update(manifest_path)
            if updated:
                print(f"Manifest successfully updated at {manifest_path}")
            else:
                print("Manifest is already up to date; no changes written")
            sys.exit(0)
    except Exception as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
