<h1 align="center">dsh-scnet</h1>

<p align="center">在 DeepSeek Harness 里操作超算互联网（scnet.cn）及同类国产超算集群：配 SSH、生成 Slurm 作业、探测集群、排查失败，附海光 DCU/DTK 知识。</p>

## 这是什么

一个 DeepSeek Harness 官方 bundle 插件，把 `scnet-hpc` 的 Agent Skill 和 bash 脚本包装成 DSH 可安装包。装好后 DSH 模型在涉及超算集群、Slurm 作业、海光 DCU/DTK 时会加载对应 skill，并可调用工具完成确定性操作。

## 安装

```sh
dsh plugin --profile web add "github:lql341/dsh-scnet#main"
```

或本地目录：

```sh
git clone https://github.com/lql341/dsh-scnet.git
cd dsh-scnet
dsh plugin --profile web add .
```

> git 源安装会取源码而非构建产物；本插件入口是纯 JavaScript（无编译步骤），无需 allowBuilds。

## 能力面

### Skills

| Skill | 作用 |
|---|---|
| scnet-hpc | 国产超算使用规范：连接、提交/监控、调试、失败排查、海光 DCU/DTK 资源索引 |

### Tools

| 工具 | 说明 |
|---|---|
| scnet_list_clusters | 列出已配置的集群 profile |
| scnet_show_cluster | 读取指定集群的完整参数 |
| scnet_generate_job | 按 profile 生成合规 Slurm 作业脚本 |
| scnet_setup_ssh | 配置本地到集群的 SSH 连接 |
| scnet_probe_cluster | 探测新集群并生成 profile |

## 结构

```
.
├── package.json          # dsh.bundle + dsh.skills
├── cordis.patch.yml      # bundle 组合层
├── index.mjs             # Cordis 入口，注册 5 个工具
├── skills/scnet-hpc/     # Agent Skill + clusters/scripts/references
├── sync.sh               # 从 canonical 仓库同步
└── README.md
```

## 同步

本仓库是发布面，知识内容（`skills/scnet-hpc/` 下的 SKILL.md、clusters、references、scripts）从 canonical 仓库 `lql341/scnet-hpc` 同步：

```sh
./sync.sh                   # 默认 ../skills/scnet-hpc
./sync.sh --src /path/to/scnet-hpc
```

只改 canonical，本仓库跑 sync 更新；不要把 `skills/scnet-hpc/` 当手工维护目录。

## 隐私与安全

- 仓库不含私钥、token、用户名、密钥指纹。
- `scnet_setup_ssh` 会写入 `~/.ssh/`，调用前确认私钥路径和集群。
- `scnet_generate_job` 生成的 `.slurm` 可能含本机用户名，`.gitignore` 已排除。
- 集群主机名/端口是平台公开信息；profile 中连接字段默认留空，由用户本地填写。

## License

MIT
