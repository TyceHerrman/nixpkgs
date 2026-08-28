#!/usr/bin/env python3

import argparse
import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
MANIFEST_FIELDS = {
    "attr",
    "package_file",
    "upstream",
    "maintainer",
    "platform_pattern",
    "verification",
}
VERIFICATION_NAMES = {"harper-signature", "whatcable-cli"}


class GitHubApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Package:
    attr: str
    package_file: str
    upstream: str
    maintainer: str
    platform_pattern: str
    verification: str


@dataclass(frozen=True)
class Candidate:
    attr: str
    package_file: str
    old_version: str
    new_version: str
    release_url: str
    branch: str
    title: str
    verification: str


@dataclass(frozen=True)
class Collection:
    base_sha: str
    candidates: tuple[Candidate, ...]
    notes: tuple[str, ...]


class GitHubClient:
    def __init__(self, token: str | None, *, opener=urlopen):
        self.token = token
        self.opener = opener

    def get_json(self, path: str, *, query: dict[str, object] | None = None):
        if not path.startswith("/"):
            raise ValueError("GitHub API path must begin with a slash")

        url = f"{API_ROOT}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "nixpkgs-darwin-maintainer-updates",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers)

        try:
            with self.opener(request) as response:
                return json.load(response)
        except (HTTPError, URLError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubApiError(f"GitHub API request failed for {path}: {error}") from error

    def get_text_content(self, repository: str, path: str, *, ref: str) -> str:
        payload = self.get_json(
            f"/repos/{repository}/contents/{path}", query={"ref": ref}
        )
        try:
            if not isinstance(payload, dict):
                raise TypeError("contents response is not an object")
            if payload.get("type") != "file" or payload.get("encoding") != "base64":
                raise ValueError("contents response is not a base64 file")
            content = payload["content"]
            if not isinstance(content, str):
                raise TypeError("contents payload is not text")
            return base64.b64decode(content).decode()
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
            raise GitHubApiError(
                f"invalid GitHub contents response for {repository}/{path}: {error}"
            ) from error


def load_manifest(path: Path) -> tuple[Package, ...]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read package manifest {path}: {error}") from error
    if not isinstance(payload, list):
        raise ValueError("package manifest must be a JSON array")

    packages: list[Package] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != MANIFEST_FIELDS:
            raise ValueError(f"manifest entry {index} has unexpected fields")
        if not all(isinstance(item[field], str) for field in MANIFEST_FIELDS):
            raise ValueError(f"manifest entry {index} fields must all be strings")

        package = Package(**item)
        if re.fullmatch(r"[a-z0-9][a-z0-9+._-]*", package.attr) is None:
            raise ValueError(f"invalid package attribute: {package.attr!r}")
        if package.attr in seen:
            raise ValueError(f"duplicate package attribute: {package.attr}")
        seen.add(package.attr)

        package_path = PurePosixPath(package.package_file)
        if (
            package_path.is_absolute()
            or not package_path.parts
            or package_path.parts[0] != "pkgs"
            or ".." in package_path.parts
            or package_path.suffix != ".nix"
        ):
            raise ValueError(f"unsafe package path: {package.package_file!r}")
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", package.upstream) is None:
            raise ValueError(f"invalid upstream repository: {package.upstream!r}")
        if re.fullmatch(r"[A-Za-z0-9_]+", package.maintainer) is None:
            raise ValueError(f"invalid maintainer name: {package.maintainer!r}")
        if package.verification not in VERIFICATION_NAMES:
            raise ValueError(
                f"unsupported verification for {package.attr}: {package.verification!r}"
            )
        try:
            re.compile(package.platform_pattern)
        except re.error as error:
            raise ValueError(
                f"invalid platform pattern for {package.attr}: {error}"
            ) from error
        packages.append(package)

    return tuple(sorted(packages, key=lambda package: package.attr))


def normalize_version(tag: str) -> str:
    match = re.fullmatch(r"v?([0-9]+(?:\.[0-9]+)*)", tag)
    if match is None:
        raise ValueError(f"unsupported stable release tag: {tag!r}")
    return match.group(1)


def compare_versions(left: str, right: str) -> int:
    left_parts = tuple(int(part) for part in left.split("."))
    right_parts = tuple(int(part) for part in right.split("."))
    length = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (length - len(left_parts))
    right_parts += (0,) * (length - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)


def extract_package_version(source: str) -> str:
    versions = re.findall(
        r'^\s*version\s*=\s*"([^"]+)"\s*;', source, re.MULTILINE
    )
    if len(versions) != 1:
        raise ValueError(
            f"expected one literal version assignment, found {len(versions)}"
        )
    return normalize_version(versions[0])


def validate_package_source(package: Package, source: str) -> None:
    if re.search(rf"\b{re.escape(package.maintainer)}\b", source) is None:
        raise ValueError(f"{package.attr}: expected maintainer is absent")
    if re.search(package.platform_pattern, source, re.MULTILINE) is None:
        raise ValueError(
            f"{package.attr}: expected Darwin platform declaration is absent"
        )


def _require_base_sha(payload) -> str:
    if not isinstance(payload, dict):
        raise GitHubApiError("invalid upstream commit response")
    sha = payload.get("sha")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise GitHubApiError("invalid upstream commit SHA")
    return sha


def _require_latest_release(payload, upstream: str) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise GitHubApiError(f"invalid latest release response for {upstream}")
    if payload.get("draft") is not False or payload.get("prerelease") is not False:
        raise GitHubApiError(f"latest release for {upstream} is not stable")
    tag = payload.get("tag_name")
    release_url = payload.get("html_url")
    if not isinstance(tag, str) or not tag:
        raise GitHubApiError(f"latest release for {upstream} has no tag")
    if not isinstance(release_url, str) or not release_url:
        raise GitHubApiError(f"latest release for {upstream} has no URL")
    return normalize_version(tag), release_url


def _existing_pr_url(
    client: GitHubClient, *, fork_owner: str, branch: str, title: str
) -> str | None:
    pulls = client.get_json(
        "/repos/NixOS/nixpkgs/pulls",
        query={
            "state": "open",
            "head": f"{fork_owner}:{branch}",
            "per_page": 100,
        },
    )
    if not isinstance(pulls, list):
        raise GitHubApiError("invalid pull request list response")
    if pulls:
        url = pulls[0].get("html_url") if isinstance(pulls[0], dict) else None
        if not isinstance(url, str) or not url:
            raise GitHubApiError("existing pull request has no URL")
        return url

    search = client.get_json(
        "/search/issues",
        query={
            "q": f'repo:NixOS/nixpkgs is:pr is:open in:title "{title}"',
            "per_page": 100,
        },
    )
    if not isinstance(search, dict) or not isinstance(search.get("items"), list):
        raise GitHubApiError("invalid pull request search response")
    for item in search["items"]:
        if isinstance(item, dict) and item.get("title") == title:
            url = item.get("html_url")
            if not isinstance(url, str) or not url:
                raise GitHubApiError("matching pull request has no URL")
            return url
    return None


def collect_updates(
    packages: tuple[Package, ...] | list[Package],
    client: GitHubClient,
    *,
    fork_owner: str,
) -> Collection:
    base_sha = _require_base_sha(
        client.get_json("/repos/NixOS/nixpkgs/commits/master")
    )
    candidates: list[Candidate] = []
    notes: list[str] = []

    for package in sorted(packages, key=lambda item: item.attr):
        source = client.get_text_content(
            "NixOS/nixpkgs", package.package_file, ref=base_sha
        )
        validate_package_source(package, source)
        old_version = extract_package_version(source)
        new_version, release_url = _require_latest_release(
            client.get_json(f"/repos/{package.upstream}/releases/latest"),
            package.upstream,
        )
        if compare_versions(new_version, old_version) <= 0:
            notes.append(f"{package.attr}: current at {old_version}")
            continue

        branch = f"auto-update/{package.attr}-{new_version}"
        title = f"{package.attr}: {old_version} -> {new_version}"
        existing_url = _existing_pr_url(
            client,
            fork_owner=fork_owner,
            branch=branch,
            title=title,
        )
        if existing_url is not None:
            notes.append(f"{package.attr}: existing pull request {existing_url}")
            continue

        candidates.append(
            Candidate(
                attr=package.attr,
                package_file=package.package_file,
                old_version=old_version,
                new_version=new_version,
                release_url=release_url,
                branch=branch,
                title=title,
                verification=package.verification,
            )
        )

    return Collection(base_sha, tuple(candidates), tuple(notes))


def candidate_to_dict(candidate: Candidate) -> dict[str, str]:
    return {
        "attr": candidate.attr,
        "package_file": candidate.package_file,
        "old_version": candidate.old_version,
        "new_version": candidate.new_version,
        "release_url": candidate.release_url,
        "branch": candidate.branch,
        "title": candidate.title,
        "verification": candidate.verification,
    }


def collection_payload(collection: Collection) -> dict[str, object]:
    return {
        "base_sha": collection.base_sha,
        "has_updates": bool(collection.candidates),
        "matrix": {
            "include": [
                candidate_to_dict(candidate) for candidate in collection.candidates
            ]
        },
        "notes": list(collection.notes),
    }


def write_actions_outputs(
    collection: Collection, output_path: Path, summary_path: Path
) -> dict[str, object]:
    payload = collection_payload(collection)
    matrix_json = json.dumps(payload["matrix"], separators=(",", ":"))
    has_updates = "true" if payload["has_updates"] else "false"
    with output_path.open("a", encoding="utf-8") as output:
        output.write(f"base_sha={collection.base_sha}\n")
        output.write(f"has_updates={has_updates}\n")
        output.write(f"matrix={matrix_json}\n")

    count = len(collection.candidates)
    noun = "update" if count == 1 else "updates"
    summary_lines = [
        "## Darwin maintainer release check",
        "",
        f"- Upstream nixpkgs base: `{collection.base_sha}`",
        f"- Result: {count} {noun}",
    ]
    if collection.notes:
        summary_lines.extend(["", "### Notes", ""])
        summary_lines.extend(f"- {note}" for note in collection.notes)
    with summary_path.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(summary_lines) + "\n")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect GitHub releases for Tyce's Darwin-only nixpkgs"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("packages.json"),
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (args.github_output is None) != (args.github_summary is None):
        raise ValueError(
            "--github-output and --github-summary must be supplied together"
        )
    packages = load_manifest(args.manifest)
    client = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    collection = collect_updates(packages, client, fork_owner="TyceHerrman")
    if args.github_output is not None:
        payload = write_actions_outputs(
            collection, args.github_output, args.github_summary
        )
    else:
        payload = collection_payload(collection)
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
