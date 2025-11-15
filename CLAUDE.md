# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Nixpkgs is a collection of over 120,000 software packages for the Nix package manager and the implementation of NixOS. This is one of the largest and most active package repositories on GitHub.

## Building and Testing

### Testing Package Changes

Build a package:
```bash
nix-build -A <package-name>
```

Add `-K` flag to keep the temporary build directory on failure for debugging.

If successful, a `./result` symlink is created pointing to the built package in the Nix store.

### Testing with Sandboxing

Sandboxing is enabled by default on Linux. For other platforms, enable it in `/etc/nix/nix.conf`:
```ini
sandbox = true
```

### Using nixpkgs-review

Review changes and test reverse dependencies:
```bash
# Review a PR
nix-shell -p nixpkgs-review --run "nixpkgs-review pr <PR-number>"

# Review uncommitted changes
nix-shell -p nixpkgs-review --run "nixpkgs-review wip"

# Review last commit
nix-shell -p nixpkgs-review --run "nixpkgs-review rev HEAD"
```

With flakes:
```bash
nix run nixpkgs#nixpkgs-review -- pr <PR-number>
```

### Testing NixOS Changes

Test NixOS module changes:
```bash
sudo nixos-rebuild test -I nixpkgs=<path-to-local-nixpkgs> --fast
```

Run NixOS tests:
```bash
# Tests are in nixos/tests/
nix-build -A nixosTests.<test-name>
```

Invoke OfBorg to test a module:
```
@ofborg test <module>
```

## Formatting and Linting

### Code Formatting

All Nix files MUST be formatted using nixfmt. CI enforces this.

Format all files:
```bash
nix-shell --run treefmt
# OR
nix develop --command treefmt
# OR
nix fmt
```

### Development Shell

Enter development shell with tooling:
```bash
nix-shell
# OR
nix develop
```

Provides: nixpkgs-review, gh (GitHub CLI), and formatting tools.

## Repository Structure

### Package Organization

- **`pkgs/by-name/`**: Modern organization for top-level packages
  - Structure: `pkgs/by-name/<2-letter-prefix>/<package-name>/package.nix`
  - Example: `pkgs/by-name/he/hello/package.nix`
  - This is the preferred location for new packages

- **`pkgs/`**: Legacy categorized organization
  - `applications/`, `development/`, `games/`, `servers/`, etc.
  - Nested package sets for language-specific packages (e.g., Python, Perl)
  - `build-support/`: Builders and fetchers
  - `stdenv/`: Standard environment
  - `top-level/`: Entry points and package set aggregation

- **`nixos/`**: NixOS implementation
  - `modules/`: NixOS configuration modules
  - `tests/`: NixOS integration tests
  - `lib/`: NixOS-specific library functions

- **`lib/`**: Nixpkgs library functions (also exposed in flake as `nixpkgs.lib`)

- **`doc/`**: Nixpkgs manual sources

- **`maintainers/`**: Maintainer listings and scripts

## Adding a New Package

1. Create package directory:
```bash
# For package named "some-package" (prefix is first 2 lowercase letters)
mkdir -p pkgs/by-name/so/some-package
```

2. Create `package.nix` in that directory with a function that returns a derivation

3. Add yourself as maintainer (first time contributors):
   - Add to `maintainers/maintainer-list.nix` in a separate commit with message: `maintainers: add <handle>`

4. Test the build:
```bash
nix-build -A some-package
```

5. Test executables in `./result/bin/`

6. Format code:
```bash
nix fmt
```

### Package Examples

- Simple package: `pkgs/by-name/he/hello/package.nix`
- Package with dependencies: `pkgs/by-name/cp/cpio/package.nix`
- Package with optional dependencies: `pkgs/by-name/pa/pan/package.nix`
- Binary-only package: `pkgs/by-name/di/discord-gamesdk/package.nix`

## Commit Conventions

### Package Changes

Format:
```
<pkg-name>: <change-type>

<motivation-and-details>
```

Examples:
- `nginx: init at 2.0.1`
- `firefox: 54.0.1 -> 55.0` (or `54.0.1 → 55.0`)
- `python3{9,10}Packages.requests: 1.0.0 -> 2.0.0`

The `(pkg-name):` prefix triggers automatic CI builds.

### NixOS Module Changes

Format:
```
nixos/<module>: <change-type>

<motivation-and-details>
```

Examples:
- `nixos/hydra: add bazBaz option`
- `nixos/nginx: refactor config generation`

### General Rules

- One commit per logical unit
- Squash fixup commits before merging
- No period at end of summary line
- Read area-specific conventions in `doc/`, `lib/`, `nixos/`, `pkgs/` README files

## Branch Strategy

### Primary Branches

- **`master`**: Main development branch (unstable channels)
- **`release-YY.MM`**: Stable release branches (e.g., `release-25.05`)
- **`staging`**: For changes causing mass rebuilds (500-1000+ packages)
- **`staging-next`**: Intermediate testing branch for staging changes
- **`staging-nixos`**: For kernel updates and test driver changes

### When to Use Which Branch

Use `master` for:
- Most changes
- Non-mass-rebuild changes

Use `staging` for:
- Changes rebuilding 1000+ packages

Use `release-YY.MM` for:
- Backports of security fixes
- Backports of backwards-compatible changes

### Rebasing Between Branches

```bash
# Rebase from master to staging
git rebase --onto upstream/staging... upstream/master
git push origin feature --force-with-lease
```

## CI and Automated Checks

### OfBorg

- Builds packages automatically on PRs
- Triggers on commit message patterns (package name prefix)
- Can be manually invoked with `@ofborg` commands

### GitHub Actions

- Formatting checks (nixfmt)
- Evaluation checks
- Various linting and validation
- Automatic backport PRs (via `backport release-YY.MM` labels)

### Merge Bot

Invoke with: `@NixOS/nixpkgs-merge-bot merge`

Requirements:
- Author must be a committer or @r-ryantm
- Invoker must be a package maintainer
- Package must be in `pkgs/by-name`
- All CI checks must pass

## Code Style

### Nix Syntax

- Use `lowerCamelCase` for variable names
- List function parameters explicitly (no `args: with args;`)
- Avoid unnecessary string interpolation: `{ rev = version; }` not `{ rev = "${version}"; }`
- Use `lib.optional(s)` for conditional lists
- File naming: lowercase with dashes (kebab-case)

### Meta Attributes

Always include:
- `meta.description`
- `meta.homepage`
- `meta.license`
- `meta.maintainers` (include yourself)
- `meta.platforms` (if not all platforms)

## Flake Interface

This repository provides:

- `nixpkgs.lib`: Library functions including `lib.nixosSystem`
- `nixpkgs.legacyPackages.<system>`: All packages
- `nixpkgs.nixosModules.*`: Optional NixOS modules
- Development shell with nixpkgs-review and other tools

## Release Notes

Major changes should be documented in `nixos/doc/manual/release-notes/rl-YYMM.section.md` for the next release.

## Important Notes

- Hydra is the CI system: https://hydra.nixos.org/
- Successful builds are cached at https://cache.nixos.org/
- Review process is community-driven; be patient and proactive
- Test changes thoroughly before submitting PRs
- Never use `nix fmt` output as final without reviewing it
