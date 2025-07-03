#!/usr/bin/env python3
"""
Helm Chart Search Tool for Migration Project
Searches kubesearch.dev data for real-world Helm chart usage examples
"""

import sqlite3
import sys
import argparse
from typing import List, Dict, Optional
import json
import os
import re
from pathlib import Path
import urllib.request
import urllib.error
import shutil
from datetime import datetime, timedelta

class HelmChartSearch:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Use relative path from script location
            script_dir = Path(__file__).parent
            db_path = script_dir / "repos.db"
        self.db_path = db_path
        
        # Download database if it doesn't exist or is older than a week
        if not os.path.exists(db_path) or self._is_database_stale(db_path):
            self._download_database()
        
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access

    def search_chart(self, chart_name: str, limit: int = 10) -> List[Dict]:
        """Search for Helm chart deployments by chart name"""
        query = """
        SELECT DISTINCT
            r.repo_name,
            r.stars,
            fhr.release_name,
            fhr.chart_name,
            fhr.chart_version,
            fhr.namespace,
            fhr.url,
            fhr.helm_repo_name,
            fhr.hajimari_icon
        FROM flux_helm_release fhr
        JOIN repo r ON fhr.repo_name = r.repo_name
        WHERE fhr.chart_name LIKE ?
        ORDER BY r.stars DESC, fhr.chart_name
        LIMIT ?
        """
        
        cursor = self.conn.execute(query, (f"%{chart_name}%", limit))
        return [dict(row) for row in cursor.fetchall()]

    def get_chart_stats(self, chart_name: str) -> Dict:
        """Get statistics for a chart"""
        query = """
        SELECT 
            COUNT(*) as total_deployments,
            COUNT(DISTINCT repo_name) as unique_repos,
            chart_name,
            GROUP_CONCAT(DISTINCT chart_version) as versions,
            GROUP_CONCAT(DISTINCT helm_repo_name) as repo_sources
        FROM flux_helm_release 
        WHERE chart_name LIKE ?
        GROUP BY chart_name
        """
        
        cursor = self.conn.execute(query, (f"%{chart_name}%",))
        row = cursor.fetchone()
        return dict(row) if row else {}

    def list_app_template_charts(self, limit: int = 50) -> List[Dict]:
        """List charts using bjw-s app-template"""
        query = """
        SELECT DISTINCT
            fhr.chart_name,
            COUNT(*) as usage_count,
            GROUP_CONCAT(DISTINCT r.repo_name) as example_repos,
            MAX(r.stars) as max_stars
        FROM flux_helm_release fhr
        JOIN repo r ON fhr.repo_name = r.repo_name
        WHERE fhr.helm_repo_name LIKE '%app-template%' 
           OR fhr.helm_repo_name LIKE '%bjw-s%'
        GROUP BY fhr.chart_name
        ORDER BY usage_count DESC, max_stars DESC
        LIMIT ?
        """
        
        cursor = self.conn.execute(query, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_migration_services_data(self, services: List[str]) -> Dict[str, List[Dict]]:
        """Get chart data for multiple services from migration plan"""
        results = {}
        for service in services:
            results[service] = self.search_chart(service, limit=5)
        return results

    def fetch_chart_config(self, repo_name: str, chart_name: str, fetch_type: str = "both") -> Dict:
        """Fetch HelmRelease and/or values files for a specific chart"""
        # Find the chart in database
        query = """
        SELECT url, release_name FROM flux_helm_release 
        WHERE repo_name = ? AND chart_name = ?
        LIMIT 1
        """
        cursor = self.conn.execute(query, (repo_name, chart_name))
        result = cursor.fetchone()
        
        if not result:
            return {"error": f"Chart '{chart_name}' not found in repository '{repo_name}'"}
        
        url = result['url']
        release_name = result['release_name']
        
        # Convert GitHub blob URL to raw URL
        raw_url = self._convert_to_raw_url(url)
        if not raw_url:
            return {"error": f"Could not convert URL to raw format: {url}"}
        
        output = {
            "repo_name": repo_name,
            "chart_name": chart_name,
            "release_name": release_name,
            "helm_release_url": url,
            "files": {}
        }
        
        # Fetch HelmRelease if requested
        if fetch_type in ["helm", "both"]:
            helm_content = self._fetch_url_content(raw_url)
            if helm_content:
                output["files"]["helmrelease.yaml"] = helm_content
            else:
                output["files"]["helmrelease.yaml"] = f"Error: Could not fetch {raw_url}"
        
        # Look for companion values files if requested
        if fetch_type in ["values", "both"]:
            values_files = self._find_values_files(raw_url)
            for values_file, content in values_files.items():
                output["files"][values_file] = content
        
        return output
    
    def _convert_to_raw_url(self, github_url: str) -> Optional[str]:
        """Convert GitHub blob URL to raw URL"""
        # Pattern: https://github.com/user/repo/blob/branch/path/file.yaml
        # Target:  https://raw.githubusercontent.com/user/repo/branch/path/file.yaml
        pattern = r'https://github\.com/([^/]+)/([^/]+)/blob/(.+)'
        match = re.match(pattern, github_url)
        
        if match:
            user, repo, path = match.groups()
            return f"https://raw.githubusercontent.com/{user}/{repo}/{path}"
        return None
    
    def _fetch_url_content(self, url: str) -> Optional[str]:
        """Fetch content from URL"""
        try:
            with urllib.request.urlopen(url) as response:
                return response.read().decode('utf-8')
        except urllib.error.URLError as e:
            return None
        except Exception as e:
            return None
    
    def _find_values_files(self, helm_release_url: str) -> Dict[str, str]:
        """Find and fetch companion values files"""
        values_files = {}
        
        # Extract directory path from HelmRelease URL
        base_url = '/'.join(helm_release_url.split('/')[:-1])
        
        # Common values file patterns
        patterns = [
            "values.yaml",
            "values.yml", 
            f"values-{self._extract_chart_name(helm_release_url)}.yaml",
            "plex-values.yaml",  # Chart-specific naming
            "config.yaml"
        ]
        
        for pattern in patterns:
            values_url = f"{base_url}/{pattern}"
            content = self._fetch_url_content(values_url)
            if content:
                values_files[pattern] = content
        
        # Also check parent directory for values
        parent_url = '/'.join(base_url.split('/')[:-1])
        for pattern in ["values.yaml", "values.yml"]:
            values_url = f"{parent_url}/{pattern}"
            content = self._fetch_url_content(values_url)
            if content:
                values_files[f"../{pattern}"] = content
        
        return values_files
    
    def _extract_chart_name(self, url: str) -> str:
        """Extract likely chart name from URL path"""
        parts = url.split('/')
        for part in reversed(parts):
            if part and not part.endswith('.yaml'):
                return part
        return "unknown"

    def _is_database_stale(self, db_path):
        """Check if the database file is older than a week"""
        try:
            file_mtime = os.path.getmtime(db_path)
            file_age = datetime.now().timestamp() - file_mtime
            week_in_seconds = 7 * 24 * 60 * 60
            
            if file_age > week_in_seconds:
                print(f"Database is {file_age / (24 * 60 * 60):.1f} days old, refreshing...")
                return True
            return False
        except OSError:
            # If we can't get file stats, consider it stale
            return True

    def _download_database(self):
        """Download the kubesearch database if it doesn't exist"""
        # Calculate yesterday's date (releases are typically from the previous day)
        yesterday = datetime.now() - timedelta(days=1)
        release_tag = yesterday.strftime("%Y-%m-%d")
        
        # Try yesterday's release first, then try a few days back
        for days_back in range(1, 8):  # Try up to 7 days back
            date_to_try = datetime.now() - timedelta(days=days_back)
            tag_name = date_to_try.strftime("%Y-%m-%d")
            
            db_url = f"https://github.com/whazor/k8s-at-home-search/releases/download/{tag_name}/repos.db"
            print(f"Trying to download database from release {tag_name}...")
            
            try:
                # Download the database
                with urllib.request.urlopen(db_url) as response:
                    with open(self.db_path, 'wb') as f:
                        shutil.copyfileobj(response, f)
                
                print(f"Database downloaded successfully from release {tag_name} to {self.db_path}")
                return
                
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    print(f"Release {tag_name} not found, trying older release...")
                    continue
                else:
                    print(f"HTTP error {e.code} for release {tag_name}: {e}")
                    continue
            except Exception as e:
                print(f"Error downloading from release {tag_name}: {e}")
                continue
        
        # If we get here, all recent releases failed
        print("ERROR: Could not download database from any recent release.")
        print("Please check your internet connection or try again later.")
        sys.exit(1)

    def close(self):
        self.conn.close()

def main():
    parser = argparse.ArgumentParser(description="Search Helm charts for migration planning")
    parser.add_argument("command", choices=["search", "stats", "app-template", "migration-batch", "fetch"])
    parser.add_argument("chart_name", nargs="?", help="Chart name to search for")
    parser.add_argument("--limit", type=int, default=10, help="Limit results")
    parser.add_argument("--repo", help="Repository name for fetch command (e.g., gandazgul/k8s-infrastructure)")
    parser.add_argument("--type", choices=["helm", "values", "both"], default="both", 
                       help="What to fetch: helm (HelmRelease only), values (values files only), both (default)")
    
    args = parser.parse_args()
    
    searcher = HelmChartSearch()
    
    try:
        if args.command == "search":
            if not args.chart_name:
                print("Error: chart_name required for search command")
                sys.exit(1)
            results = searcher.search_chart(args.chart_name, args.limit)
            
        elif args.command == "stats":
            if not args.chart_name:
                print("Error: chart_name required for stats command")
                sys.exit(1)
            results = searcher.get_chart_stats(args.chart_name)
            
        elif args.command == "app-template":
            results = searcher.list_app_template_charts(args.limit)
            
        elif args.command == "migration-batch":
            # Services from your migration plan
            media_services = ["plex", "sonarr", "radarr", "qbittorrent", "sabnzbd", "prowlarr", "bazarr", "overseerr", "tautulli"]
            auth_services = ["authentik", "adguard"]
            productivity_services = ["immich", "bookstack", "filerun"]
            utility_services = ["uptime-kuma", "homer"]
            
            all_services = media_services + auth_services + productivity_services + utility_services
            results = searcher.get_migration_services_data(all_services)
            
        elif args.command == "fetch":
            if not args.chart_name or not args.repo:
                print("Error: Both chart_name and --repo required for fetch command")
                sys.exit(1)
            results = searcher.fetch_chart_config(args.repo, args.chart_name, args.type)
        
        if args.command == "fetch":
            # Fetch command keeps human-readable output
            if "error" in results:
                print(f"Error: {results['error']}")
            else:
                print(f"\n=== Configuration for {results['chart_name']} from {results['repo_name']} ===")
                print(f"Release Name: {results['release_name']}")
                print(f"Source URL: {results['helm_release_url']}")
                print("\n" + "="*80)
                
                for filename, content in results['files'].items():
                    print(f"\n--- {filename} ---")
                    if content.startswith("Error:"):
                        print(content)
                    else:
                        print(content)
        else:
            # All other commands output JSON
            print(json.dumps(results, indent=2))
                        
    finally:
        searcher.close()

if __name__ == "__main__":
    main()