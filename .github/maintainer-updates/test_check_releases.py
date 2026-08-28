import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).parent))

import check_releases  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class MappingOpener:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        parsed = urlsplit(request.full_url)
        key = (parsed.path, tuple(sorted(parse_qsl(parsed.query))))
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(json.dumps(response).encode())


def api_key(path, **query):
    return (path, tuple(sorted((key, str(value)) for key, value in query.items())))


def package_source(version, platform):
    return f"""
      version = "{version}";
      maintainers = with lib.maintainers; [ tyceherrman ];
      platforms = {platform};
    """


def content_payload(source):
    content = base64.b64encode(source.encode()).decode()
    return {
        "type": "file",
        "encoding": "base64",
        "content": content,
        "sha": "b" * 40,
    }


def release_payload(tag, repository):
    return {
        "url": f"https://api.github.com/repos/{repository}/releases/1",
        "html_url": f"https://github.com/{repository}/releases/tag/{tag}",
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-08T22:57:10Z",
    }


PACKAGES = (
    check_releases.Package(
        attr="harper-desktop",
        package_file="pkgs/by-name/ha/harper-desktop/package.nix",
        upstream="Automattic/harper",
        maintainer="tyceherrman",
        platform_pattern=r"platforms\s*=\s*lib\.platforms\.darwin\s*;",
        verification="harper-signature",
    ),
    check_releases.Package(
        attr="whatcable",
        package_file="pkgs/by-name/wh/whatcable/package.nix",
        upstream="darrylmorley/whatcable",
        maintainer="tyceherrman",
        platform_pattern=r'platforms\s*=\s*\[\s*"aarch64-darwin"\s*\]\s*;',
        verification="whatcable-cli",
    ),
)


def collection_responses(*, pull_requests=None, search_items=None):
    base_sha = "a" * 40
    branch = "auto-update/whatcable-1.4.0"
    title = "whatcable: 1.2.1 -> 1.4.0"
    return {
        api_key("/repos/NixOS/nixpkgs/commits/master"): {"sha": base_sha},
        api_key(
            "/repos/NixOS/nixpkgs/contents/"
            "pkgs/by-name/ha/harper-desktop/package.nix",
            ref=base_sha,
        ): content_payload(package_source("2.8.0", "lib.platforms.darwin")),
        api_key("/repos/Automattic/harper/releases/latest"): release_payload(
            "v2.8.0", "Automattic/harper"
        ),
        api_key(
            "/repos/NixOS/nixpkgs/contents/"
            "pkgs/by-name/wh/whatcable/package.nix",
            ref=base_sha,
        ): content_payload(package_source("1.2.1", '[ "aarch64-darwin" ]')),
        api_key("/repos/darrylmorley/whatcable/releases/latest"): release_payload(
            "v1.4.0", "darrylmorley/whatcable"
        ),
        api_key(
            "/repos/NixOS/nixpkgs/pulls",
            state="open",
            head=f"TyceHerrman:{branch}",
            per_page=100,
        ): pull_requests or [],
        api_key(
            "/search/issues",
            q=f'repo:NixOS/nixpkgs is:pr is:open in:title "{title}"',
            per_page=100,
        ): {
            "total_count": len(search_items or []),
            "incomplete_results": False,
            "items": search_items or [],
        },
    }


class VersionTests(unittest.TestCase):
    def test_normalizes_optional_v_prefix(self):
        self.assertEqual(check_releases.normalize_version("v1.4.0"), "1.4.0")
        self.assertEqual(check_releases.normalize_version("2.8.0"), "2.8.0")

    def test_compares_numeric_components(self):
        self.assertGreater(check_releases.compare_versions("1.10", "1.9"), 0)
        self.assertLess(check_releases.compare_versions("1.9", "1.10"), 0)
        self.assertEqual(check_releases.compare_versions("1.2", "1.2.0"), 0)

    def test_rejects_non_stable_tag_syntax(self):
        for tag in ("v2.0.0-rc1", "release-2.0", "nightly"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                check_releases.normalize_version(tag)


class PackageSourceTests(unittest.TestCase):
    def test_extracts_exactly_one_literal_version(self):
        source = 'version = "2.8.0";\n'
        self.assertEqual(check_releases.extract_package_version(source), "2.8.0")

    def test_rejects_missing_or_multiple_versions(self):
        with self.assertRaises(ValueError):
            check_releases.extract_package_version('pname = "example";')

        with self.assertRaises(ValueError):
            check_releases.extract_package_version(
                'version = "1.0";\nversion = "2.0";\n'
            )

    def test_validates_maintainer_and_darwin_pattern(self):
        package = check_releases.Package(
            attr="harper-desktop",
            package_file="package.nix",
            upstream="Automattic/harper",
            maintainer="tyceherrman",
            platform_pattern=r"platforms\s*=\s*lib\.platforms\.darwin\s*;",
            verification="harper-signature",
        )
        source = """
          version = "2.8.0";
          maintainers = with lib.maintainers; [ tyceherrman ];
          platforms = lib.platforms.darwin;
        """

        check_releases.validate_package_source(package, source)

        with self.assertRaises(ValueError):
            check_releases.validate_package_source(
                package, source.replace("tyceherrman", "someone")
            )

        with self.assertRaises(ValueError):
            check_releases.validate_package_source(
                package, source.replace("lib.platforms.darwin", "lib.platforms.unix")
            )


class CollectionTests(unittest.TestCase):
    def test_collects_only_newer_release(self):
        opener = MappingOpener(collection_responses())
        client = check_releases.GitHubClient("test-token", opener=opener)

        result = check_releases.collect_updates(
            PACKAGES, client, fork_owner="TyceHerrman"
        )

        self.assertEqual(result.base_sha, "a" * 40)
        self.assertEqual([item.attr for item in result.candidates], ["whatcable"])
        candidate = result.candidates[0]
        self.assertEqual(candidate.old_version, "1.2.1")
        self.assertEqual(candidate.new_version, "1.4.0")
        self.assertEqual(candidate.branch, "auto-update/whatcable-1.4.0")
        self.assertEqual(candidate.title, "whatcable: 1.2.1 -> 1.4.0")
        self.assertEqual(
            candidate.release_url,
            "https://github.com/darrylmorley/whatcable/releases/tag/v1.4.0",
        )
        self.assertIn("harper-desktop: current at 2.8.0", result.notes)

    def test_suppresses_existing_head_pull_request(self):
        pull_request = {
            "number": 123,
            "title": "whatcable: 1.2.1 -> 1.4.0",
            "html_url": "https://github.com/NixOS/nixpkgs/pull/123",
        }
        client = check_releases.GitHubClient(
            None,
            opener=MappingOpener(
                collection_responses(pull_requests=[pull_request])
            ),
        )

        result = check_releases.collect_updates(
            PACKAGES, client, fork_owner="TyceHerrman"
        )

        self.assertEqual(result.candidates, ())
        self.assertIn(
            "whatcable: existing pull request https://github.com/NixOS/nixpkgs/pull/123",
            result.notes,
        )

    def test_suppresses_existing_exact_title_pull_request(self):
        pull_request = {
            "number": 456,
            "title": "whatcable: 1.2.1 -> 1.4.0",
            "html_url": "https://github.com/NixOS/nixpkgs/pull/456",
        }
        client = check_releases.GitHubClient(
            None,
            opener=MappingOpener(collection_responses(search_items=[pull_request])),
        )

        result = check_releases.collect_updates(
            PACKAGES, client, fork_owner="TyceHerrman"
        )

        self.assertEqual(result.candidates, ())
        self.assertIn(
            "whatcable: existing pull request https://github.com/NixOS/nixpkgs/pull/456",
            result.notes,
        )

    def test_api_failure_is_not_treated_as_no_update(self):
        url = "https://api.github.com/repos/NixOS/nixpkgs/commits/master"
        error = HTTPError(url, 500, "server error", {}, io.BytesIO(b"{}"))
        opener = MappingOpener(
            {api_key("/repos/NixOS/nixpkgs/commits/master"): error}
        )
        client = check_releases.GitHubClient(None, opener=opener)

        with self.assertRaises(check_releases.GitHubApiError):
            check_releases.collect_updates(
                PACKAGES, client, fork_owner="TyceHerrman"
            )

    def test_token_is_an_authorization_header_not_part_of_url(self):
        opener = MappingOpener(
            {api_key("/repos/NixOS/nixpkgs/commits/master"): {"sha": "a" * 40}}
        )
        client = check_releases.GitHubClient("test-token", opener=opener)

        client.get_json("/repos/NixOS/nixpkgs/commits/master")

        request = opener.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertNotIn("test-token", request.full_url)


class ManifestTests(unittest.TestCase):
    def write_manifest(self, directory, payload):
        path = Path(directory) / "packages.json"
        path.write_text(json.dumps(payload))
        return path

    def test_loads_valid_manifest_in_attribute_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(
                directory,
                [
                    {
                        "attr": package.attr,
                        "package_file": package.package_file,
                        "upstream": package.upstream,
                        "maintainer": package.maintainer,
                        "platform_pattern": package.platform_pattern,
                        "verification": package.verification,
                    }
                    for package in reversed(PACKAGES)
                ],
            )

            packages = check_releases.load_manifest(path)

        self.assertEqual([package.attr for package in packages], [
            "harper-desktop",
            "whatcable",
        ])

    def test_rejects_duplicate_or_unsafe_manifest_entries(self):
        base = {
            "attr": "whatcable",
            "package_file": "pkgs/by-name/wh/whatcable/package.nix",
            "upstream": "darrylmorley/whatcable",
            "maintainer": "tyceherrman",
            "platform_pattern": r"platforms\s*=",
            "verification": "whatcable-cli",
        }
        invalid_payloads = (
            [base, base],
            [{**base, "package_file": "../outside.nix"}],
            [{**base, "upstream": "not-a-repository"}],
            [{**base, "verification": "arbitrary-shell"}],
            [{**base, "extra": "unexpected"}],
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(invalid_payloads):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    check_releases.load_manifest(
                        self.write_manifest(directory, payload)
                    )


class ActionsOutputTests(unittest.TestCase):
    def setUp(self):
        self.candidate = check_releases.Candidate(
            attr="whatcable",
            package_file="pkgs/by-name/wh/whatcable/package.nix",
            old_version="1.2.1",
            new_version="1.4.0",
            release_url="https://github.com/darrylmorley/whatcable/releases/tag/v1.4.0",
            branch="auto-update/whatcable-1.4.0",
            title="whatcable: 1.2.1 -> 1.4.0",
            verification="whatcable-cli",
        )

    def test_candidate_dict_and_actions_files_are_deterministic(self):
        collection = check_releases.Collection(
            base_sha="a" * 40,
            candidates=(self.candidate,),
            notes=("harper-desktop: current at 2.8.0",),
        )
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            summary_path = Path(directory) / "summary"

            payload = check_releases.write_actions_outputs(
                collection, output_path, summary_path
            )

            output = output_path.read_text()
            summary = summary_path.read_text()

        expected_candidate = {
            "attr": "whatcable",
            "package_file": "pkgs/by-name/wh/whatcable/package.nix",
            "old_version": "1.2.1",
            "new_version": "1.4.0",
            "release_url": "https://github.com/darrylmorley/whatcable/releases/tag/v1.4.0",
            "branch": "auto-update/whatcable-1.4.0",
            "title": "whatcable: 1.2.1 -> 1.4.0",
            "verification": "whatcable-cli",
        }
        matrix = json.dumps(
            {"include": [expected_candidate]}, separators=(",", ":")
        )
        self.assertEqual(check_releases.candidate_to_dict(self.candidate), expected_candidate)
        self.assertEqual(
            output,
            f"base_sha={'a' * 40}\nhas_updates=true\nmatrix={matrix}\n",
        )
        self.assertEqual(payload["matrix"], {"include": [expected_candidate]})
        self.assertTrue(payload["has_updates"])
        self.assertIn("harper-desktop: current at 2.8.0", summary)
        self.assertIn("1 update", summary)

    def test_empty_collection_emits_false_and_empty_matrix(self):
        collection = check_releases.Collection("b" * 40, (), ("nothing new",))
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "output"
            summary_path = Path(directory) / "summary"

            check_releases.write_actions_outputs(
                collection, output_path, summary_path
            )

            output = output_path.read_text()

        self.assertEqual(
            output,
            f"base_sha={'b' * 40}\nhas_updates=false\nmatrix={{\"include\":[]}}\n",
        )


if __name__ == "__main__":
    unittest.main()
