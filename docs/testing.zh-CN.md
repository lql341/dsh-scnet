# 初步测试 DSH-SCNet

按风险从低到高验证插件是否正常工作。

## 1. 环境准备

```sh
node -v                              # 需要 ≥ 22.19
npm install -g @deepseek-ai/dsh
dsh --version
```

## 2. 安装插件

```sh
dsh plugin --profile web add dsh-scnet
```

## 3. 启动

```sh
dsh web
# 浏览器打开 http://127.0.0.1:3080
```

## 4. 确认插件已加载

```sh
dsh --profile web --dump-config | grep -A2 scnet
```

应能看到：

```text
- id: scnet
  name: dsh-scnet
```

## 5. 配置 DeepSeek API Key

Web UI 里：`设置 → 模型 → DeepSeek 卡片填 Key 并保存`。

或编辑 `~/.dsh/.credentials.yaml`：

```yaml
DEEPSEEK_API_KEY: sk-你的key
```

## 6. 会话内测工具

| 顺序 | 测试话术 | 预期 | 风险 |
|---|---|---|---|
| 1 | 用 scnet_list_clusters 看看有哪些集群 | 返回 `kseshell`、`wuzhshell`、`xianshell`、`zzeshell` | 只读 |
| 2 | 用 scnet_show_cluster 读一下 zzeshell | 返回该集群 profile | 只读 |
| 3 | 用 scnet_generate_job 生成一个 probe 作业 | 生成带 GRES 的 `.slurm` 并给出上传命令 | 只写当前目录 |
| 3a | 用 scnet_generate_job 在 kseshell 生成 cpu_only 构建作业 | 使用 `kshcnormal` 且不含 `--gres` | 只写当前目录 |
| 4 | 用 scnet_setup_ssh 配置连接 | 需要真实私钥，会改 `~/.ssh` | 中 |
| 5 | 用 scnet_probe_cluster 探测集群 | 需要真实集群，会 SSH 到远端 | 中 |
| 6 | 用 scnet_refresh_cluster dry_run=true 刷新规则 | 输出即将写入的缓存，不落盘 | 中（会 SSH） |
| 7 | 用 scnet_run_compute_probe 跑计算节点探针 | 返回 PROBE_ 结果 | 高（提交作业并等待） |
| 8 | 用 scnet_status 查看当前配置 | 返回脱敏配置 | 只读 |
| 9 | 用 scnet_openapi_regions 查看授权区域 | 返回区域且不含 token | 只读 |
| 10 | 用 scnet_job_queues 查看昆山队列 | 返回实时队列和空闲资源 | 只读 |
| 11 | 用 scnet_job_list 列出当前或历史作业 | 返回紧凑作业记录 | 只读 |
| 12 | 用 scnet_limits 查询资源限制 | 返回用户和调度器限制 | 只读 |
| 13 | 用 scnet_submit_job（dry_run=true）预览一次提交 | 返回将要发送的请求，不真正提交 | 只读（dry_run） |
| 14 | 用 scnet_submit_job 提交一个 5 秒小作业 | 返回 job_id、作业目录与日志路径 | 高（会消耗配额） |
| 15 | 用 scnet_job_show 查该 job_id | 返回状态与 stdout/stderr 路径 | 只读 |
| 16 | 用 scnet_job_logs 读该作业日志 | 返回日志内容（同时验证 path 与 job_id+work_dir 两种模式结果一致） | 只读 |
| 17 | 用 scnet_job_cancel 取消一个作业 | 建议先用 dry_run=true 预览 | 高（变更） |
| 18 | 用 scnet_file_list 查看默认目录 | 返回共享存储文件 | 只读 |
| 19 | 用 scnet_file_transfer 传输一个文件 | 默认不覆盖目标 | 有副作用 |
| 20 | 用 scnet_notebook_regions 查看区域 | 返回 Notebook 可用区域 | 只读 |
| 21 | 用 scnet_notebook_resources 查看昆山资源 | 返回 CPU/GPU/DCU 资源 | 只读 |
| 22 | 用 scnet_notebook_list 查看实例 | 返回脱敏实例列表 | 只读 |

第 4 至 7 步只有在你有私钥和目标集群时才测，测前确认副作用。

第 14、17 步是变更操作，会真实占用或释放调度器资源：先用 `dry_run=true` 预览，确认返回里的
目标区域/集群，并且**不要在提交超时后盲目重试**（平台没有幂等键），先查作业状态。

Notebook 创建、启动、停止和释放没有作为 DSH deterministic tool 暴露。此类操作通过
Skill CLI 执行，并先使用 `--dry-run`。
