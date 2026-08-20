# Testing

[简体中文](./testing.zh-CN.md)

Run checks in increasing order of side effects.

## 1. Static package validation

```sh
npm install --no-package-lock --ignore-scripts
npm run validate
npm pack --dry-run
```

This validates the package manifest, JavaScript entry point, sync script, and packaged shell scripts.

## 2. Install the packed artifact

```sh
mkdir -p .release
npm pack --pack-destination .release
dsh plugin --profile test-scnet add ./.release/dsh-scnet-*.tgz
dsh --profile test-scnet --dump-config
```

Confirm that the composed configuration includes:

```text
- id: scnet-skill-filesystem
- id: scnet
```

## 3. Read-only tool checks

| Tool | Expected result |
| --- | --- |
| `scnet_list_clusters` | Returns the packaged cluster identifiers |
| `scnet_show_cluster` | Returns the selected profile contents |
| `scnet_generate_job` | Writes a profile-aware Slurm script in the current directory |

Check both accelerator and CPU-only job generation. Review the output for the selected partition, memory, and GRES rules.

## 4. Local state changes

`scnet_setup_ssh` writes under `~/.ssh`. Run it only with a real SCNet key, an explicit cluster, and a confirmed username. Review the resulting host entry and connection test.

## 5. Remote read-only checks

`scnet_probe_cluster` and `scnet_refresh_cluster` require a working SSH connection. Use `dry_run=true` where supported and review the proposed profile data before persisting it.

## 6. Scheduler-consuming checks

`scnet_run_compute_probe` and refresh operations with compute probing submit Slurm jobs. Confirm the target cluster, account policy, accelerator count, CPU count, and time limit before execution.

## Cleanup

Remove the isolated test profile after verification:

```sh
dsh plugin --profile test-scnet remove dsh-scnet
```

Delete generated `.slurm` files and `.release/` artifacts when they are no longer needed.
