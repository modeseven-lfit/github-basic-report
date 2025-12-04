#!/usr/bin/env python3
"""
GitHub Organization Repository Report Generator

Generates a comprehensive markdown report for all repositories in a GitHub
organization, including commit statistics and contributor information.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import requests


# Automation tools to filter from commit counts
AUTOMATION_BOTS = {
    "pre-commit-ci[bot]",
    "dependabot[bot]",
    "renovate[bot]",
    "github-actions[bot]",
    "allcontributors[bot]",
    "mergify[bot]",
    "codecov[bot]",
    "snyk-bot",
    "greenkeeper[bot]",
    "pyup-bot",
}

# Global set of excluded usernames
EXCLUDED_USERS = set()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate repository report for a GitHub organization"
    )
    parser.add_argument(
        "--token",
        required=True,
        help="GitHub personal access token"
    )
    parser.add_argument(
        "--org",
        required=True,
        help="GitHub organization name"
    )
    parser.add_argument(
        "--skip-clone",
        action="store_true",
        help="Skip cloning, use existing repositories in clone/ directory"
    )
    parser.add_argument(
        "--sort",
        choices=["alphabetical", "commits"],
        default="alphabetical",
        help="Sort order for repositories (default: alphabetical)"
    )
    parser.add_argument(
        "--exclude-users",
        type=str,
        default="",
        help="Comma-separated list of usernames to exclude from statistics"
    )
    return parser.parse_args()


def get_github_headers(token: str) -> Dict[str, str]:
    """Return headers for GitHub API requests."""
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def fetch_all_repositories(org: str, headers: Dict[str, str]) -> List[Dict]:
    """Fetch all repositories from a GitHub organization."""
    repos = []
    page = 1
    per_page = 100

    print(f"Fetching repositories from {org}...")

    while True:
        url = f"https://api.github.com/orgs/{org}/repos"
        params = {"page": page, "per_page": per_page, "type": "all"}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            print(f"Error fetching repositories: {response.status_code}")
            print(response.text)
            sys.exit(1)

        page_repos = response.json()
        if not page_repos:
            break

        repos.extend(page_repos)
        print(f"  Fetched page {page} ({len(page_repos)} repos)")
        page += 1

    print(f"Total repositories found: {len(repos)}")
    return repos


def get_repository_languages(
    org: str, repo_name: str, headers: Dict[str, str]
) -> str:
    """Get primary language(s) for a repository."""
    url = f"https://api.github.com/repos/{org}/{repo_name}/languages"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return "Unknown"

    languages = response.json()
    if not languages:
        return "None"

    # Return top 3 languages by bytes
    sorted_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)
    top_langs = [lang for lang, _ in sorted_langs[:3]]
    return ", ".join(top_langs)


def clone_repository(repo_url: str, clone_path: Path) -> bool:
    """Clone a repository with minimal depth but full log."""
    try:
        # Clone with no depth limit to get full history
        subprocess.run(
            ["git", "clone", "--no-checkout", repo_url, str(clone_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Error cloning: {e.stderr}")
        return False


def get_commit_stats(
    repo_path: Path, months: int, exclude_users: set = None
) -> Tuple[int, List[Tuple[str, str, int]]]:
    """
    Get commit statistics for a repository.
    Returns (commit_count, top_contributors)
    exclude_users: set of usernames/emails to exclude from statistics
    """
    if exclude_users is None:
        exclude_users = set()
    since_date = datetime.now() - timedelta(days=months * 30)
    since_str = since_date.strftime("%Y-%m-%d")

    try:
        # Get commits with author name and email
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                f"--since={since_str}",
                "--format=%an|%ae",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        commits = result.stdout.strip().split("\n")
        if not commits or commits == [""]:
            return 0, []

        # Filter out automation bots
        user_commits = []
        author_counter = Counter()

        for commit in commits:
            if not commit:
                continue

            parts = commit.split("|")
            if len(parts) != 2:
                continue

            author_name, author_email = parts
            author_name = author_name.strip()
            author_email = author_email.strip()

            # Skip automation bots
            is_bot = False
            for bot in AUTOMATION_BOTS:
                if bot in author_name or bot in author_email:
                    is_bot = True
                    break

            # Skip excluded users
            is_excluded = False
            if exclude_users:
                # Normalize author name by removing spaces for comparison
                author_name_normalized = author_name.lower().replace(" ", "")
                author_email_lower = author_email.lower()
                
                for excluded_user in exclude_users:
                    excluded_user_normalized = excluded_user.lower().replace(" ", "")
                    excluded_user_lower = excluded_user.lower()
                    
                    # Check if excluded user matches name (with/without spaces) or email
                    if (excluded_user_normalized in author_name_normalized or
                        excluded_user_lower in author_email_lower or
                        author_name_normalized in excluded_user_normalized):
                        is_excluded = True
                        break

            if not is_bot and not is_excluded:
                user_commits.append(commit)
                author_key = f"{author_name}|{author_email}"
                author_counter[author_key] += 1

        # Get top contributors
        top_contributors = []
        for author_key, count in author_counter.most_common(3):
            author_name, author_email = author_key.split("|")
            top_contributors.append((author_name, author_email, count))

        return len(user_commits), top_contributors

    except subprocess.CalledProcessError:
        return 0, []


def get_github_username(email: str, headers: Dict[str, str]) -> str:
    """Attempt to get GitHub username from email."""
    # First try to search for users by email
    url = f"https://api.github.com/search/users"
    params = {"q": f"{email} in:email"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("total_count", 0) > 0:
                return data["items"][0]["login"]
    except Exception:
        pass
    
    # Fallback: return email prefix
    return email.split("@")[0] if "@" in email else email


def format_contributors(
    contributors: List[Tuple[str, str, int]], headers: Dict[str, str]
) -> str:
    """Format top contributors for markdown table cell."""
    if not contributors:
        return "None"

    lines = []
    labels = ["most", "second most", "third most"]

    for idx, (name, email, count) in enumerate(contributors):
        username = get_github_username(email, headers)
        label = labels[idx] if idx < len(labels) else "commits"
        lines.append(f"{name}/{username}/{email} ({label} commits)")

    return "<br>".join(lines)


def generate_report(
    org: str,
    token: str,
    repos: List[Dict],
    clone_base_path: Path,
    headers: Dict[str, str],
    skip_clone: bool,
    exclude_users: set,
) -> Tuple[str, List[Tuple[Dict, int]]]:
    """
    Generate the markdown report content.
    Returns (report_content, repos_with_commit_counts)
    """
    repos_with_stats = []
    lines = [
        f"# GitHub Organization Report: {org}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total Repositories: {len(repos)}",
        "",
        "| Repository | Description | Project Type | Archived | "
        "Commits (1M) | Commits (3M) | Commits (12M) | "
        "Top Contributors (12M) |",
        "|------------|-------------|--------------|----------|"
        "--------------|--------------|---------------|"
        "------------------------|",
    ]

    for idx, repo in enumerate(repos, 1):
        repo_name = repo["name"]
        description = (repo.get("description") or "").replace("|", "\\|")
        archived = "✅" if repo.get("archived", False) else "❌"

        print(f"\n[{idx}/{len(repos)}] Processing: {repo_name}")

        # Get languages
        print("  Getting languages...")
        languages = get_repository_languages(org, repo_name, headers)

        # Clone repository or check if it exists
        repo_path = clone_base_path / repo_name
        
        if skip_clone:
            if not repo_path.exists():
                print(f"  Repository not found in clone directory, skipping...")
                lines.append(
                    f"| {repo_name} | {description} | {languages} | "
                    f"{archived} | N/A | N/A | N/A | Not cloned |"
                )
                repos_with_stats.append((repo, 0))
                continue
            else:
                print(f"  Using existing repository at {repo_path}...")
        else:
            print(f"  Cloning to {repo_path}...")
            if not clone_repository(repo["clone_url"], repo_path):
                lines.append(
                    f"| {repo_name} | {description} | {languages} | "
                    f"{archived} | Error | Error | Error | Error |"
                )
                repos_with_stats.append((repo, 0))
                continue

        # Get commit statistics
        print("  Analyzing commits (1 month)...")
        commits_1m, _ = get_commit_stats(repo_path, 1, exclude_users)

        print("  Analyzing commits (3 months)...")
        commits_3m, _ = get_commit_stats(repo_path, 3, exclude_users)

        print("  Analyzing commits (12 months)...")
        commits_12m, top_contributors = get_commit_stats(repo_path, 12, exclude_users)

        print("  Formatting contributors...")
        contributors_str = format_contributors(top_contributors, headers)

        # Store repo with stats for sorting
        repos_with_stats.append((repo, commits_12m))

        # Add row to table
        lines.append(
            f"| {repo_name} | {description} | {languages} | {archived} | "
            f"{commits_1m} | {commits_3m} | {commits_12m} | "
            f"{contributors_str} |"
        )

    return "\n".join(lines), repos_with_stats


def main():
    """Main execution function."""
    args = parse_arguments()

    # Setup paths
    script_dir = Path(__file__).parent
    clone_dir = script_dir / "clone"
    report_file = script_dir / "GITHUB_REPORT.md"

    # Prepare headers
    headers = get_github_headers(args.token)

    # Parse excluded users
    exclude_users = set()
    if args.exclude_users:
        exclude_users = {u.strip() for u in args.exclude_users.split(",") if u.strip()}
        print(f"\nExcluding users from statistics: {', '.join(exclude_users)}")

    # Clean and recreate clone directory (unless --skip-clone)
    if args.skip_clone:
        print("\nUsing existing clone directory (--skip-clone flag set)...")
        if not clone_dir.exists():
            print(f"  Warning: Clone directory does not exist: {clone_dir}")
            print(f"  Creating directory...")
            clone_dir.mkdir(parents=True)
    else:
        print("\nPreparing clone directory...")
        if clone_dir.exists():
            print(f"  Removing existing directory: {clone_dir}")
            shutil.rmtree(clone_dir)
        clone_dir.mkdir(parents=True)
        print(f"  Created fresh directory: {clone_dir}")

    # Fetch all repositories
    repos = fetch_all_repositories(args.org, headers)

    if not repos:
        print("No repositories found!")
        sys.exit(1)

    # Sort repositories based on sort flag
    if args.sort == "alphabetical":
        print("\nSorting repositories alphabetically...")
        repos = sorted(repos, key=lambda r: r["name"].lower())
    else:
        print("\nRepositories will be sorted by commit count after analysis...")

    # Generate report
    print("\n" + "=" * 70)
    print("GENERATING REPORT")
    print("=" * 70)

    report_content, repos_with_stats = generate_report(
        args.org, args.token, repos, clone_dir, headers, args.skip_clone, exclude_users
    )

    # If sorting by commits, regenerate the report with sorted repos
    if args.sort == "commits":
        print("\nSorting repositories by commit count (12 months)...")
        repos_with_stats.sort(key=lambda x: x[1], reverse=True)
        sorted_repos = [repo for repo, _ in repos_with_stats]
        
        # Regenerate report with sorted repos
        report_content, _ = generate_report(
            args.org, args.token, sorted_repos, clone_dir, headers, True, exclude_users
        )

    # Write report
    print(f"\nWriting report to: {report_file}")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n" + "=" * 70)
    print("REPORT GENERATION COMPLETE")
    print("=" * 70)
    print(f"Report saved to: {report_file}")


if __name__ == "__main__":
    main()
