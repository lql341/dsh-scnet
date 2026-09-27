---
name: scnet-hpc
description: Configure or operate SCNet HPC through SSH, OpenAPI, and pluggable future backends.
---

# SCNet HPC

Use the selected backend, cluster profile, and target-cluster evidence. SSH is the default;
OpenAPI is the structured control plane. Never silently switch backends.

## First use and selection

- Run `scripts/setup.sh new|modify|status|reset` for explicit configuration lifecycle.
- Advanced OpenAPI discovery: `python3 scripts/scnet.py setup`.
- Read-only preflight: `python3 scripts/scnet.py doctor`.
- Backend precedence: `--backend`, `SCNET_HPC_BACKEND`, saved setup choice, profile
  `DEFAULT_BACKEND`, then `ssh`.
- Read `clusters/<cluster>.conf` before reporting static facts. Treat
  `clusters/.cache/<cluster>.auto.conf` as optional, time-sensitive SSH probe data.
- With multiple profiles, require an explicit cluster before access changes, installation,
  job generation, or submission. Query the selected backend for live queues, limits, and state.
- SSH setup is profile-scoped; record usernames and key expiry metadata per profile. OpenAPI
  credentials are platform-scoped and discover all authorized regions/schedulers automatically.
- OpenAPI may enable multiple regions locally, but every mutating operation must resolve to one
  explicit/default target region.

Read [references/backends.md](references/backends.md) for backend selection and extension.
Read [references/openapi.md](references/openapi.md) for OpenAPI credentials and limits.

## Route only as needed

- SSH access: `references/setup.md`
- Python/modules/offline dependencies: `references/environment.md`
- Scheduler/runtime/accelerator diagnosis: `references/troubleshooting.md`
- Add or refresh profiles: `references/adding-cluster.md`
- Hygon DCU/DTK/HIP/profiling: `references/hygon-dcu-development.md`
- Compatibility reports: `references/software-compatibility.md`
- English instructions: `references/quickstart-en.md`

Read only the selected profile and references needed for the current operation. Profile values
override examples.

## Boundaries and evidence

- Read-only inspection and local generation do not authorize remote mutation.
- Resolve backend, target, paths, command, and expected effect before submit, cancel, upload,
  download, overwrite, deletion, or SSH configuration. Never silently retry submission.
- Compute probes consume scheduler resources; run them only when requested or required for
  target-node evidence.
- Keep credentials, tokens, personal paths, internal hosts, nodes, job IDs, and private mirrors
  out of profiles and public reports.
- Preserve existing SSH configuration; use `scripts/setup-ssh.sh` for bounded changes.
- Respect profile-specific partition, GRES, memory, walltime, offline-network, and shared-storage
  constraints. Propagate workload exit status.
- Distinguish profile values, live scheduler state, login-node evidence, compute-node evidence,
  and inference. Treat Hygon guidance as architecture/toolchain-specific.

## Stable entrypoints

- `scripts/setup.sh`: first-use configuration panel.
- `python3 scripts/scnet.py ...`: backend-neutral operations, dry-run, raw output, and doctor.
- `python3 scripts/scnet.py notebook ...`: Notebook discovery and confirmation-driven
  lifecycle operations. Use `--dry-run` before create/start/stop/release.
- `scripts/new-job.sh`: profile-aware Slurm generation.
- `scripts/refresh-cluster.sh`: SSH-derived profile refresh.
- `scripts/probe-cluster.sh`: initial profile creation.
- `scripts/run-compute-probe.sh`: bounded accelerator probe.

Use compact normalized output by default. Request raw backend data only for diagnosis.
