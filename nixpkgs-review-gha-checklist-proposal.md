# Feature request: optionally check the nixpkgs-review item in the PR description

opt-in feature to check the nixpkgs PR template's `nixpkgs-review` item after a successful review

## Use case

I have a custom updater for bumping versions of darwin-only packages and auto-creating PRs to nixpkgs. It also auto-requests nixpkgs-review-gha run. The review posts its result on PR, it can even be auto-marked as ready, but the PR description still contains:

```markdown
- [ ] Ran `nixpkgs-review` on this PR. See [nixpkgs-review usage].
```

would be nice to have an option to change that checklist item to `[x]` after successful reporting

The reporting API introduced in [#138](https://github.com/Defelo/nixpkgs-review-gha/pull/138) seems relevant 
