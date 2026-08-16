# 初步测试 dsh-scnet

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
| 1 | 用 scnet_list_clusters 看看有哪些集群 | 返回 `kseshell`、`zzeshell` | 只读 |
| 2 | 用 scnet_show_cluster 读一下 zzeshell | 返回该集群 profile | 只读 |
| 3 | 用 scnet_generate_job 生成一个 probe 作业 | 生成 `.slurm` 并给出上传命令 | 只写当前目录 |
| 4 | 用 scnet_setup_ssh 配置连接 | 需要真实私钥，会改 `~/.ssh` | 中 |
| 5 | 用 scnet_probe_cluster 探测集群 | 需要真实集群，会 SSH 到远端 | 中 |
| 6 | 用 scnet_refresh_cluster dry_run=true 刷新规则 | 输出即将写入的缓存，不落盘 | 中（会 SSH） |
| 7 | 用 scnet_run_compute_probe 跑计算节点探针 | 返回 PROBE_ 结果 | 高（提交作业并等待） |

第 4 至 7 步只有在你有私钥和目标集群时才测，测前确认副作用。
