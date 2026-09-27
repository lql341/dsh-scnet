# SCNet backend selection and extension

The skill separates cluster intent from transport. SSH and OpenAPI are built in; future MCP
servers, platform connectors, and site-specific gateways can be added without changing the
task-level commands.

## Selection

Backend precedence:

1. `--backend <name>`;
2. `SCNET_HPC_BACKEND`;
3. saved setup-panel `default_backend`;
4. selected profile `DEFAULT_BACKEND`;
5. `ssh`.

Do not silently fall back between backends. A failed OpenAPI request must not become an SSH
submission, and a failed SSH command must not be replayed through OpenAPI. Replaying mutations
can duplicate jobs or apply them to a different region.

List registered implementations and their declared capabilities:

```bash
python3 scripts/scnet.py backends
python3 scripts/scnet.py --backend <name> capabilities
```

Built-in capability summary:

| Domain / operation | SSH | OpenAPI |
|---|---:|---:|
| Local profiles / authorized regions | yes | yes |
| Queues and limits | yes | yes |
| Job status and logs | yes | yes |
| Submit and cancel | yes | yes |
| Upload and download | yes | yes |
| Create remote directory | no | yes |
| Arbitrary remote command | yes | no |
| Modules, builds, interactive diagnosis | yes | no |
| Notebook read-only discovery | no | yes |

Use OpenAPI for structured control-plane work. Use SSH for environment setup, compilation,
interactive inspection, full scheduler tooling, and operations not represented by a structured
backend.

## Common CLI

On a new computer, start with the dependency-light Bash panel:

```bash
./scripts/setup.sh
python3 scripts/scnet.py doctor
```

Configuration lifecycle:

```bash
./scripts/setup.sh new
./scripts/setup.sh modify
./scripts/setup.sh status
./scripts/setup.sh reset
```

`new` adds a connection without replacing an existing profile/account. `modify` preserves
unrelated configuration. `status` is read-only. `reset` is scoped and does not remove real SSH
keys or `~/.ssh/config` unless that is performed separately and explicitly.

Use `./scripts/setup.sh --skip-connect` when only local selections should be saved. The Bash
panel can be rerun to update a profile's SSH user/key metadata. OpenAPI uses one platform
credential set and discovers regions, users, schedulers, and home paths automatically; no region
ID is required during setup.
Developers
can use `python3 scripts/scnet.py setup` for live OpenAPI region discovery. Both panels store no
secrets; provide OpenAPI credentials through a host credential manager or environment injection.

Region selection is multi-select for local enablement, followed by a single default region.
Mutating operations remain single-region by design.

Global options must appear before the operation:

```bash
python3 scripts/scnet.py --backend ssh --cluster <profile> queues
python3 scripts/scnet.py --backend openapi --region <region-id> limits
python3 scripts/scnet.py --backend openapi --region <region-id> job <job-id>
```

Use `--dry-run` before a mutation to inspect the normalized action without contacting the
backend:

```bash
python3 scripts/scnet.py --backend openapi --dry-run \
  submit --name smoke --queue debug --work-dir /absolute/work/dir \
  --command 'echo hello'
```

Mutating examples:

```bash
python3 scripts/scnet.py --backend ssh --cluster <profile> \
  submit --remote-path /absolute/path/job.slurm

python3 scripts/scnet.py --backend openapi --region <region-id> submit \
  --name probe --queue debug --work-dir /absolute/work/dir \
  --command 'python3 probe.py' --dcus 1 --cpus 8 --walltime 00:10:00
```

The CLI does not interpret a command as authorization. Follow the skill's mutation boundaries
before invoking submit, cancel, upload, download, or `exec`.

## External backend protocol

An external backend is an executable named:

```text
scnet-hpc-backend-<name>
```

Discover it either by:

- placing it in a directory listed by `SCNET_HPC_BACKEND_PATH`; or
- placing it on `PATH` and listing `<name>` in `SCNET_HPC_EXTERNAL_BACKENDS`.

The router writes one JSON request to standard input:

```json
{
  "protocol": "scnet-hpc.backend",
  "protocol_version": 1,
  "operation": "queues",
  "profile_name": "example",
  "profile": {},
  "options": {}
}
```

The executable returns one JSON object:

```json
{
  "ok": true,
  "protocol_version": 1,
  "data": []
}
```

It must implement the `capabilities` operation and return:

```json
{"ok": true, "protocol_version": 1, "data": {"capabilities": ["clusters", "queues"]}}
```

Return `{"ok": false, "error": "..."}` for a bounded failure. Never print credentials or tokens
to standard output or standard error.

## MCP and connector integration

If an official SCNet MCP server becomes available, prefer its native tools when the host exposes
them and the user has selected or authorized that connection. Keep the same normalized operation
semantics: clusters, queues, limits, job, logs, submit, cancel, files, upload, and download.

For hosts that cannot expose MCP tools directly, use a small
`scnet-hpc-backend-mcp` bridge implementing the protocol above. Platform connectors can use the
same adapter pattern. Do not hard-code speculative MCP tool names, schemas, or authentication
until the official interface is available and verified.

## Profiles

Profiles may contain non-secret backend hints:

```bash
DEFAULT_BACKEND="ssh"
OPENAPI_REGION_ID=""
OPENAPI_SCHEDULER_ID=""
OPENAPI_USERNAME=""
```

Keep AK, SK, tokens, cookies, and passwords out of profiles.
