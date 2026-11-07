# SCNet OpenAPI backend

This backend follows the official SCNet OpenAPI 2.0 documentation reviewed on
2026-09-26:

- Overview: <https://www.scnet.cn/ac/openapi/doc/2.0/index.html>
- Recommended AK/SK authentication:
  <https://www.scnet.cn/ac/openapi/doc/2.0/api/safecertification/get-user-tokens-aksk.html>
- Job submission:
  <https://www.scnet.cn/ac/openapi/doc/2.0/api/jobmanager/job.html>
- Creating a directory:
  <https://www.scnet.cn/ac/openapi/doc/2.0/api/efile/folder-create.html>
- Chunked upload and merge:
  <https://www.scnet.cn/ac/openapi/doc/2.0/api/efile/chunk-upload.html>
  and <https://www.scnet.cn/ac/openapi/doc/2.0/api/efile/merge-file.html>

The local implementation intentionally normalizes large responses. Use `--raw` only when the
compact result is insufficient.

## Credentials

Get AK/SK from SCNet **个人中心 → 访问控制**; the downloaded file's `Accesskey` and `Secretkey`
columns are the AK and SK, and the username is the platform login. These differ from cluster/Linux
usernames and from model-service API keys. The step-by-step user briefing lives in
[first-use.md](first-use.md).

Official: <https://www.scnet.cn/ac/openapi/doc/2.0/index.html> ·
<https://www.scnet.cn/ac/openapi/doc/2.0/api/safecertification/get-user-tokens-aksk.html>

## Guided first-time setup

```bash
python3 scripts/scnet.py setup new --mode openapi     # macOS/Linux
python scripts/scnet.py setup new --mode openapi      # Windows PowerShell
```

Use `setup modify --mode openapi` to replace credentials. Copy one field at a time: platform user,
AccessKey, SecretKey; both key inputs are invisible, wrapping quotes are removed, and pasted shell
assignments or multiline values are rejected.

| Environment | Persistent AK/SK storage | Notes |
|---|---|---|
| macOS | Keychain, service `scnet-hpc-openapi` | Built-in `security`; allow access when prompted |
| Linux desktop | Secret Service, service `scnet-hpc-openapi` | Needs `libsecret-tools` **and** a running, unlocked keyring and session D-Bus |
| Linux headless / CI | Host-injected environment | Installing `libsecret-tools` alone does not create a workable keyring |
| Windows / WSL2 | Current user's Credential Manager (WSL2: inside WSL2 only) | Windows and WSL2 do not share stores |

Saving is optional and verified by reading the item back; if it fails the panel records
`not_saved` instead of claiming success. `setup status` shows metadata and the credential source
the current process actually sees; `setup reset` can delete the store item separately.

### Environment injection

Set all three (a partial set is rejected so two accounts cannot be mixed); environment values
override the system store, so clear stale overrides after saving replacements.

```bash
export SCNET_OPENAPI_USER="<platform-user>"
export SCNET_OPENAPI_ACCESS_KEY="<access-key>"
export SCNET_OPENAPI_SECRET_KEY="<secret-key>"
python3 scripts/scnet.py --backend openapi doctor
```

PowerShell: same three names as `$env:SCNET_OPENAPI_USER`, `$env:SCNET_OPENAPI_ACCESS_KEY`,
`$env:SCNET_OPENAPI_SECRET_KEY`. They last only for that session and its children, so prefer the
wizard and Credential Manager for daily use; do not use plaintext shell profiles, `setx`, or
checked-in env files. Commands containing secrets may land in shell history.

For an externally managed token, or to override discovery:

```bash
export SCNET_OPENAPI_TOKEN="<region-token>"       # requires SCNET_OPENAPI_REGION_ID
export SCNET_OPENAPI_REGION_ID="<region-id>"
export SCNET_OPENAPI_AUTH_BASE="https://api.scnet.cn"
export SCNET_OPENAPI_CENTER_URL="https://www.scnet.cn/ac/openapi/v2/center"
export SCNET_OPENAPI_SCHEDULER_ID="<scheduler-id>"
export SCNET_OPENAPI_USERNAME="<region-user>"
```

The client signs the canonical AK/timestamp/user JSON with HMAC-SHA256, and reuses region tokens
from a permission-restricted disk cache for up to four hours. Region IDs, users, schedulers and
home paths are cached as non-secret metadata. Interactive terminals support ↑/↓ plus Enter and
direct numeric selection; SecretKey entry never echoes characters.

Never put these values in a prompt, profile, repository file, generated report, or shell trace.
Use the host's credential store or secret injection when available.

## Read-only operations

```bash
python3 scripts/scnet.py --backend openapi clusters
python3 scripts/scnet.py --backend openapi --region <id> queues
python3 scripts/scnet.py --backend openapi --region <id> limits
python3 scripts/scnet.py --backend openapi --region <id> job <job-id>
python3 scripts/scnet.py --backend openapi --region <id> \
  logs --path /absolute/path/std.out.123 --lines 200
python3 scripts/scnet.py --backend openapi --region <id> \
  files --path /absolute/path
python3 scripts/scnet.py --backend openapi --region <id> quota
```

If a region exposes multiple schedulers, add `--scheduler-id`.

`limits` here means **your user/account quota**, not partition capacity: `--partition` is
rejected on purpose. Partition node counts, free resources and max walltime come from `queues`;
SSH `limits --partition` additionally reports TRES, QoS and `DefMemPerCPU`. `quota` returns the
shared-storage threshold and usage. `logs` is a paged file-service read (`--page`, `--host-name`).

## Mutations

Create a remote directory:

```bash
python3 scripts/scnet.py --backend openapi --region <id> \
  mkdir /absolute/work/dir --parents
```

OpenAPI submission uses the documented BASIC/BASE command mode. Extra scheduler directives can
be repeated:

```bash
python3 scripts/scnet.py --backend openapi --region <id> submit \
  --name probe --queue debug --work-dir /absolute/work/dir \
  --command $'module load ...\npython3 probe.py' \
  --nodes 1 --cpus 8 --dcus 1 --walltime 00:10:00 \
  --scheduler-option '#SBATCH --account=example'
```

Other mutations:

```bash
python3 scripts/scnet.py --backend openapi --region <id> cancel <job-id>
python3 scripts/scnet.py --backend openapi --region <id> \
  upload local.file /absolute/remote/directory
python3 scripts/scnet.py --backend openapi --region <id> \
  download /absolute/remote/file local.file
```

Downloads refuse to replace an existing local path unless `--cover` is supplied. They stream to a
temporary file and rename it into place, so a large or interrupted transfer neither fills memory
nor truncates an existing target. Uploads send
`uncover` by default and require `--cover` for replacement.

For uploads, the second argument is always a remote **directory**, not a complete filename.
The uploaded filename comes from the local file. For example, uploading `mesh.bin` to
`/public/home/alice/mesh` creates `/public/home/alice/mesh/mesh.bin`; passing
`/public/home/alice/mesh.bin` as the second argument asks the API to use `mesh.bin` as a
directory name.

List active or historical jobs without supplying a job ID:

```bash
python3 scripts/scnet.py --backend openapi --region <id> \
  jobs --scope active --limit 20
python3 scripts/scnet.py --backend openapi --region <id> \
  jobs --scope history --days 30 --limit 20
```

`job <job-id>` checks the realtime endpoint first and automatically falls back to the filtered
history-list endpoint. The caller does not need to provide `acctTime`.

Account and resource summaries are read-only:

```bash
python3 scripts/scnet.py --backend openapi --region <id> account
python3 scripts/scnet.py --backend openapi --region <id> resource-summary
```

Wait for a job with a bounded timeout:

```bash
python3 scripts/scnet.py --backend openapi --region <id> \
  wait <job-id> --wait-timeout 300 --interval 10
```

Region tokens are cached under `${XDG_CACHE_HOME:-~/.cache}/scnet-hpc` when that location is
writable. Cache locking or writes are best-effort; an unavailable cache never blocks an OpenAPI
operation.

Uploads larger than 8 MiB automatically use the documented burst/merge flow. Override the
threshold and chunk size with `--chunk-size <bytes>`; use `--chunk-size 0` to force ordinary
multipart upload. The current implementation keeps one chunk in memory at a time.

Preview a mutation without contacting the backend:

```bash
python3 scripts/scnet.py --backend openapi --region <id> --dry-run \
  submit --name probe --queue debug --work-dir /absolute/work/dir \
  --command 'echo hello' --cpus 1 --dcus 1
```

Do not automatically retry submission or cancellation after a timeout. Query job state first:
the public documentation does not establish an idempotency key for submission.

## Known validation boundaries

- The implementation is validated locally for parsing, signing, routing, normalization, and the
  external-backend contract. Live OpenAPI operations still require testing against each
  authorized SCNet region.
- The official cancellation page describes one method value in prose and uses `5` in all request
  examples. The client defaults to `5`; override it with `SCNET_OPENAPI_CANCEL_METHOD` if a live
  region requires a different documented value.
- Small ordinary uploads buffer one file in memory; large uploads use chunked transfer.
- OpenAPI does not replace SSH for module discovery, environment construction, compilation,
  interactive `srun`, performance profiling, or low-level scheduler diagnosis.
- API success is determined by both HTTP transport and the JSON `code`; HTTP 200 alone is not
  sufficient.
- History lookups use the filtered `/historyjobs` list. The `/historyjobs/{scheduler}/{job}`
  detail endpoint needs `acctTime` and can exceed a two-minute timeout without it.
- Submit sends `GAP_NPROC` as total cores (`--cpus` per node × `--nodes`) because the API also
  defines `GAP_PPN`; `GAP_NDCU`, `GAP_NGPU` and `GAP_JOB_MEM` are per node.

## Compact output and waiting

Default job output includes ID, state, queue, and available exit code or failure reason.
Empty fields are omitted; zero and false are retained. Use `--details` for all normalized
fields and `--raw` for backend data. `--json` retains its envelope with compact formatting;
`--dry-run` always retains the complete preview. Consumers needing the previous complete
CLI payload must pass `--details`; SDK/backend return schemas are preserved.

```bash
python3 scripts/scnet.py --region <id> job <job-id>
python3 scripts/scnet.py --details --region <id> job <job-id>
python3 scripts/scnet.py --region <id> wait <job-id> --interval 3 --wait-timeout 180
```

`wait` polls internally and emits only the final result or timeout summary. OpenAPI live
`COMPLETED` can also describe a recently cancelled job: until accounting confirms the state,
output reports `FINALIZING`. Waiting may therefore include accounting update latency.
Transfers return the target path and byte count; logs return only the requested lines.
