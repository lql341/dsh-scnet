<h1 align="center">dsh-scnet</h1>

<p align="center">在 DeepSeek Harness 里操作超算互联网（scnet.cn）及同类国产超算集群：配 SSH、生成 Slurm 作业、探测/刷新集群、运行计算节点探针、排查失败，附海光 DCU/DTK 知识。</p>

## 这是什么

一个 DeepSeek Harness bundle 插件，把 `scnet-hpc` 的 Agent Skill 和 bash 脚本包装成 DSH 可安装包。装好后 DSH 模型在涉及超算集群、Slurm 作业、海光 DCU/DTK 时会加载对应 skill，并可调用工具完成确定性操作。

## 安装

推荐从 npm 安装：

```sh
dsh plugin --profile web add dsh-scnet
```

git 源、本地目录安装以及验证步骤见 [INSTALL.md](./INSTALL.md)。

## 能力面

### Skills

| Skill | 作用 |
|---|---|
| scnet-hpc | 国产超算使用规范：连接、提交/监控、调试、失败排查、海光 DCU/DTK 资源索引 |

### 内置集群

| 短名 | 描述 | 加速器 |
|---|---|---|
| zzeshell | 超算互联网 · 郑州 | 海光 BW1000 DCU (gfx936) ×8, 64GB/卡 |
| kseshell | 超算互联网 · 昆山 | 海光 Z100 DCU (gfx906) ×4, 16GB/卡 |
| wuzhshell | 超算互联网 · 乌镇 | 海光 Z100 DCU (gfx906) ×4, 16GB/卡 |

### Tools

| 工具 | 说明 |
|---|---|
| scnet_list_clusters | 列出已配置的集群 profile |
| scnet_show_cluster | 读取指定集群的完整参数 |
| scnet_generate_job | 按 profile 生成合规 Slurm 作业脚本 |
| scnet_setup_ssh | 配置本地到集群的 SSH 连接 |
| scnet_probe_cluster | 探测新集群并生成 profile |
| scnet_refresh_cluster | 动态刷新已有集群的规则缓存 |
| scnet_run_compute_probe | 在计算节点运行最小能力探针 |

## 文档

- [INSTALL.md](./INSTALL.md) — 安装与验证
- [TESTING.md](./TESTING.md) — 按风险排序的初步测试步骤

## 结构

```
.
├── package.json          # dsh.bundle + dsh.skills
├── cordis.patch.yml      # bundle 组合层
├── index.mjs             # Cordis 入口，注册 7 个工具
├── skills/scnet-hpc/
│   ├── clusters/
│   │   ├── zzeshell.conf
│   │   ├── kseshell.conf
│   │   └── wuzhshell.conf
│   ├── scripts/
│   └── references/
├── sync.sh               # 从 canonical 仓库同步
├── README.md             # 项目说明
├── INSTALL.md            # 安装与验证
├── TESTING.md            # 初步测试步骤
├── LICENSE
└── .gitignore
```

## 同步

本仓库是发布面，知识内容（`skills/scnet-hpc/` 下的 SKILL.md、clusters、references、scripts）从 canonical 仓库 `lql341/scnet-hpc` 同步：

```sh
./sync.sh                   # 默认 ../skills/scnet-hpc
./sync.sh --src /path/to/scnet-hpc
```

只改 canonical，本仓库跑 sync 更新；不要把 `skills/scnet-hpc/` 当手工维护目录。
`sync.sh` 会自动排除 `scripts/install.sh` 和 `clusters/.cache/`，避免把安装脚本或本机动态缓存打进发布包。

## 隐私与安全

- 仓库不含私钥、token、用户名、密钥指纹。
- `scnet_setup_ssh` 会写入 `~/.ssh/`，调用前确认私钥路径和集群。
- `scnet_generate_job` 生成的 `.slurm` 可能含本机用户名，`.gitignore` 已排除。
- 集群主机名/端口是平台公开信息，由 canonical 仓库维护。
- `scnet_refresh_cluster` / `scnet_run_compute_probe` 会 SSH 到远端并可能提交作业；运行前确认集群和副作用。
- `clusters/.cache/` 是本机动态探测缓存，`.gitignore` 已排除，不应提交。

## License

MIT
