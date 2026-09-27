# Notebook service

Notebook is a separate SCNet OpenAPI service domain. It reuses platform authentication and
region discovery, but it is not a Slurm job and does not use `hpcUrls`.

Read-only commands:

```bash
python3 scripts/scnet.py --backend openapi notebook regions
python3 scripts/scnet.py --backend openapi --region <id> notebook resources
python3 scripts/scnet.py --backend openapi --region <id> notebook images
python3 scripts/scnet.py --backend openapi --region <id> notebook list
python3 scripts/scnet.py --backend openapi --region <id> notebook show <notebook-id>
python3 scripts/scnet.py --backend openapi --region <id> notebook url <notebook-id>
```

The default output redacts SSH passwords and URL query credentials. Use `--reveal` only when
the user explicitly needs a URL to open, and do not place the resulting value in reports or
long-lived logs.

Lifecycle commands:

```bash
python3 scripts/scnet.py --dry-run --backend openapi \
  notebook create --region <id>
python3 scripts/scnet.py --backend openapi \
  notebook create --region <id>
python3 scripts/scnet.py --backend openapi \
  notebook start <id> --region <id>
python3 scripts/scnet.py --backend openapi \
  notebook stop <id> --region <id>
python3 scripts/scnet.py --backend openapi \
  notebook release <id> --region <id>
```

`create` automatically chooses the smallest currently available resource and the smallest
trusted preset Jupyter image. Advanced users may override the resource group or image ID.

`smoke` performs a bounded lifecycle:

```bash
python3 scripts/scnet.py --dry-run --backend openapi \
  notebook smoke --region <id>
python3 scripts/scnet.py --backend openapi \
  notebook smoke --region <id>
```

It creates one minimal Notebook, waits for `Running`, validates the redacted Jupyter URL, then
stops and releases the instance in a cleanup block.

Mutations require interactive confirmation. Non-interactive callers must pass `--yes`. Release
requires the Notebook ID in interactive mode because it is irreversible.

Official API sections:

- Notebook resource discovery;
- image discovery;
- instance list/detail;
- Jupyter URL lookup;
- instance lifecycle.
