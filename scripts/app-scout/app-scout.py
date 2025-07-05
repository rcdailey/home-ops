#!/usr/bin/env python3
"""
App Scout - Kubernetes Application Discovery Tool

This script provides a two-phase approach for migrating Docker Compose services to Kubernetes:

1. DISCOVERY PHASE: `discover [app_name]`
   - Searches kubesearch.dev database for real-world Helm chart and app-template usage
   - Returns unified landscape view showing both dedicated charts and app-template deployments
   - Includes repository metadata, file availability, and exact file paths
   - Designed for AI consumption to make informed migration decisions

2. INSPECTION PHASE: `inspect [app_name] --repo [repo_name] --files [file_types]`
   - Fetches specific configuration files using exact paths from discovery phase
   - Uses GitHub CLI to retrieve file contents from real-world deployments
   - Supports targeted file fetching (helmrelease, values, configmaps, secrets, etc.)

The script uses the kubesearch.dev database (scraped from public GitOps repositories) and
GitHub's GraphQL API for file operations. No API tokens needed - relies on user's `gh auth` setup.

Key design principles:
- High-performance GraphQL batching for API efficiency
- Exact file paths eliminate guesswork
- Structured JSON output for AI processing
- Clean separation between discovery and inspection phases
"""

import sqlite3
import sys
import argparse
import subprocess
import json
import os
import re
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import urllib.request
import urllib.error
import shutil
import httpx


class AppMigrationDiscovery:
    """
    Main class for discovering Kubernetes deployment patterns for Docker Compose migration.

    Provides two core functions:
    1. discover_app_landscape() - Complete landscape analysis for an application
    2. inspect_app_config() - Targeted file retrieval from specific repositories
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            script_dir = Path(__file__).parent
            db_path = script_dir / "repos.db"
        self.db_path = db_path

        # Download database if it doesn't exist or is older than a week
        if not os.path.exists(db_path) or self._is_database_stale(db_path):
            self._download_database()

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access

        # Initialize GitHub API client with hybrid auth
        self.github_token = self._get_github_token()
        self.http_client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            },
            timeout=30.0
        )

    async def discover_app_landscape(self, app_name: str, sample_count: int = 3) -> Dict:
        """
        Phase 1: Discover complete landscape for an application.

        Returns comprehensive view of both dedicated Helm charts and app-template usage
        patterns for the specified application. Includes repository metadata, file
        availability with exact paths, and usage statistics.

        Args:
            app_name: Name of application to discover (e.g., "authentik", "plex")
            sample_count: Number of top repositories to analyze per category

        Returns:
            Dict with structure:
            {
                "[app_name]": {
                    "dedicated_charts": {
                        "usage_count": int,
                        "chart_sources": [repo_names],
                        "repositories": [repo_details_with_file_paths]
                    },
                    "app_template": {
                        "usage_count": int,
                        "repositories": [repo_details_with_file_paths]
                    }
                }
            }
        """
        print(f"Discovering landscape for '{app_name}'...", file=sys.stderr)

        result = {app_name: {"dedicated_charts": {}, "app_template": {}}}

        # Discover dedicated chart usage
        dedicated_data = await self._discover_dedicated_charts(app_name, sample_count)
        result[app_name]["dedicated_charts"] = dedicated_data

        # Discover app-template usage
        app_template_data = await self._discover_app_template_usage(app_name, sample_count)
        result[app_name]["app_template"] = app_template_data

        return result

    async def inspect_app_config(
        self, app_name: str, repo_name: str, file_types: List[str]
    ) -> Dict:
        """
        Phase 2: Inspect specific configuration files from a repository.

        Fetches exact files using paths discovered in Phase 1. No searching or
        guessing - uses precise file locations identified during discovery.

        Args:
            app_name: Application name for context
            repo_name: Repository name (e.g., "angelnu/k8s-gitops")
            file_types: List of file types to fetch (e.g., ["helmrelease", "values"])

        Returns:
            Dict with file contents:
            {
                "app_name": str,
                "repo_name": str,
                "files": {
                    "helmrelease": "file_content...",
                    "values": "file_content..."
                }
            }
        """
        print(
            f"Inspecting {repo_name} for {app_name} files: {', '.join(file_types)}",
            file=sys.stderr,
        )

        # First, get file paths for this specific repo/app combination
        file_paths = await self._get_file_paths_for_repo(app_name, repo_name)

        if not file_paths:
            return {
                "error": f"No file paths found for {app_name} in repository {repo_name}. Run discover first."
            }

        # Batch fetch requested files using GraphQL
        file_contents = await self._gh_get_file_contents_batch(repo_name, file_paths, file_types)
        return {"app_name": app_name, "repo_name": repo_name, "files": file_contents}

    async def _discover_dedicated_charts(self, app_name: str, sample_count: int) -> Dict:
        """
        Discover dedicated Helm chart usage for an application.

        Searches for charts where chart_name exactly matches the app_name.
        For top repositories, discovers available files and their exact paths.
        """
        # Query for dedicated charts (exact match on chart_name)
        query = """
        SELECT DISTINCT
            r.repo_name,
            r.stars,
            fhr.release_name,
            fhr.chart_name,
            fhr.chart_version,
            fhr.namespace,
            fhr.url,
            fhr.helm_repo_name
        FROM flux_helm_release fhr
        JOIN repo r ON fhr.repo_name = r.repo_name
        WHERE fhr.chart_name = ?
        ORDER BY r.stars DESC, fhr.chart_name
        LIMIT ?
        """

        cursor = self.conn.execute(
            query, (app_name, sample_count * 2)
        )  # Get extra in case some fail
        rows = cursor.fetchall()

        if not rows:
            return {"usage_count": 0, "chart_sources": [], "repositories": []}

        # Get total usage count
        count_query = """
        SELECT COUNT(*) as total FROM flux_helm_release WHERE chart_name = ?
        """
        count_cursor = self.conn.execute(count_query, (app_name,))
        total_count = count_cursor.fetchone()["total"]

        # Get unique chart sources
        sources_query = """
        SELECT DISTINCT helm_repo_name FROM flux_helm_release WHERE chart_name = ?
        """
        sources_cursor = self.conn.execute(sources_query, (app_name,))
        chart_sources = [row["helm_repo_name"] for row in sources_cursor.fetchall()]

        # Process top repositories with batch GitHub API calls
        repositories = []
        limited_rows = rows[:sample_count]

        # Extract repo names for batch metadata fetching
        repo_names = [row["repo_name"] for row in limited_rows]
        batch_metadata = await self._gh_get_repo_metadata_batch(repo_names)

        for row in limited_rows:
            repo_data = dict(row)

            # Add batch-fetched metadata
            if repo_data["repo_name"] in batch_metadata:
                repo_data.update(batch_metadata[repo_data["repo_name"]])

            # Discover available files and their paths
            file_paths = await self._discover_file_paths(
                repo_data["repo_name"], repo_data["url"], "dedicated"
            )
            repo_data["available_files"] = file_paths

            repositories.append(repo_data)

        return {
            "usage_count": total_count,
            "chart_sources": chart_sources,
            "repositories": repositories,
        }

    async def _discover_app_template_usage(self, app_name: str, sample_count: int) -> Dict:
        """
        Discover app-template usage for an application.

        Searches for app-template deployments where release_name contains the app_name.
        Uses fuzzy matching to catch variations in naming conventions.
        """
        # Query for app-template usage (fuzzy match on release_name)
        query = """
        SELECT DISTINCT
            r.repo_name,
            r.stars,
            fhr.release_name,
            fhr.chart_name,
            fhr.chart_version,
            fhr.namespace,
            fhr.url,
            fhr.helm_repo_name
        FROM flux_helm_release fhr
        JOIN repo r ON fhr.repo_name = r.repo_name
        WHERE fhr.chart_name = 'app-template'
        AND fhr.release_name LIKE ?
        ORDER BY r.stars DESC, fhr.release_name
        LIMIT ?
        """

        cursor = self.conn.execute(query, (f"%{app_name}%", sample_count * 2))
        rows = cursor.fetchall()

        if not rows:
            return {"usage_count": 0, "repositories": []}

        # Get total usage count
        count_query = """
        SELECT COUNT(*) as total FROM flux_helm_release
        WHERE chart_name = 'app-template' AND release_name LIKE ?
        """
        count_cursor = self.conn.execute(count_query, (f"%{app_name}%",))
        total_count = count_cursor.fetchone()["total"]

        # Process top repositories with batch GitHub API calls
        repositories = []
        limited_rows = rows[:sample_count]

        # Extract repo names for batch metadata fetching
        repo_names = [row["repo_name"] for row in limited_rows]
        batch_metadata = await self._gh_get_repo_metadata_batch(repo_names)

        for row in limited_rows:
            repo_data = dict(row)

            # Add batch-fetched metadata
            if repo_data["repo_name"] in batch_metadata:
                repo_data.update(batch_metadata[repo_data["repo_name"]])

            # Discover available files and their paths
            file_paths = await self._discover_file_paths(
                repo_data["repo_name"], repo_data["url"], "app-template"
            )
            repo_data["available_files"] = file_paths

            repositories.append(repo_data)

        return {"usage_count": total_count, "repositories": repositories}

    async def _discover_file_paths(
        self, repo_name: str, helm_release_url: str, deployment_type: str
    ) -> Dict[str, str]:
        """
        Discover available configuration files and their exact paths in a repository.

        Explores the directory structure around the known HelmRelease location to find
        related configuration files (values, configmaps, secrets, etc.).

        Returns:
            Dict mapping file types to exact repository paths:
            {"helmrelease": "path/to/file.yaml", "values": "path/to/values.yaml"}
        """
        # Extract the directory path from the HelmRelease URL
        # URL format: https://github.com/user/repo/blob/branch/path/to/file.yaml
        url_pattern = r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)"
        match = re.match(url_pattern, helm_release_url)

        if not match:
            print(
                f"Warning: Could not parse GitHub URL: {helm_release_url}",
                file=sys.stderr,
            )
            return {}

        user, repo, branch, file_path = match.groups()

        # The file_path includes the filename, get just the directory
        dir_path = "/".join(file_path.split("/")[:-1])

        # File type patterns to search for
        file_patterns = {
            "helmrelease": ["helmrelease.yaml", "helm-release.yaml", "hr.yaml"],
            "values": ["values.yaml", "values.yml"],
            "configmaps": ["configmap.yaml", "configmaps.yaml", "config.yaml"],
            "secrets": ["secret.yaml", "secrets.yaml"],
            "pvcs": ["pvc.yaml", "pvcs.yaml", "storage.yaml", "volume.yaml"],
            "ingress": ["ingress.yaml", "route.yaml", "httproute.yaml"],
        }

        discovered_files = {}

        # Start with the known HelmRelease file
        discovered_files["helmrelease"] = file_path

        # Search for other files in the same directory and parent directories
        search_paths = [dir_path]
        if "/" in dir_path:
            parent_path = "/".join(dir_path.split("/")[:-1])
            search_paths.append(parent_path)

        for search_path in search_paths:
            files_in_dir = await self._gh_list_files(repo_name, search_path)

            for file_type, patterns in file_patterns.items():
                if file_type in discovered_files:  # Already found
                    continue

                for filename in files_in_dir:
                    if any(pattern in filename.lower() for pattern in patterns):
                        full_path = (
                            f"{search_path}/{filename}" if search_path else filename
                        )
                        discovered_files[file_type] = full_path
                        break

        return discovered_files

    async def _get_file_paths_for_repo(self, app_name: str, repo_name: str) -> Dict[str, str]:
        """
        Retrieve cached file paths for a specific app/repo combination.

        This method looks up file paths that were discovered during the discovery phase.
        In a production version, this would query a cache or re-run discovery.
        For now, it re-runs a targeted discovery to get the paths.
        """
        # Find the HelmRelease URL for this specific repo/app combination
        queries = [
            # Try dedicated chart first
            """
            SELECT fhr.url FROM flux_helm_release fhr
            JOIN repo r ON fhr.repo_name = r.repo_name
            WHERE r.repo_name = ? AND fhr.chart_name = ?
            LIMIT 1
            """,
            # Try app-template
            """
            SELECT fhr.url FROM flux_helm_release fhr
            JOIN repo r ON fhr.repo_name = r.repo_name
            WHERE r.repo_name = ? AND fhr.chart_name = 'app-template' AND fhr.release_name LIKE ?
            LIMIT 1
            """,
        ]

        helm_release_url = None
        deployment_type = None

        # Try dedicated chart
        cursor = self.conn.execute(queries[0], (repo_name, app_name))
        result = cursor.fetchone()
        if result:
            helm_release_url = result["url"]
            deployment_type = "dedicated"
        else:
            # Try app-template
            cursor = self.conn.execute(queries[1], (repo_name, f"%{app_name}%"))
            result = cursor.fetchone()
            if result:
                helm_release_url = result["url"]
                deployment_type = "app-template"

        if not helm_release_url:
            return {}

        return await self._discover_file_paths(repo_name, helm_release_url, deployment_type)


    async def _gh_list_files(self, repo_name: str, path: str) -> List[str]:
        """
        List files in a repository directory using GitHub API.

        Returns list of filenames in the specified directory path.
        """
        try:
            owner, name = repo_name.split('/')
            response = await self.http_client.get(
                f"https://api.github.com/repos/{repo_name}/contents/{path}",
                timeout=30.0
            )

            if response.status_code == 200:
                contents = response.json()
                if isinstance(contents, list):
                    return [item["name"] for item in contents if item["type"] == "file"]
        except Exception as e:
            print(
                f"Warning: Could not list files in {repo_name}/{path}: {e}",
                file=sys.stderr,
            )

        return []


    def _is_database_stale(self, db_path):
        """Check if the database file is older than a week"""
        try:
            file_mtime = os.path.getmtime(db_path)
            file_age = datetime.now().timestamp() - file_mtime
            week_in_seconds = 7 * 24 * 60 * 60

            if file_age > week_in_seconds:
                print(
                    f"Database is {file_age / (24 * 60 * 60):.1f} days old, refreshing...",
                    file=sys.stderr,
                )
                return True
            return False
        except OSError:
            return True

    def _download_database(self):
        """Download the kubesearch database if it doesn't exist"""
        # Try to download from recent releases (try up to 7 days back)
        for days_back in range(1, 8):
            date_to_try = datetime.now() - timedelta(days=days_back)
            tag_name = date_to_try.strftime("%Y-%m-%d")

            db_url = f"https://github.com/whazor/k8s-at-home-search/releases/download/{tag_name}/repos.db"
            print(
                f"Trying to download database from release {tag_name}...",
                file=sys.stderr,
            )

            try:
                with urllib.request.urlopen(db_url) as response:
                    with open(self.db_path, "wb") as f:
                        shutil.copyfileobj(response, f)

                print(
                    f"Database downloaded successfully from release {tag_name}",
                    file=sys.stderr,
                )
                return

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                else:
                    print(
                        f"HTTP error {e.code} for release {tag_name}: {e}",
                        file=sys.stderr,
                    )
                    continue
            except Exception as e:
                print(
                    f"Error downloading from release {tag_name}: {e}", file=sys.stderr
                )
                continue

        print(
            "ERROR: Could not download database from any recent release.",
            file=sys.stderr,
        )
        print(
            "Please check your internet connection or try again later.", file=sys.stderr
        )
        sys.exit(1)

    def _get_github_token(self) -> str:
        """Get GitHub token using hybrid approach"""
        try:
            # Check if gh cli is installed and authenticated
            result = subprocess.run(["gh", "--version"], capture_output=True, text=True)
            if result.returncode != 0:
                print("Error: GitHub CLI (gh) is not installed.", file=sys.stderr)
                print("Install it from: https://cli.github.com/", file=sys.stderr)
                sys.exit(1)

            # Get token from gh CLI
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                print("Error: GitHub CLI is not authenticated.", file=sys.stderr)
                print("Run: gh auth login", file=sys.stderr)
                sys.exit(1)

        except FileNotFoundError:
            print("Error: GitHub CLI (gh) is not installed.", file=sys.stderr)
            print("Install it from: https://cli.github.com/", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error getting GitHub token: {e}", file=sys.stderr)
            sys.exit(1)

    async def _github_graphql_request(self, query: str) -> dict:
        """Make GraphQL request to GitHub API"""
        try:
            response = await self.http_client.post(
                "https://api.github.com/graphql",
                json={"query": query},
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"GraphQL request failed: {e}", file=sys.stderr)
            return {"errors": [str(e)]}

    async def _gh_get_repo_metadata_batch(self, repos: List[str]) -> Dict[str, Dict]:
        """Batch fetch repository metadata using GraphQL"""
        if not repos:
            return {}

        # Build GraphQL query for multiple repos
        repo_queries = []
        for i, repo in enumerate(repos):
            owner, name = repo.split('/')
            repo_queries.append(f'''
                repo{i}: repository(owner: "{owner}", name: "{name}") {{
                    stargazerCount
                    pushedAt
                    description
                    name
                    owner {{ login }}
                }}
            ''')

        query = f"query {{ {' '.join(repo_queries)} }}"

        data = await self._github_graphql_request(query)

        results = {}
        if "data" in data:
            for i, repo in enumerate(repos):
                repo_data = data["data"].get(f"repo{i}")
                if repo_data:
                    results[repo] = {
                        "stars": repo_data.get("stargazerCount", 0),
                        "last_commit": repo_data.get("pushedAt", ""),
                        "description": repo_data.get("description", "")
                    }
                else:
                    results[repo] = {"stars": 0, "last_commit": "", "description": ""}

        return results

    async def _gh_get_file_contents_batch(self, repo_name: str, file_paths: Dict[str, str], file_types: List[str]) -> Dict[str, str]:
        """Batch fetch file contents using GraphQL"""
        if not file_paths:
            return {file_type: f"Error: No file paths available" for file_type in file_types}

        # Build GraphQL query for multiple files
        file_queries = []
        requested_files = []

        for file_type in file_types:
            if file_type in file_paths:
                file_path = file_paths[file_type]
                file_queries.append(f'''
                    {file_type}: object(expression: "HEAD:{file_path}") {{
                        ... on Blob {{
                            text
                        }}
                    }}
                ''')
                requested_files.append(file_type)

        if not file_queries:
            return {file_type: f"Error: File type '{file_type}' not available in this repository" for file_type in file_types}

        owner, name = repo_name.split('/')
        query = f'''
        query {{
            repository(owner: "{owner}", name: "{name}") {{
                {' '.join(file_queries)}
            }}
        }}
        '''

        data = await self._github_graphql_request(query)

        results = {}
        if "data" in data and "repository" in data["data"]:
            repo_data = data["data"]["repository"]
            for file_type in file_types:
                if file_type in requested_files:
                    file_data = repo_data.get(file_type)
                    if file_data and file_data.get("text"):
                        results[file_type] = file_data["text"]
                    else:
                        results[file_type] = f"Error: Could not fetch {file_paths.get(file_type, 'unknown path')}"
                else:
                    results[file_type] = f"Error: File type '{file_type}' not available in this repository"
        else:
            for file_type in file_types:
                results[file_type] = f"Error: Could not access repository {repo_name}"

        return results

    async def close(self):
        """Close database and HTTP client connections"""
        self.conn.close()
        await self.http_client.aclose()


async def main():
    """
    Main CLI interface for the App Migration Discovery tool.

    Supports two primary commands:
    - discover [app_name]: Get complete landscape view
    - inspect [app_name] --repo [repo] --files [types]: Fetch specific files
    """
    parser = argparse.ArgumentParser(
        description="Discover Kubernetes deployment patterns for Docker Compose migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover all deployment patterns for authentik
  python3 app-scout.py discover authentik

  # Inspect specific files from a repository
  python3 app-scout.py inspect authentik --repo angelnu/k8s-gitops --files helmrelease,values

  # Get larger sample size for discovery
  python3 app-scout.py discover plex --sample-count 5
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Discover command
    discover_parser = subparsers.add_parser(
        "discover", help="Discover deployment landscape for an application"
    )
    discover_parser.add_argument(
        "app_name", help="Application name to discover (e.g., authentik, plex)"
    )
    discover_parser.add_argument(
        "--sample-count",
        type=int,
        default=3,
        help="Number of repositories to analyze per category (default: 3)",
    )

    # Inspect command
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect specific configuration files"
    )
    inspect_parser.add_argument("app_name", help="Application name")
    inspect_parser.add_argument(
        "--repo", required=True, help="Repository name (e.g., angelnu/k8s-gitops)"
    )
    inspect_parser.add_argument(
        "--files",
        required=True,
        help="Comma-separated file types (helmrelease,values,configmaps,secrets,pvcs,ingress)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    discovery = AppMigrationDiscovery()

    try:
        if args.command == "discover":
            result = await discovery.discover_app_landscape(args.app_name, args.sample_count)
            print(json.dumps(result, indent=2))

        elif args.command == "inspect":
            file_types = [f.strip() for f in args.files.split(",")]
            result = await discovery.inspect_app_config(args.app_name, args.repo, file_types)
            print(json.dumps(result, indent=2))

    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await discovery.close()


if __name__ == "__main__":
    asyncio.run(main())
