# Darwin maintainer release automation

This fork-only workflow checks `harper-desktop` and `whatcable` for stable
GitHub releases every six hours. Each update is built and checked on an Apple
Silicon GitHub runner before the workflow pushes an automation branch and opens
a draft pull request against `NixOS/nixpkgs` under Tyce Herrman's account. Once
the upstream checks have passed or been skipped, a separate Linux job starts a
Darwin-only review in `TyceHerrman/nixpkgs-review-gha`.

## One-time setup

1. On Tyce Herrman's GitHub account, create a classic personal access token
   with the `public_repo` scope and a suitable expiration. GitHub currently
   requires a classic token for contributing to a public repository that the
   token owner does not own and is not a member of; a fine-grained token cannot
   be scoped to `NixOS/nixpkgs` for this use case. The review gate also uses
   this token to read the upstream PR's check rollup.
2. In `TyceHerrman/nixpkgs`, open **Settings > Secrets and variables > Actions**
   and add that token as the repository secret `NIXPKGS_PR_TOKEN`.
3. Create a fine-grained personal access token with repository access limited
   to `TyceHerrman/nixpkgs-review-gha` and **Actions: Read and write**. Add it to
   `TyceHerrman/nixpkgs` as the repository secret
   `NIXPKGS_REVIEW_GHA_TOKEN`.
4. Under **Settings > Actions > General > Workflow permissions**, select
   **Read and write permissions**. The short-lived workflow `GITHUB_TOKEN` uses
   this only to push validated branches back to the fork.
5. Merge this automation branch into the fork's default branch. GitHub runs
   scheduled workflows only from the default branch.
6. Use **Actions > Tyce Darwin maintainer updates > Run workflow** for a manual
   check or update run.

The PATs are created, stored, expired, and rotated by the user. The workflow can
consume the Actions secrets but cannot read their values back from GitHub.
Rotate each token before its expiration and review every generated draft
manually.

## Scope and behavior

The reviewed allowlist is [`packages.json`](packages.json); acquiring another
nixpkgs maintainership does not automatically add it. The detector checks the
current `NixOS/nixpkgs` `master`, accepts only stable numeric GitHub release
tags, and suppresses an update when an open PR already has the deterministic
head branch or exact update title.

Generated branches use `auto-update/<attribute>-<version>`. The workflow never
merges PRs, marks drafts ready, deletes branches, or writes upstream issues or
labels. The review gate polls for up to three hours and requires the complete
check set to remain in GitHub CLI's `pass` or `skipping` buckets for three
consecutive observations. It stops without dispatching on failed or cancelled
checks, and it suppresses duplicate `review #<PR>` workflow runs. The dispatched
review enables only `x86_64-darwin` and `aarch64-darwin`, both with relaxed Nix
sandboxing.

A missing or rejected `NIXPKGS_PR_TOKEN` leaves the already validated fork
branch in place so a later run can retry draft creation. A missing or rejected
`NIXPKGS_REVIEW_GHA_TOKEN` leaves the draft PR intact and fails only the review
gate.
