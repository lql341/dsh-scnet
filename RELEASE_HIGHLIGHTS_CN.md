- OpenAPI `limits` 拒绝 `--partition`（它是账户配额），并指路 `queues`——分区节点数、空闲资源
  与最长时长本来就在 `queues` 里。
- SSH `limits` 默认只报告 `AllowAccounts` 数量（完整列表留给 `--raw`），不再把上千个无关
  用户名塞进正常输出。
- 去掉 Slurm `%P` 的右对齐补位，使 `queues`/`job` 在 SSH 与 OpenAPI 下输出一致；归一化作业
  时保留合法的 0 卡 GPU/DCU 计数。
- OpenAPI 下载改为经临时文件流式落盘，不再把整个文件读进内存；SSH `scp` 传输使用长超时，
  避免 `--timeout 30` 掐断大文件传输。
- 修正 `SSH_PORT` 解析顺序（profile 未写端口时改用 `~/.ssh/config`），给远端 `scontrol` 参数
  加引号，为探针作业号增加校验，并停止为 CPU-only 作业骨架生成加速器探针。
- 新增 `quota` 操作（两个 backend 语义一致），并修正多节点提交的总核心数，使申请的 CPU/DCU
  与调度器实际分配一致。
