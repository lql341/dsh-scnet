# Changelog

## 0.6.15 - 2026-10-22

- Let `doctor` accept an explicit region and repeated queues, and verify that
  each selected queue exists in that region.
- Reject queue binding when `--no-network` cannot verify it.
- Report whether the region came from CLI, environment, profile or user config.
- Add region/queue binding and missing-queue regressions.

## 0.6.14 - 2026-10-22

- Resolve the OpenAPI region from `SCNET_OPENAPI_REGION_ID`, then the selected
  profile, then stored user config; report the source in `doctor`.
- Keep `doctor` offline behavior unchanged while making the environment/profile
  override visible and testable.

## 0.6.13 - 2026-10-18

- Recover from invalid Windows credential-store encodings with redacted instructions instead
  of an uncaught decode error; include Windows Credential Manager in reset choices.
- Print absolute, shell-quoted follow-up commands after setup, so users can run config and
  doctor from any working directory, including installation paths with spaces or apostrophes.
- Synchronize the first-use preparation checklist into both distribution repositories' English
  and Chinese READMEs, preserve installation instructions, and clarify native Windows OpenAPI support.
- Extend regression coverage to credential decoding, executable PowerShell follow-up commands,
  and repeatable onboarding document generation for both distribution layouts.

## 0.6.12 - 2026-10-18

- Explain required inputs and their official download locations before first-time setup in
  the Skill entrypoint, both READMEs, and the local wizard; request only the selected backend's credentials.
- Guide AK/SK input with quote normalization, paste validation, hidden keys, and explicit
  credential source/persistence status; verify saved credentials by reading them back.
- Add current-user Windows Credential Manager support and portable non-secret config writes;
  clarify Keychain, Linux keyring dependencies, PowerShell process scope, and WSL2 separation.
- Preview SSH key sources, cluster usernames, installed paths and existing Host handling;
  report effective SSH parameters and document Windows OpenSSH setup and key expiry.
- Test onboarding outcomes and credential handling on Linux, macOS and Windows, including
  an isolated native Windows credential-store round trip with dummy data.

## 0.6.11 - 2026-10-18

- Keep Slurm job generation working when the optional SSH node-count probe fails;
  preserve profile/cache metadata and cover probe outcomes with deterministic SSH mocks.
- Skip POSIX file-mode checks on Windows without claiming ACL verification, and clarify
  Windows setup guidance and the recommended WSL2 environment.
- Enforce LF line endings for shell scripts in the canonical and distribution repositories.
- Start downstream synchronization only after canonical main validation succeeds, and publish
  aligned 0.6.11 versions with generated English and Chinese README release blocks.

## 0.6.10 - 2026-10-15

- Coordinate the synchronized downstream DSH release with a protocol-neutral one-shot loopback
  OAuth callback listener, fixed-path validation, timeout cleanup, and generic browser responses.
- Keep the canonical Skill endpoint-neutral: no SCNet issuer, endpoint, client ID, scope, or
  credential is embedded in this release.

## 0.6.9 - 2026-10-14

- Default CLI job, transfer, queue, and log output to a compact projection; add `--details`
  for the previous normalized field set while preserving `--raw` and full dry-run previews.
- Keep SDK/backend schemas independent from CLI output and document bounded internal waiting.
- Fall back to Slurm accounting when SSH `squeue` reports an invalid historical job ID.
- Confirm ambiguous OpenAPI live completion through accounting; report `FINALIZING` until
  accounting arrives, including immediately after cancellation.
- Align first-use defaults and preserve configuration fields when updating the Bash panel.
- Correct token caching, SSH option compatibility, and Notebook documentation.

## 0.6.8 - 2026-10-12

- In the downstream DSH connector, add stable error codes and JSON-safe error envelopes.
- In the downstream DSH connector, add one-shot OAuth callback sessions that reject callback replay.
- Add a platform credential-store adapter for Secret Service or other OS keyrings without a
  plaintext fallback.

## 0.6.7 - 2026-10-12

- Allow Desktop hosts to inject a verified Python 3 interpreter through
  `DSH_SCNET_PYTHON` or `SCNET_PYTHON`; local scripts no longer require a `python3` command name.
- Fall back to an available Python 3 command when no interpreter is injected, while rejecting
  Python 2 and invalid configured paths.

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
