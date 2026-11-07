- Run concurrent agent sessions under different OpenAPI accounts with `--account` /
  `SCNET_OPENAPI_ACCOUNT`; each alias keeps its own secure-store item and region defaults and
  never falls back to another account.
- Register independent SSH aliases for an existing cluster, so several Linux users on one region
  can be configured without editing repository profiles.
- `setup --mode ssh` no longer changes the saved default backend.
