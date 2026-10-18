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

Obtain AK/SK from the SCNet website:

1. Sign in to SCNet.
2. Open **Personal Center / 个人中心**.
3. Open **Access Control / 访问控制**.
4. Generate and download the authorization file containing AccessKey and SecretKey.

Use the platform username for `user`, the downloaded file's `Accesskey` column for AK,
and its `Secretkey` column for SK. Copy each value separately, without column labels or shell
assignments. These credentials differ from both cluster/Linux usernames and model-service API keys.
For the initial user briefing and commands that work outside the Skill directory, read
[first-use.md](first-use.md).

Official instructions:
<https://www.scnet.cn/ac/openapi/doc/2.0/api/safecertification/get-user-tokens-aksk.html>

## Guided first-time setup

Run `python3 scripts/scnet.py setup new --mode openapi` on macOS/Linux, or
`python scripts/scnet.py setup new --mode openapi` in Windows PowerShell.
Use `setup modify --mode openapi` to replace credentials for an existing setup.

Copy only each field's value, one at a time: platform login user, AccessKey, then SecretKey.
The cluster/Linux username is discovered later and may differ. Both key inputs are invisible;
surrounding quotes are removed, while pasted shell assignments, multiline values, and invisible
characters are rejected with a retry. The wizard does not display either key.

| Environment | Where persistent AK/SK are stored | Dependency and recovery |
|---|---|---|
| macOS | Login user's Keychain, service `scnet-hpc-openapi` | Built-in `security`; allow access/unlock when prompted; find the item in Keychain Access |
| Linux desktop | Secret Service, service `scnet-hpc-openapi` | Ubuntu/Debian: `sudo apt install libsecret-tools`; a running, unlocked keyring and session D-Bus are also needed |
| Linux headless / CI | Host-injected environment | No `libsecret-tools` required for API calls; installing the package alone does not create a working keyring |
| Native Windows | Current user's Windows Credential Manager, Generic Credential `scnet-hpc-openapi` | Built in; manage through Control Panel > Credential Manager > Windows Credentials |
| WSL2 | Linux credentials inside WSL2 | Windows Credential Manager and Windows environment changes are not automatically shared |

Saving is optional and happens after authentication. A saved item is read back before persistence is
reported as verified. If saving fails or is declined, **region setup is not credential persistence**:
the panel records `not_saved` and explains how to provide credentials for subsequent commands.
Use `setup status` for metadata and the actual credential source visible to the current process;
use `doctor --no-network` for local checks or `doctor` for a read-only connection check.
`setup reset` can delete the credential-store item separately from region metadata.

### Environment injection

Set all three variables together. A partial set is rejected instead of mixing one account's
username/key with another account's saved credential set. Environment values take precedence over
the system store; clear stale overrides after saving replacement credentials.

Bash/Zsh, in the same terminal that will launch the client:

```bash
export SCNET_OPENAPI_USER="<platform-user>"
export SCNET_OPENAPI_ACCESS_KEY="<access-key>"
export SCNET_OPENAPI_SECRET_KEY="<secret-key>"
```

PowerShell, in the same window that will launch the client:

```powershell
$env:SCNET_OPENAPI_USER = "<platform-user>"
$env:SCNET_OPENAPI_ACCESS_KEY = "<access-key>"
$env:SCNET_OPENAPI_SECRET_KEY = "<secret-key>"
python scripts/scnet.py --backend openapi doctor
```

These `$env:` assignments last only for the current PowerShell session and its subsequently launched
children. Already-running desktop applications do not receive them. Prefer the interactive wizard and
Windows Credential Manager for daily desktop use. Do not use plaintext shell profiles, `setx`, or
checked-in environment files as the default credential store. Commands containing real secrets may
be recorded in shell history; host-managed secret injection avoids manual command entry.

To stop overriding the store in PowerShell:

```powershell
Remove-Item Env:SCNET_OPENAPI_USER,Env:SCNET_OPENAPI_ACCESS_KEY,Env:SCNET_OPENAPI_SECRET_KEY -ErrorAction SilentlyContinue
```

The client signs the canonical AK/timestamp/user JSON with HMAC-SHA256 when requesting
region tokens. Tokens are reused from a permission-restricted disk cache for up to four hours
when available; an expired or unavailable cache triggers authentication. The setup panel can store the
platform credential set in macOS Keychain, Linux Secret Service, or Windows Credential Manager; otherwise use environment
variables. Region IDs, region users, schedulers, and home paths are discovered and cached as
non-secret metadata.

Interactive terminals support ↑/↓ plus Enter and direct numeric selection. Press Enter without
typing a number to accept the current/default item. SecretKey input is intentionally invisible.
This behavior is the same in macOS Terminal/iTerm2 and Ubuntu/Debian terminals.
Ubuntu/Debian users can install `secret-tool` with `sudo apt install libsecret-tools`.

For an externally managed token:

```bash
export SCNET_OPENAPI_TOKEN="<region-token>"
export SCNET_OPENAPI_REGION_ID="<region-id>"
```

Optional overrides:

```bash
export SCNET_OPENAPI_AUTH_BASE="https://api.scnet.cn"
export SCNET_OPENAPI_CENTER_URL="https://www.scnet.cn/ac/openapi/v2/center"
export SCNET_OPENAPI_SCHEDULER_ID="<scheduler-id>"
export SCNET_OPENAPI_USERNAME="<region-user>"
```

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
```

If a region exposes multiple schedulers, add `--scheduler-id`.

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

Downloads refuse to replace an existing local path unless `--cover` is supplied. Uploads send
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
