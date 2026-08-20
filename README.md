# DSH-SCNet

[English](#english) | [简体中文](#简体中文)

## English

DSH-SCNet (`dsh-scnet` on npm) is a community-maintained DSH bundle for operating Supercomputing Network (SCNet) clusters. It packages the canonical [`scnet-hpc`](https://github.com/lql341/scnet-hpc) skill, profile-aware shell utilities, and seven deterministic tools for SSH setup, Slurm job generation, cluster discovery, and compute-node diagnostics.

> This is an independent community project. It is compatible with DeepSeek Harness but is not an official DeepSeek product and does not imply endorsement, partnership, or authorization by DeepSeek.

## Requirements

- Node.js 22.19 or later
- DeepSeek Harness (`dsh`)
- Linux or macOS for native shell execution
- Windows through WSL2; native Windows execution is not supported by the bundled Bash scripts
- An SCNet account and cluster credentials for remote operations

## Install

```sh
dsh plugin --profile web add dsh-scnet
```

Then verify that the bundle layer is present:

```sh
dsh --profile web --dump-config
```

See [Installation](./docs/installation.md) for npm, GitHub, and local-checkout workflows.

## Included capabilities

| Component | Purpose |
| --- | --- |
| `scnet-hpc` skill | Profile-based operating guidance for SSH, Slurm, offline compute nodes, and accelerator validation |
| `scnet_list_clusters` | List packaged cluster profiles |
| `scnet_show_cluster` | Read a selected profile before reporting resource constraints |
| `scnet_generate_job` | Generate profile-aware accelerator or CPU-only Slurm scripts |
| `scnet_setup_ssh` | Configure a local SSH key and host entry with explicit user confirmation |
| `scnet_probe_cluster` | Produce an initial profile from read-only login-node probes |
| `scnet_refresh_cluster` | Refresh time-sensitive profile fields; compute probing is opt-in |
| `scnet_run_compute_probe` | Submit a minimal compute-node capability probe |

Packaged profiles currently cover Zhengzhou, Kunshan, Wuzhen, and Xi'an SCNet environments. Cluster specifications and scheduler policies remain profile-specific and should be verified against the target environment.

## Bundle structure

```text
.
├── package.json
├── cordis.patch.yml
├── index.mjs
├── skills/scnet-hpc/
│   ├── SKILL.md
│   ├── clusters/
│   ├── references/
│   └── scripts/
├── scripts/validate-package.mjs
├── docs/
├── sync.sh
└── .github/workflows/
```

The package is a DSH bundle: `package.json` declares `dsh.bundle.patch`, and `cordis.patch.yml` mounts both the tool plugin and the packaged skill directory through `@deepseek-ai/dsh-skill-filesystem`.

## Source synchronization

The `skills/scnet-hpc/` directory is generated from the canonical `scnet-hpc` repository:

```sh
./sync.sh --src ../scnet-hpc
```

Do not maintain the generated directory independently. The sync excludes the canonical installer and local probe cache because neither belongs in the npm runtime package.

## Validation

```sh
npm install --no-package-lock --ignore-scripts
npm run validate
npm pack --dry-run
```

See [Testing](./docs/testing.md) for local package installation and risk-ordered runtime checks.

## Security boundaries

- The repository and npm package must not contain private keys, tokens, usernames, private endpoints, or local probe caches.
- SSH configuration, remote probes, and Slurm submission are state-changing operations and require an explicit target and user authorization.
- Generated Slurm files may include local usernames and are ignored by Git.
- Accelerator compatibility claims require evidence from the target compute node.

## Branding

The project uses the abbreviated `DSH` ecosystem identifier in its name. References to “DeepSeek Harness” are descriptive compatibility statements only. No official logo or other DeepSeek brand asset is distributed by this package.

The naming and attribution policy follows the [DeepSeek Harness brand guidelines](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.0-rc.8/BRAND_GUIDELINES.md).

## License

This project is released under the [MIT License](LICENSE). Subject to the license terms, the software may be used, copied, modified, merged, published, sublicensed, and distributed, including for commercial purposes.

Redistributions must retain the copyright notice and the MIT license notice. The software is provided “as is,” without warranties of any kind; users are responsible for evaluating the suitability and risks of the bundle, skill instructions, cluster profiles, scripts, and generated outputs for their own environment.

---

## 简体中文

[English](#english) | [简体中文](#简体中文)

<p align="center">在 DeepSeek Harness 里操作超算互联网（SCNet）集群：配 SSH、生成 CPU/DCU Slurm 作业、探测/刷新集群、运行计算节点探针、排查失败，附海光 DCU/DTK 知识和英文快速指南。</p>

> 本项目是独立维护的社区项目，与 DeepSeek Harness 兼容，但不是 DeepSeek 官方产品，也不表示 DeepSeek 对本项目提供背书、合作或授权。

## 这是什么

一个 DeepSeek Harness bundle 插件，把 `scnet-hpc` 的 Agent Skill 和 bash 脚本包装成 DSH 可安装包。装好后 DSH 模型在涉及超算集群、Slurm 作业、海光 DCU/DTK 时会加载对应 skill，并可调用工具完成确定性操作。

## 安装

推荐从 npm 安装：

```sh
dsh plugin --profile web add dsh-scnet
```

git 源、本地目录安装以及验证步骤见[安装说明](./docs/installation.zh-CN.md)。

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
| xianshell | 超算互联网 · 西安 | 海光 Z100 DCU (gfx906) ×4, 16GB/卡 |

### Tools

| 工具 | 说明 |
|---|---|
| scnet_list_clusters | 列出已配置的集群 profile |
| scnet_show_cluster | 读取指定集群的完整参数 |
| scnet_generate_job | 按 profile 生成加速器或 CPU-only Slurm 作业，支持显式分区覆盖 |
| scnet_setup_ssh | 配置本地到集群的 SSH 连接 |
| scnet_probe_cluster | 探测新集群并生成 profile |
| scnet_refresh_cluster | 动态刷新已有集群的规则缓存 |
| scnet_run_compute_probe | 在计算节点运行最小能力探针 |

## 文档

- [安装说明](./docs/installation.zh-CN.md)
- [测试说明](./docs/testing.zh-CN.md)

## 结构

```
.
├── package.json          # dsh.bundle manifest
├── cordis.patch.yml      # bundle 组合层
├── index.mjs             # Cordis 入口，注册 7 个工具
├── skills/scnet-hpc/
│   ├── clusters/
│   │   ├── zzeshell.conf
│   │   ├── kseshell.conf
│   │   ├── wuzhshell.conf
│   │   └── xianshell.conf
│   ├── scripts/
│   └── references/
├── sync.sh               # 从 canonical 仓库同步
├── README.md             # 英文默认说明
├── README_CN.md          # 中文说明
├── docs/                # 中英文安装与测试文档
├── LICENSE
└── .gitignore
```

## 同步

本仓库是发布面，知识内容（`skills/scnet-hpc/` 下的 SKILL.md、clusters、references、scripts）从 canonical 仓库 `lql341/scnet-hpc` 同步：

```sh
./sync.sh                   # 当前本机布局默认 ../../skills/scnet-hpc
./sync.sh --src /path/to/scnet-hpc
```

只改 canonical，本仓库跑 sync 更新；不要把 `skills/scnet-hpc/` 当手工维护目录。
`sync.sh` 会自动排除 `scripts/install.sh` 和 `clusters/.cache/`，避免把安装脚本或本机动态缓存打进发布包。

## 隐私与安全

- 仓库不含私钥、token、用户名、密钥指纹。
- `scnet_setup_ssh` 会写入 `~/.ssh/`，调用前确认私钥路径和集群。
- `scnet_generate_job` 生成的 `.slurm` 可能含本机用户名，`.gitignore` 已排除。
- SSH 接入端点仅使用平台面向用户公开提供的信息，由 canonical 仓库维护。
- `scnet_refresh_cluster` / `scnet_run_compute_probe` 会 SSH 到远端并可能提交作业；运行前确认集群和副作用。
- `clusters/.cache/` 是本机动态探测缓存，`.gitignore` 已排除，不应提交。

## License

本项目采用 [MIT License](LICENSE) 开源。除许可证正文另有规定外，使用者可以自由使用、复制、修改、合并、发布、再许可和销售本项目及其衍生作品。

再发布本项目或其重要组成部分时，应保留版权声明和 MIT 许可声明。本项目按“现状”提供，不对适销性、特定用途适用性或不侵权作任何明示或默示保证；使用者应自行评估 DSH bundle、skill 说明、集群配置、脚本和生成结果在其环境中的适用性与风险。

项目命名与归属声明遵循 [DeepSeek Harness 品牌素材使用规范](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.0-rc.8/BRAND_GUIDELINES.zh.md)。
