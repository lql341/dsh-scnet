- 通过 `--account` / `SCNET_OPENAPI_ACCOUNT` 让并发的 agent 会话使用不同 OpenAPI 账号：
  每个别名的凭据条目与区域默认值彼此独立，且不会回退到其他账号。
- 可为同一集群登记独立的 SSH 别名，多个 Linux 用户在一个区域内并行工作，无需改动仓库 profile。
- `setup --mode ssh` 不再顺带修改已保存的默认 backend。
