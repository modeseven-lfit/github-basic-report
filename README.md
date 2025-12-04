# GitHub Organization Report Generator

A tool to analyze and report on all repositories within a GitHub
organization.

## Requirements

- Python 3.7+
- Git CLI installed and available in PATH
- GitHub Personal Access Token with repo read permissions
- Python packages: requests (install via pip)

## Installation

```bash
pip install requests
```

## Usage

```bash
python report.py --token YOUR_GITHUB_TOKEN --org ORGANIZATION_NAME \
  [--skip-clone] [--sort alphabetical|commits] \
  [--exclude-users USER1,USER2,...]
```

### Options

- `--token`: GitHub Personal Access Token (required)
- `--org`: GitHub organization name (required)
- `--skip-clone`: Skip cloning, use existing repos in clone/ directory
- `--sort`: Sort order - 'alphabetical' (default) or 'commits'
- `--exclude-users`: Comma-separated usernames to exclude from stats

### Examples

Basic usage:
```bash
python report.py --token ghp_xxxxxxxxxxxx --org os-climate
```

Sort by commit activity and exclude specific users:
```bash
python report.py --token ghp_xxxxxxxxxxxx --org os-climate \
  --sort commits --exclude-users ModeSevenIndustrialSolutions
```

Use existing clones without re-cloning:
```bash
python report.py --token ghp_xxxxxxxxxxxx --org os-climate \
  --skip-clone
```

## Output

The script generates `GITHUB_REPORT.md` containing:

- Repository metadata (name, description, languages)
- Archive status
- User commit counts (1, 3, and 12 month periods)
- Top 3 contributors in the past 12 months

Automation bot commits (dependabot, renovate, etc.) are excluded
from statistics.

## Notes

- The script is idempotent: re-running clears and regenerates all data
- Repositories are cloned to `./clone/` directory (auto-managed)
- Processing time depends on the number and size of repositories