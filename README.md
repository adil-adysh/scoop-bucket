# scoop-bucket

Personal Scoop bucket for CLI tools published by [@adil-adysh](https://github.com/adil-adysh), including `git-explain` and `hashnode-cli`.

## Add the Bucket

```powershell
scoop bucket add adil-adysh https://github.com/adil-adysh/scoop-bucket
```

## Available Packages

### git-explain

Accessible local explanations for changed source code.

```powershell
# Install git-explain
scoop install adil-adysh/git-explain

# Update git-explain
scoop update git-explain
```

Once installed, Scoop creates a shim for `git-explain.exe`, allowing you to run:

```powershell
git-explain
# or as a git subcommand
git explain
```

### hashnode-cli (`hn`)

Unofficial Hashnode CLI - Write and manage blogs from your terminal.

```powershell
scoop install adil-adysh/hn
```

## Maintainer Automation

The manifests in this bucket are managed and kept up to date automatically:
- **`git-explain` Updater**: A scheduled GitHub Actions workflow runs daily (and can be triggered manually via `workflow_dispatch`) to detect new stable GitHub releases (`vX.Y.Z`).
- **Integrity & Verification**: Before updating `bucket/git-explain.json`, the automation validates release metadata (ignoring drafts and prereleases), verifies allowlisted archive URLs, checks SHA256 checksums from `SHA256SUMS.txt`, downloads and verifies the archive digest, and performs an atomic update to prevent downgrades or broken manifests.
- **Continuous Integration**: Every push, pull request, and manual dispatch runs:
  - Automated test suites (`scripts/test_update_git_explain.py`) verifying manifest metadata, strict semver parsing, error handling, failure preservation, and workflow linting via `actionlint`.
  - An automated disposable Windows runner job (`windows-latest`) that bootstraps Scoop in an isolated runner temporary directory, registers the local bucket checkout, installs `adil-adysh/git-explain` (honoring the Git dependency), verifies both `git-explain -h` and `git explain -h` execution against the generated shim, and confirms clean uninstallation and shim removal.
