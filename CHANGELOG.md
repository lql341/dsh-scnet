# Changelog

## 0.6.6 - 2026-10-10

- Generate one current-release README block from canonical English and Chinese highlight files,
  replacing the previous version block instead of accumulating release history in every README.
- Automatically create Git tags and GitHub Releases for the canonical Skill and Codex Plugin.
- Automatically publish the synchronized DSH package to npm and create its matching Git tag and
  GitHub Release after validation.

## 0.6.5 - 2026-10-09

- Clarify that the release workflow reads the package version instead of documenting a fixed
  version number.
- Surface the 0.6.4 OpenAPI-first default and optional Ubuntu/Debian `libsecret-tools` credential
  storage guidance in distribution READMEs.

## 0.6.4 - 2026-10-09

- Prefer OpenAPI with AK/SK for new configurations and backend selection; retain SSH as an
  explicit secondary backend for shell-based workflows.
- Document Ubuntu/Debian `libsecret-tools` installation for secure local AK/SK storage and
  clarify that environment-injected credentials do not require it.

## 0.6.3 - 2026-10-01

- Make queue preflight fail closed for mutating submissions and add bounded job waiting.
- Add account and resource summaries, structured JSON error categories, and automatic download
  filename derivation.
- Normalize ordinary and chunked upload results to the same remote directory/filename contract.

## 0.6.2 - 2026-09-30

- Query completed jobs through the filtered history-list endpoint instead of the slow,
  empty history-detail response; callers still provide only a job ID.
- Normalize the historical `workdir`, queue-time, and walltime field variants.
- Treat token-cache locking and writes as best-effort optimizations so read-only homes,
  sandboxes, and containers can continue without persistent caching.

## 0.6.1 - 2026-09-30

- Complete job-state normalization and fall back from stale realtime job records to the
  documented history endpoint.
- Add compact active/history job listing and persist OpenAPI region tokens with a locked,
  permission-restricted cache.
- Clarify that OpenAPI uploads take a remote directory; the local filename is supplied
  separately and is never part of the directory path.

## 0.6.0 - 2026-09-30

- Surface the job lifecycle in the downstream DSH bundle: submission, status, logs, and
  cancellation become first-class tools instead of CLI-only operations.
- Add a convenience job-log mode for OpenAPI jobs that derives
  `{work_dir}/std.{out,err}.{job_id}`, while keeping explicit absolute paths as the general
  contract and as the only mode available over SSH.
- Canonical Skill behaviour is unchanged: the underlying OpenAPI and SSH job operations shipped in
  0.5.0. This release carries the downstream tool registration and its version alignment.

## 0.5.1 - 2026-09-30

- Align downstream DSH, Codex Plugin, and npm package versioning at the canonical release version.
- Update the DSH downstream sync workflow to preserve prerelease and stable version strings without duplication.

## 0.5.0 - 2026-09-27

- Added repeatable configuration lifecycle and SSH key rotation metadata.
- Added SCNet OpenAPI authentication, multi-region discovery, jobs, files, and transfer support.
- Added shared internal OpenAPI client for CLI, plugins, and future adapters.
- Added Notebook region, resource, image, instance, URL, and safe lifecycle operations.
- Added sensitive-field redaction, dry-run support, and confirmation-driven mutations.
- Added verified one-line Codex Skill installation.
- Expanded canonical, Codex Plugin, and DSH synchronization validation.
