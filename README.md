# DSH-SCNet

[简体中文](./README_CN.md)

DSH-SCNet (`dsh-scnet` on npm) is a community-maintained DSH bundle for operating Supercomputing Network (SCNet). It packages the source [`scnet-hpc`](https://github.com/lql341/scnet-hpc) Skill, profile-aware utilities, and bounded tools for SSH, Slurm, OpenAPI files, regional resources, and Notebook discovery.

Current release: **0.6.13**

<!-- scnet-release:start -->
## 0.6.13 highlights

- Recover malformed Windows credential entries with actionable, redacted guidance.
- Print absolute follow-up commands that work from any directory, with shell-appropriate quoting.
- Synchronize first-use preparation checklists into both distribution READMEs and clarify
  native Windows OpenAPI support, with regression coverage for both layouts.
<!-- scnet-release:end -->

> This is an independent community project. It is compatible with DeepSeek Harness but is not an official DeepSeek product and does not imply endorsement, partnership, or authorization by DeepSeek.

<!-- scnet-onboarding:start -->
## What to prepare for first use

Start with **OpenAPI** for queries and standard job management. Add SSH when you need remote
compilation, environment installation, or shell commands.

| Connection | Required inputs | Where to obtain them |
| --- | --- | --- |
| OpenAPI (default) | Platform username, AK, SK | Sign in to SCNet > Personal Center / 个人中心 > Access Control / 访问控制 > generate and download the authorization file. Use its `Accesskey` and `Secretkey` columns. |
| SSH (as needed) | Target cluster, cluster/Linux username, private-key file path | Select the region in the console > Command Line E-Shell / 命令行 E-Shell > SSH Connection / SSH 连接 at top left. Download the key and check host/port; verify the username with `whoami` in that region's web E-Shell. |

Your account needs access to the target region. Prepare credentials for the chosen connection;
explanations and offline preparation require none. **Enter AK/SK only in your own terminal's hidden
prompts. For SSH, supply a local file path. Keep keys and private-key contents out of chat.**

Ask your agent to help configure scnet-hpc for the first time. The Skill explains the inputs and
their sources before providing a local command for your OS and actual installation directory.
See the [first-use checklist](skills/scnet-hpc/references/first-use.md).
<!-- scnet-onboarding:end -->

## Requirements

- Node.js 22.19 or later
- DeepSeek Harness (`dsh`)
- Linux or macOS for native shell execution
- Native Windows supports Python OpenAPI and Windows Credential Manager; use WSL2 for automatic SSH installation and Bash workflows
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

Release order is canonical-to-downstream: update the canonical `VERSION` and release highlights once. CI synchronizes both distribution repositories. After each synchronized pull request passes validation, the workflow merges it automatically. The resulting `main` push validates and packs the bundle, publishes the npm package with the appropriate `latest` or `next` tag, and creates the matching Git tag and GitHub Release. Do not bump only `package.json`: the canonical `VERSION` remains the release source of truth.

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
