#!/usr/bin/env python3
"""Discover Kubernetes deployment patterns indexed by kubesearch.dev."""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

DATABASE_MAX_AGE = timedelta(days=7)
RELEASES_URL = (
    "https://api.github.com/repos/whazor/k8s-at-home-search/releases?per_page=10"
)
REQUIRED_COLUMNS = {
    "flux_helm_release": {
        "release_name",
        "chart_name",
        "chart_version",
        "namespace",
        "repo_name",
        "url",
        "timestamp",
        "helm_repo_name",
    },
    "repo": {"repo_name", "branch", "stars"},
}


def default_cache_dir() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "app-scout"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


@lru_cache(maxsize=128)
def app_name_pattern(app_name: str) -> re.Pattern[str]:
    escaped = re.escape(app_name.casefold())
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def release_matches_app(release_name: str | None, app_name: str) -> int:
    if not release_name:
        return 0
    return int(app_name_pattern(app_name).search(release_name.casefold()) is not None)


def manifest_path(url: str, source_ref: str | None) -> str | None:
    if not source_ref:
        return None

    path = unquote(urlparse(url).path)
    for marker in (f"/blob/{source_ref}/", f"/-/blob/{source_ref}/"):
        if marker in path:
            return path.split(marker, maxsplit=1)[1]
    return None


class DatabaseCache:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or default_cache_dir()
        self.database_path = self.cache_dir / "repos.db"
        self.metadata_path = self.cache_dir / "repos.json"

    def ensure(self) -> tuple[Path, dict]:
        valid_cache = self._is_valid(self.database_path)
        if valid_cache and not self._is_stale(self.database_path):
            return self.database_path, self._metadata(stale=False)

        try:
            release = self._refresh()
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            sqlite3.DatabaseError,
            urllib.error.URLError,
        ) as error:
            if not valid_cache:
                raise RuntimeError(
                    f"could not obtain a valid database: {error}"
                ) from error

            print(
                f"Warning: database refresh failed; using the existing cache: {error}",
                file=sys.stderr,
            )
            return self.database_path, self._metadata(stale=True)

        return self.database_path, self._metadata(stale=False, release=release)

    def _refresh(self) -> dict:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        release = self._current_release()
        temporary_path = self._download(release["download_url"])

        try:
            if not self._is_valid(temporary_path):
                raise ValueError("downloaded asset is not a valid kubesearch database")
            os.replace(temporary_path, self.database_path)
        finally:
            temporary_path.unlink(missing_ok=True)

        metadata = {
            "release": release["release"],
            "published_at": release["published_at"],
            "source": release["download_url"],
        }
        try:
            self._write_metadata(metadata)
        except OSError as error:
            print(
                f"Warning: could not save database metadata: {error}", file=sys.stderr
            )
        return metadata

    def _current_release(self) -> dict:
        request = urllib.request.Request(
            RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "app-scout",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            releases = json.load(response)

        if not isinstance(releases, list):
            raise TypeError("GitHub returned an invalid releases response")

        for release in releases:
            if not isinstance(release, dict):
                continue
            for asset in release.get("assets", []):
                if isinstance(asset, dict) and asset.get("name") == "repos.db":
                    return {
                        "release": release.get("tag_name"),
                        "published_at": release.get("published_at"),
                        "download_url": asset["browser_download_url"],
                    }
        raise ValueError("recent releases do not contain repos.db")

    def _download(self, url: str) -> Path:
        request = urllib.request.Request(url, headers={"User-Agent": "app-scout"})
        descriptor, name = tempfile.mkstemp(
            prefix="repos.", suffix=".tmp", dir=self.cache_dir
        )
        os.close(descriptor)
        temporary_path = Path(name)

        try:
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                temporary_path.open("wb") as destination,
            ):
                shutil.copyfileobj(response, destination)
        except (OSError, urllib.error.URLError):
            temporary_path.unlink(missing_ok=True)
            raise
        return temporary_path

    def _write_metadata(self, metadata: dict) -> None:
        descriptor, name = tempfile.mkstemp(
            prefix="repos.", suffix=".json", dir=self.cache_dir
        )
        temporary_path = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(metadata, file)
                file.write("\n")
            os.replace(temporary_path, self.metadata_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _metadata(self, *, stale: bool, release: dict | None = None) -> dict:
        metadata = release or self._read_metadata()
        cached_at = datetime.fromtimestamp(
            self.database_path.stat().st_mtime, tz=UTC
        ).isoformat()
        return {**metadata, "cached_at": cached_at, "stale": stale}

    def _read_metadata(self) -> dict:
        try:
            with self.metadata_path.open(encoding="utf-8") as file:
                metadata = json.load(file)
            if isinstance(metadata, dict):
                return metadata
        except (OSError, json.JSONDecodeError):
            pass
        return {"release": None, "published_at": None, "source": None}

    @staticmethod
    def _is_stale(path: Path) -> bool:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return datetime.now(tz=UTC) - modified_at > DATABASE_MAX_AGE

    @staticmethod
    def _is_valid(path: Path) -> bool:
        if not path.is_file():
            return False

        try:
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    return False
                for table, required_columns in REQUIRED_COLUMNS.items():
                    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
                    columns = {row[1] for row in rows}
                    if not required_columns <= columns:
                        return False
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError):
            return False
        return True


class AppScout:
    def __init__(self, database_path: Path):
        self.connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function(
            "app_name_matches", 2, release_matches_app, deterministic=True
        )

    def close(self) -> None:
        self.connection.close()

    def database_details(self, cache_metadata: dict) -> dict:
        row = self.connection.execute(
            "SELECT MAX(CAST(timestamp AS INTEGER)) FROM flux_helm_release"
        ).fetchone()
        latest_record_at = None
        if row[0]:
            latest_record_at = datetime.fromtimestamp(row[0], tz=UTC).isoformat()
        return {**cache_metadata, "latest_record_at": latest_record_at}

    def discover(self, app_name: str, sample_count: int) -> dict:
        return {
            "dedicated_charts": self._dedicated_charts(app_name, sample_count),
            "app_template": self._app_template(app_name, sample_count),
        }

    def _dedicated_charts(self, app_name: str, sample_count: int) -> dict:
        predicate = "lower(f.chart_name) = lower(?)"
        counts = self._counts(predicate, (app_name,))
        rows = self._representative_repositories(predicate, (app_name,), sample_count)
        source_rows = self.connection.execute(
            """
            SELECT DISTINCT helm_repo_name
            FROM flux_helm_release
            WHERE lower(chart_name) = lower(?) AND helm_repo_name != ''
            ORDER BY lower(helm_repo_name)
            """,
            (app_name,),
        )
        return {
            **counts,
            "chart_sources": [row[0] for row in source_rows],
            "repositories": [self._repository(row) for row in rows],
        }

    def _app_template(self, app_name: str, sample_count: int) -> dict:
        predicate = (
            "f.chart_name = 'app-template' AND app_name_matches(f.release_name, ?)"
        )
        counts = self._counts(predicate, (app_name,))
        rows = self._representative_repositories(predicate, (app_name,), sample_count)
        return {
            **counts,
            "match_rule": "name bounded by non-alphanumeric characters",
            "repositories": [self._repository(row) for row in rows],
        }

    def _counts(self, predicate: str, parameters: tuple[str, ...]) -> dict:
        row = self.connection.execute(
            f"""
            SELECT COUNT(*) AS deployment_count,
                   COUNT(DISTINCT f.repo_name) AS repository_count
            FROM flux_helm_release f
            WHERE {predicate}
            """,
            parameters,
        ).fetchone()
        return {
            "deployment_count": row["deployment_count"],
            "repository_count": row["repository_count"],
        }

    def _representative_repositories(
        self,
        predicate: str,
        parameters: tuple[str, ...],
        sample_count: int,
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            f"""
            WITH ranked AS (
                SELECT r.repo_name, COALESCE(r.stars, 0) AS stars, r.branch,
                       f.release_name,
                       f.chart_name, f.chart_version, f.namespace, f.url,
                       f.helm_repo_name,
                       ROW_NUMBER() OVER (
                           PARTITION BY r.repo_name
                           ORDER BY f.release_name, f.url
                       ) AS position
                FROM flux_helm_release f
                JOIN repo r ON r.repo_name = f.repo_name
                WHERE {predicate}
            )
            SELECT * FROM ranked
            WHERE position = 1
            ORDER BY stars DESC, repo_name
            LIMIT ?
            """,
            (*parameters, sample_count),
        ).fetchall()

    def correlate(self, app_names: list[str], sample_count: int) -> dict:
        matches_by_app = {
            app_name: self._matches_for_app(app_name) for app_name in app_names
        }
        common_repositories = set.intersection(
            *(set(matches) for matches in matches_by_app.values())
        )
        ordered_repositories = sorted(
            common_repositories,
            key=lambda repo: (
                -matches_by_app[app_names[0]][repo]["stars"],
                repo,
            ),
        )

        repositories = []
        for repo_name in ordered_repositories[:sample_count]:
            first = matches_by_app[app_names[0]][repo_name]
            repositories.append(
                {
                    "repo_name": repo_name,
                    "stars": first["stars"],
                    "source_ref": first["source_ref"],
                    "apps_found": {
                        app_name: self._app_match(matches_by_app[app_name][repo_name])
                        for app_name in app_names
                    },
                }
            )

        return {
            "apps": app_names,
            "repository_count": len(common_repositories),
            "repositories": repositories,
        }

    def _matches_for_app(self, app_name: str) -> dict[str, dict]:
        rows = self.connection.execute(
            """
            SELECT r.repo_name, COALESCE(r.stars, 0) AS stars, r.branch,
                   f.release_name,
                   f.chart_name, f.chart_version, f.namespace, f.url,
                   f.helm_repo_name
            FROM flux_helm_release f
            JOIN repo r ON r.repo_name = f.repo_name
            WHERE lower(f.chart_name) = lower(?)
               OR (f.chart_name = 'app-template'
                   AND app_name_matches(f.release_name, ?))
            ORDER BY r.stars DESC,
                     CASE WHEN f.chart_name = 'app-template' THEN 1 ELSE 0 END,
                     f.release_name,
                     f.url
            """,
            (app_name, app_name),
        )
        matches = {}
        for row in rows:
            matches.setdefault(row["repo_name"], self._repository(row))
        return matches

    @staticmethod
    def _repository(row: sqlite3.Row) -> dict:
        return {
            "repo_name": row["repo_name"],
            "stars": row["stars"],
            "source_ref": row["branch"],
            "release_name": row["release_name"],
            "chart_name": row["chart_name"],
            "chart_version": row["chart_version"],
            "namespace": row["namespace"],
            "manifest_url": row["url"],
            "manifest_path": manifest_path(row["url"], row["branch"]),
            "helm_repo_name": row["helm_repo_name"],
        }

    @staticmethod
    def _app_match(repository: dict) -> dict:
        return {
            key: repository[key]
            for key in (
                "release_name",
                "chart_name",
                "chart_version",
                "namespace",
                "manifest_url",
                "manifest_path",
                "helm_repo_name",
            )
        }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="Discover Kubernetes deployment patterns indexed by kubesearch.dev"
    )
    commands = cli.add_subparsers(dest="command", required=True)

    discover = commands.add_parser(
        "discover", help="find dedicated chart and app-template deployments"
    )
    discover.add_argument("app_name", help="application name, such as sonarr")
    discover.add_argument(
        "--sample-count",
        type=positive_int,
        default=3,
        help="maximum repositories returned per deployment type (default: 3)",
    )

    correlate = commands.add_parser(
        "correlate", help="find repositories containing all named applications"
    )
    correlate.add_argument("app_names", nargs="+", help="application names")
    correlate.add_argument(
        "--sample-count",
        type=positive_int,
        default=10,
        help="maximum repositories returned (default: 10)",
    )
    return cli


def normalized_names(cli: argparse.ArgumentParser, names: list[str]) -> list[str]:
    normalized = [name.strip().casefold() for name in names]
    if any(not name for name in normalized):
        cli.error("application names cannot be empty")
    if len(normalized) != len(set(normalized)):
        cli.error("application names must be unique")
    return normalized


def main() -> int:
    cli = parser()
    arguments = cli.parse_args()

    if arguments.command == "discover":
        app_names = normalized_names(cli, [arguments.app_name])
    else:
        app_names = normalized_names(cli, arguments.app_names)

    try:
        database_path, cache_metadata = DatabaseCache().ensure()
        scout = AppScout(database_path)
        try:
            if arguments.command == "discover":
                result = {
                    app_names[0]: scout.discover(app_names[0], arguments.sample_count)
                }
            else:
                result = scout.correlate(app_names, arguments.sample_count)
            output = {
                "database": scout.database_details(cache_metadata),
                **result,
            }
        finally:
            scout.close()
    except (OSError, RuntimeError, sqlite3.DatabaseError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
