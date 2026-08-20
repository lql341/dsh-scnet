# DSH-SCNet

[简体中文](./README_CN.md)

DSH-SCNet (`dsh-scnet` on npm) is a community-maintained DSH bundle for operating Supercomputing Network (SCNet) clusters. It packages the canonical [`scnet-hpc`](https://github.com/lql341/scnet-hpc) skill, profile-aware shell utilities, and seven deterministic tools for SSH setup, Slurm job generation, cluster discovery, and compute-node diagnostics.

> This is an independent community project. It is compatible with DeepSeek Harness but is not an official DeepSeek product and does not imply endorsement, partnership, or authorization by DeepSeek.

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
- Generated Slurm files may include local usernames and are ignored by Git.
- Accelerator compatibility claims require evidence from the target compute node.

## Branding

The project uses the abbreviated `DSH` ecosystem identifier in its name. References to “DeepSeek Harness” are descriptive compatibility statements only. No official logo or other DeepSeek brand asset is distributed by this package.

The naming and attribution policy follows the [DeepSeek Harness brand guidelines](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.0-rc.8/BRAND_GUIDELINES.md).

## License

This project is released under the [MIT License](LICENSE). Subject to the license terms, the software may be used, copied, modified, merged, published, sublicensed, and distributed, including for commercial purposes.

Redistributions must retain the copyright notice and the MIT license notice. The software is provided “as is,” without warranties of any kind; users are responsible for evaluating the suitability and risks of the bundle, skill instructions, cluster profiles, scripts, and generated outputs for their own environment.
