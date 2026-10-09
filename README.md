# DSH-SCNet

[简体中文](./README_CN.md)

DSH-SCNet (`dsh-scnet` on npm) is a community-maintained DSH bundle for operating Supercomputing Network (SCNet). It packages the source [`scnet-hpc`](https://github.com/lql341/scnet-hpc) Skill, profile-aware utilities, and bounded tools for SSH, Slurm, OpenAPI files, regional resources, and Notebook discovery.

Current release: **0.6.5**

> This is an independent community project. It is compatible with DeepSeek Harness but is not an official DeepSeek product and does not imply endorsement, partnership, or authorization by DeepSeek.

## What's new in 0.6.3

- Added read-only account and resource summaries plus bounded `scnet_job_wait`.
- Submission queue preflight now fails closed and never silently selects a queue.
- Download paths can default to the remote filename; ordinary and chunked uploads return the same
  directory/filename result shape.

## 0.6.2 highlights

- Completed jobs now resolve through the fast filtered history-list endpoint rather than timing
  out on the empty history-detail response.
- Historical field aliases such as `workdir` are normalized for log-path discovery.
- OpenAPI operations continue without persistent caching when the cache directory is read-only.

## 0.6.1 highlights

- Job details now fall back to the history endpoint when realtime records expire, with complete
  normalized terminal states.
- Added compact `scnet_job_list`, `scnet_limits`, and `scnet_file_transfer` tools.
- File uploads now make the remote-directory contract explicit: the local filename is preserved
  and must not be passed as the remote directory.

## 0.6.0 highlights

- Added first-class DSH tools for submitting jobs, inspecting job status, reading logs, and
  cancelling jobs through the existing SSH/OpenAPI backends.
- Added dry-run support and one-missing-decision-at-a-time validation for job lifecycle calls.
- Job submission reports the authoritative work directory and log paths; OpenAPI log lookup can
  derive `std.out` and `std.err` paths from `job_id` and `work_dir`.

## Requirements

- Node.js 22.19 or later
- DeepSeek Harness (`dsh`)
- Linux or macOS for native shell execution
- Windows through WSL2; native Windows execution is not supported by the bundled Bash scripts
- An SCNet account and cluster credentials for remote operations

## Install

```sh
dsh plugin --profile web add dsh-scnet
```

Then verify that the bundle layer is present:

```sh
dsh --profile web --dump-config
```

See [Installation](./docs/installation.md) for npm, GitHub, and local-checkout workflows.

## Included capabilities

| Component | Purpose |
| --- | --- |
| `scnet-hpc` skill | Profile-based operating guidance for SSH, Slurm, offline compute nodes, and accelerator validation |
| `scnet_list_clusters` | List packaged cluster profiles |
| `scnet_show_cluster` | Read a selected profile before reporting resource constraints |
| `scnet_generate_job` | Generate profile-aware accelerator or CPU-only Slurm scripts |
| `scnet_setup_ssh` | Configure a local SSH key and host entry with explicit user confirmation |
| `scnet_probe_cluster` | Produce an initial profile from read-only login-node probes |
| `scnet_refresh_cluster` | Refresh time-sensitive profile fields; compute probing is opt-in |
| `scnet_run_compute_probe` | Submit a minimal compute-node capability probe |
| `scnet_status` | Read the saved backend, SSH profile, and OpenAPI configuration |
| `scnet_openapi_regions` | List authorized OpenAPI regions without exposing tokens |
| `scnet_account_summary` | Read account status and balance |
| `scnet_resource_summary` | Summarize regional queues and resource limits |
| `scnet_job_queues` | Query regional Slurm queues and live resource availability |
| `scnet_job_list` | List active or historical jobs with compact normalized records |
| `scnet_limits` | Read user and scheduler resource limits |
| `scnet_submit_job` | Submit a job through OpenAPI or SSH; `dry_run=true` only previews the request |
| `scnet_job_show` | Read one job's state, resources, and log paths |
| `scnet_job_wait` | Wait for a job to reach a terminal state with a bounded timeout |
| `scnet_job_logs` | Read job logs by explicit path, or by `job_id` + `work_dir` |
| `scnet_job_cancel` | Cancel a job; `dry_run=true` only previews the request |
| `scnet_file_list` | List shared-storage files through the common file API |
| `scnet_file_transfer` | Upload or download one file without overwriting by default |
| `scnet_notebook_regions` | List Notebook-capable regions |
| `scnet_notebook_resources` | Query Notebook CPU/GPU/DCU resources |
| `scnet_notebook_list` | List Notebook instances with sensitive fields redacted |
| `scnet_notebook_show` | Inspect one redacted Notebook instance |

Packaged profiles currently cover Zhengzhou, Kunshan, Wuzhen, and Xi'an SCNet environments. Cluster specifications and scheduler policies remain profile-specific and should be verified against the target environment.

## Bundle structure

```text
.
├── package.json
├── cordis.patch.yml
├── index.mjs
├── skills/scnet-hpc/
│   ├── SKILL.md
│   ├── clusters/
│   ├── references/
│   └── scripts/
│       ├── scnet_backends/
│       └── scnet_sdk/
├── scripts/validate-package.mjs
├── docs/
├── sync.sh
└── .github/workflows/
```

The package is a DSH bundle: `package.json` declares `dsh.bundle.patch`, and `cordis.patch.yml` mounts both the tool plugin and the packaged skill directory through `@deepseek-ai/dsh-skill-filesystem`.

## Source synchronization

The `skills/scnet-hpc/` directory is generated from the canonical `scnet-hpc` repository:

```sh
./sync.sh --src ../scnet-hpc
```

Do not maintain the generated directory independently. The sync excludes the canonical installer and local probe cache because neither belongs in the npm runtime package.

Release order is canonical-to-downstream: update `scnet-hpc/VERSION` first; its CI then
synchronizes the skill and version into `dsh-scnet` and `codex-scnet-hpc`. Publish the matching
`dsh-scnet` npm package only after that downstream change is reviewed.

For a synchronized release, run the package validation on `main`, then trigger the repository's
`Publish DSH-SCNet` workflow with the exact value from `package.json` (currently `0.6.3`). The
workflow verifies the package/Skill version match, runs validation, creates the tarball, publishes
stable releases with the `latest` tag, and creates the matching Git tag. Do not bump only
`package.json`: `skills/scnet-hpc/VERSION`, the package version, and both README release markers
must stay aligned.

The workflow uses npm Trusted Publishing through GitHub OIDC, so account 2FA/Passkey should remain
enabled and no long-lived `NPM_TOKEN` is required. Configure `lql341/dsh-scnet` and
`.github/workflows/publish.yml` as a trusted publisher in the npm package settings before the
first OIDC release. A granular read/write token with 2FA bypass is a fallback only when Trusted
Publishing cannot be enabled.

## Validation

```sh
npm install --no-package-lock --ignore-scripts
npm run validate
npm pack --dry-run
```

See [Testing](./docs/testing.md) for local package installation and risk-ordered runtime checks.

## Security boundaries

- The repository and npm package must not contain private keys, tokens, usernames, private endpoints, or local probe caches.
- SSH configuration, remote probes, and Slurm submission are state-changing operations and require an explicit target and user authorization.
- OpenAPI and Notebook DSH tools are read-only; lifecycle mutations remain behind the Skill CLI confirmation flow.
- Notebook passwords and credential-bearing URL queries are redacted by default.
- Generated Slurm files may include local usernames and are ignored by Git.
- Accelerator compatibility claims require evidence from the target compute node.

## Branding

The project uses the abbreviated `DSH` ecosystem identifier in its name. References to “DeepSeek Harness” are descriptive compatibility statements only. No official logo or other DeepSeek brand asset is distributed by this package.

The naming and attribution policy follows the [DeepSeek Harness brand guidelines](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.0-rc.8/BRAND_GUIDELINES.md).

## Versioning

The npm package version matches `skills/scnet-hpc/VERSION` and follows the same SemVer release
train as the source Skill. `@deepseek-ai/dsh-tools` is an optional peer dependency: DSH supplies
the runtime copy, while `devDependencies` provides the same host version for local validation only.

## License

This project is released under the [MIT License](LICENSE). Subject to the license terms, the software may be used, copied, modified, merged, published, sublicensed, and distributed, including for commercial purposes.

Redistributions must retain the copyright notice and the MIT license notice. The software is provided “as is,” without warranties of any kind; users are responsible for evaluating the suitability and risks of the bundle, skill instructions, cluster profiles, scripts, and generated outputs for their own environment.
