#!/usr/bin/env python3
"""
App Scout - Kubernetes Application Discovery Tool

This script provides application discovery for migrating Docker Compose services to Kubernetes:

DISCOVERY PHASE: `discover [app_name]`
- Searches kubesearch.dev database for real-world Helm chart and app-template usage
- Returns unified landscape view showing both dedicated charts and app-template deployments
- Includes repository metadata and usage statistics
- Designed for AI consumption to make informed migration decisions

After discovery, use octocode MCP tools for file inspection:
- githubViewRepoStructure: Explore repository structure
- githubSearchCode: Search for specific patterns
- githubGetFileContent: Retrieve file contents

The script uses the kubesearch.dev database (scraped from public GitOps repositories).
No API tokens needed - relies on user's `gh auth` setup for optional operations.

Key design principles:
- High-performance GraphQL batching for API efficiency
- Structured JSON output for AI processing
- Simple, focused discovery without file fetching complexity
"""

import sqlite3
import sys
import argparse
import subprocess
import json
import os
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timedelta
import urllib.request
import urllib.error
import shutil
import httpx


class AppMigrationDiscovery:
    """
    Main class for discovering Kubernetes deployment patterns for Docker Compose migration.

    Provides discovery function: discover_app_landscape() - Complete landscape analysis
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
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=30.0,
        )

    async def discover_app_landscape(
        self, app_name: str, sample_count: int = 3
    ) -> Dict:
        """
        Discover complete landscape for an application.

        Returns comprehensive view of both dedicated Helm charts and app-template usage
        patterns for the specified application. Includes repository metadata and usage statistics.

        Args:
            app_name: Name of application to discover (e.g., "sonarr", "plex")
            sample_count: Number of top repositories to analyze per category

        Returns:
            Dict with structure:
            {
                "[app_name]": {
                    "dedicated_charts": {
                        "usage_count": int,
                        "chart_sources": [repo_names],
                        "repositories": [repo_details]
                    },
                    "app_template": {
                        "usage_count": int,
                        "repositories": [repo_details]
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
        app_template_data = await self._discover_app_template_usage(
            app_name, sample_count
        )
        result[app_name]["app_template"] = app_template_data

        # Print guidance for next steps
        print(
            "\nNOTE: To inspect configuration files from discovered repositories, use octocode MCP tools:",
            file=sys.stderr,
        )
        print(
            "  - githubViewRepoStructure: Explore repository structure", file=sys.stderr
        )
        print("  - githubSearchCode: Search for specific patterns", file=sys.stderr)
        print("  - githubGetFileContent: Retrieve file contents\n", file=sys.stderr)

        return result

    async def _discover_dedicated_charts(
        self, app_name: str, sample_count: int
    ) -> Dict:
        """
        Discover dedicated Helm chart usage for an application.

        Searches for charts where chart_name exactly matches the app_name.
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
        seen_repos = set()
        limited_rows = rows[
            : sample_count * 2
        ]  # Get extra to account for deduplication

        # Extract repo names for batch metadata fetching
        repo_names = [row["repo_name"] for row in limited_rows]
        batch_metadata = await self._gh_get_repo_metadata_batch(repo_names)

        for row in limited_rows:
            repo_data = dict(row)

            # Skip if we've already processed this repository
            if repo_data["repo_name"] in seen_repos:
                continue
            seen_repos.add(repo_data["repo_name"])

            # Stop if we have enough unique repositories
            if len(repositories) >= sample_count:
                break

            # Add batch-fetched metadata
            if repo_data["repo_name"] in batch_metadata:
                repo_data.update(batch_metadata[repo_data["repo_name"]])

            repositories.append(repo_data)

        return {
            "usage_count": total_count,
            "chart_sources": chart_sources,
            "repositories": repositories,
        }

    async def _discover_app_template_usage(
        self, app_name: str, sample_count: int
    ) -> Dict:
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
        seen_repos = set()
        limited_rows = rows[
            : sample_count * 2
        ]  # Get extra to account for deduplication

        # Extract repo names for batch metadata fetching
        repo_names = [row["repo_name"] for row in limited_rows]
        batch_metadata = await self._gh_get_repo_metadata_batch(repo_names)

        for row in limited_rows:
            repo_data = dict(row)

            # Skip if we've already processed this repository
            if repo_data["repo_name"] in seen_repos:
                continue
            seen_repos.add(repo_data["repo_name"])

            # Stop if we have enough unique repositories
            if len(repositories) >= sample_count:
                break

            # Add batch-fetched metadata
            if repo_data["repo_name"] in batch_metadata:
                repo_data.update(batch_metadata[repo_data["repo_name"]])

            repositories.append(repo_data)

        return {"usage_count": total_count, "repositories": repositories}

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
                "https://api.github.com/graphql", json={"query": query}, timeout=60.0
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
            owner, name = repo.split("/")
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
                        "description": repo_data.get("description", ""),
                    }
                else:
                    results[repo] = {"stars": 0, "last_commit": "", "description": ""}

        return results

    async def correlate_applications(
        self, app_names: List[str], sample_count: int = 10
    ) -> Dict:
        """
        Find repositories that contain multiple specific applications deployed together.

        This is useful for understanding architectural patterns where apps are deployed
        in combination (e.g., blocky + external-dns, sonarr + prowlarr).

        Args:
            app_names: List of application names to find together
            sample_count: Number of repositories to return

        Returns:
            Dict with structure:
            {
                "apps": ["app1", "app2"],
                "repositories": [
                    {
                        "repo_name": "user/repo",
                        "stars": 123,
                        "description": "repo description",
                        "apps_found": {
                            "app1": {"chart_name": "...", "type": "dedicated|app-template"},
                            "app2": {"chart_name": "...", "type": "dedicated|app-template"}
                        }
                    }
                ]
            }
        """
        print(
            f"Finding repositories with all apps: {', '.join(app_names)}",
            file=sys.stderr,
        )

        # Build SQL query to find repos containing ALL specified apps
        placeholders = ",".join(["?" for _ in app_names])
        query = f"""
        SELECT repo_name, COUNT(DISTINCT release_name) as app_count
        FROM flux_helm_release
        WHERE release_name IN ({placeholders})
        GROUP BY repo_name
        HAVING app_count = ?
        ORDER BY (SELECT stars FROM repo WHERE repo.repo_name = flux_helm_release.repo_name) DESC
        LIMIT ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, app_names + [len(app_names), sample_count])
        matching_repos = [row[0] for row in cursor.fetchall()]

        if not matching_repos:
            return {"apps": app_names, "repositories": []}

        # Get detailed information for each matching repository
        repos_info = await self._gh_get_repo_metadata_batch(matching_repos)

        results = []
        for repo_name in matching_repos:
            # Get app details for this repo
            apps_found = {}
            for app_name in app_names:
                cursor.execute(
                    """
                    SELECT release_name, chart_name, helm_repo_name, namespace
                    FROM flux_helm_release
                    WHERE repo_name = ? AND release_name = ?
                """,
                    (repo_name, app_name),
                )

                row = cursor.fetchone()
                if row:
                    release_name, chart_name, helm_repo_name, namespace = row
                    # Determine if it's app-template or dedicated chart
                    chart_type = (
                        "app-template" if chart_name == "app-template" else "dedicated"
                    )

                    apps_found[app_name] = {
                        "release_name": release_name,
                        "chart_name": chart_name,
                        "helm_repo_name": helm_repo_name,
                        "namespace": namespace,
                        "type": chart_type,
                    }

            repo_info = repos_info.get(repo_name, {})

            results.append(
                {
                    "repo_name": repo_name,
                    "stars": repo_info.get("stars", 0),
                    "description": repo_info.get("description"),
                    "last_commit": repo_info.get("last_commit"),
                    "apps_found": apps_found,
                }
            )

        return {
            "apps": app_names,
            "total_repositories": len(results),
            "repositories": results,
        }

    async def close(self):
        """Close database and HTTP client connections"""
        self.conn.close()
        await self.http_client.aclose()


async def main():
    """
    Main CLI interface for the App Migration Discovery tool.

    Supports two primary commands:
    - discover [app_name]: Get complete landscape view
    - correlate [app_names...]: Find repos with multiple apps
    """
    parser = argparse.ArgumentParser(
        description="Discover Kubernetes deployment patterns for Docker Compose migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover all deployment patterns for sonarr
  python3 app-scout.py discover sonarr

  # Find repositories that have both blocky and external-dns
  python3 app-scout.py correlate blocky external-dns

  # Get larger sample size for discovery
  python3 app-scout.py discover plex --sample-count 5

After discovery, use octocode MCP tools to inspect files:
  - githubViewRepoStructure: Explore repository structure
  - githubSearchCode: Search for specific patterns
  - githubGetFileContent: Retrieve file contents
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Discover command
    discover_parser = subparsers.add_parser(
        "discover", help="Discover deployment landscape for an application"
    )
    discover_parser.add_argument(
        "app_name", help="Application name to discover (e.g., sonarr, plex)"
    )
    discover_parser.add_argument(
        "--sample-count",
        type=int,
        default=3,
        help="Number of repositories to analyze per category (default: 3)",
    )

    # Correlate command
    correlate_parser = subparsers.add_parser(
        "correlate", help="Find repositories containing multiple applications"
    )
    correlate_parser.add_argument(
        "app_names",
        nargs="+",
        help="Application names to find together (e.g., blocky external-dns)",
    )
    correlate_parser.add_argument(
        "--sample-count",
        type=int,
        default=10,
        help="Number of repositories to return (default: 10)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    discovery = AppMigrationDiscovery()

    try:
        if args.command == "discover":
            result = await discovery.discover_app_landscape(
                args.app_name, args.sample_count
            )
            print(json.dumps(result, indent=2))

        elif args.command == "correlate":
            result = await discovery.correlate_applications(
                args.app_names, args.sample_count
            )
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
    import asyncio

    asyncio.run(main())
