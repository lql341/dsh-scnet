---
name: scnet-hpc
description: 在超算互联网（SCNet）集群上配置 SSH、使用 Slurm、申请 CPU/DCU 资源、提交和排查作业、安装依赖及验证国产加速器兼容性；当前深度验证以海光 DCU/DTK/gfx9xx 为主。Use for SCNet HPC tasks involving SSH setup, Slurm jobs, login versus compute nodes, CPU/DCU resource requests, Hygon DCU, DTK, gfx9xx, sbatch/srun, offline compute nodes, cluster profiles, or accelerator compatibility. Other SCNet accelerators must be verified on their target cluster.
---

# 国产超算集群使用规范

面向超算互联网（SCNet）系列集群，当前收录节点以海光 DCU 为主。其他芯片平台
只复用连接、调度和验证方法，不套用海光工具链结论。**集群参数不写在文档里，存在
`clusters/<集群短名>.conf`**，脚本从 profile 读取，所以同一套流程能用于多个集群。

## 先确认在跟哪个集群打交道

```bash
ls clusters/*.conf              # 有哪些集群
cat clusters/<集群短名>.conf     # 看具体参数
```

回答用户关于内存上限、分区名、硬件规格的问题时，**读 profile，不要凭记忆**。
不同集群的 `DEF_MEM_PER_CPU`、`PARTITION`、`MIN_GRES` 都不一样。

| 文件 | 用途 |
|---|---|
| `clusters/*.conf` | 每个集群一个 profile（连接、调度器、硬件、已知问题）|
| `clusters/_template.conf` | 新增集群的模板 |
| `scripts/setup-ssh.sh` | 新电脑上配连接（macOS/Linux，幂等）|
| `scripts/probe-cluster.sh` | 探测新集群，自动生成 profile |
| `scripts/refresh-cluster.sh` | 动态刷新已有集群的规则缓存 |
| `scripts/run-compute-probe.sh` | 在计算节点运行最小能力探针 |
| `scripts/new-job.sh` | 按 profile 生成合规的作业脚本 |
| `references/setup.md` | 连接配置详解、平台差异、故障排查 |
| `references/environment.md` | 环境栈、装依赖、目录约定、迁移注意 |
| `references/troubleshooting.md` | 排查手册、调试策略 |
| `references/adding-cluster.md` | 新增集群的完整步骤 |
| `references/hygon-dcu-development.md` | 海光 DCU 开发流程、DTK 工具库与官方资源索引 |
| `references/software-compatibility.md` | 国产超算上的软件兼容性排查、验证分层与公开报告脱敏 |
| `references/quickstart-en.md` | English quick start for SSH, Slurm, CPU/DCU jobs, and troubleshooting |

用户使用英文提问或需要英文操作说明时，读取 `references/quickstart-en.md`；集群具体
参数仍以 `clusters/*.conf` 为准，不从英文示例猜测。

## 换机器

本插件已随 DeepSeek Harness 安装，换机器时用 `dsh plugin --profile web add dsh-scnet` 重装即可。
配置集群连接：

```bash
./scripts/setup-ssh.sh --cluster <集群短名> <私钥文件> <用户名>
```

只有一个 profile 时可省略 `--cluster`；公开 profile 里的 `KEY_NAME_MARKER` 是占位符，所以需要显式传用户名。
## 新增集群

```bash
# 1. 手工确认能 ssh 上去（用平台给的私钥）
# 2. 探测，自动填大部分字段
./scripts/probe-cluster.sh <ssh别名> <集群短名> > clusters/<集群短名>.conf
# 3. 补齐探测不到的项（加速器型号、module 名等），profile 里有提示
```

完整步骤见 `references/adding-cluster.md`。

## 动态刷新已有集群规则

profile 里的 `SSH_HOST` / `SSH_PORT` 是固定连接参数，应写死在
`clusters/<集群短名>.conf`。其余容易随平台调整的规则
（`DEF_MEM_PER_CPU`、`MIN_GRES`、`PARTITION`、`NET_OK`、登录节点缺库等）
可以动态探测：

```bash
./scripts/refresh-cluster.sh --cluster <集群短名>          # 只做登录节点只读探测
./scripts/refresh-cluster.sh --cluster <集群短名> --compute # 再提交一个 10 分钟小作业
./scripts/refresh-cluster.sh --cluster <集群短名> --dry-run  # 只看结果，不写缓存
```

结果写到 `clusters/.cache/<集群短名>.auto.conf`，后续脚本会自动加载并覆盖
profile 中的同名字段。删除该缓存文件即可回退到纯 profile。生成作业时可用
`./scripts/new-job.sh --refresh ...` 先刷新再生成，或用 `--no-auto` 忽略缓存。

默认只做登录节点探测，不提交作业；`--compute` 才会到计算节点实测加速器架构、
FP8、Triton、bitsandbytes 和外网状态。

分区节点数 `NODE_COUNT` 是例外：每次加载集群时都会实时查询当前
`PARTITION` 的 `TotalNodes`，查不到才回退到 cache/profile。需要关闭时设
`SCNET_HPC_LIVE_NODE_COUNT=no`。

## 通用硬约束

以下几条在国产超算上普遍存在，**具体数值查 profile**。

### 1. 可能强制申请加速器

若 profile 里 `MIN_GRES` 非空，该集群的 QOS 强制每个作业至少申请那么多加速器，
**纯 CPU 作业会被拒**：

```
sbatch: error: min tres(gres/dcu) request 0 exceeds per-job max tres limit 1
sbatch: error: QOSMinGRES
```

哪怕作业根本不用 GPU（比如只读文件的探针），也要写 `--gres=<GRES_TYPE>:1`。

### 2. 内存上限 = `cpus-per-task × DEF_MEM_PER_CPU`

超了直接被拒（`too much memory was requested relative to the number of CPUs`）。
**要更多内存只能加 CPU 核数。**

用 `scripts/new-job.sh` 生成脚本可避免手算。以 `DEF_MEM_PER_CPU=3888` 为例：

| `--cpus-per-task` | 上限 | 安全写法 |
|---|---|---|
| 8 | 30.38 GB | `--mem=30gb` |
| 16 | 60.75 GB | `--mem=60gb` |
| 32 | 121.50 GB | `--mem=121gb` |

注意 `--mem` 只是请求量，cgroup 实际按 `cpus × DEF_MEM_PER_CPU` 给
——所以 `MaxRSS` 可能超过你写的 `--mem` 值。

### 3. 登录节点可能无法 import 深度学习框架

若 profile 的 `LOGIN_NODE_MISSING_LIBS` 非空，登录节点缺那些库，
即使 `module load` 之后也 import 不了：

```
ImportError: libmsgpackc.so.2: cannot open shared object file
```

**不要在登录节点试 torch 代码然后困惑为什么报错。** 哪怕只想看一眼 tensor 的
dtype，也要走 `srun` 或 `sbatch`。

登录节点通常用于 `git`、文件管理、`sacct`/`squeue` 和准备依赖；能否访问软件源、
下载模型或执行 `pip install` 必须查看 profile 的网络字段并现场确认。

### 4. 计算节点通常无外网 —— 依赖必须预装

profile 的 `NET_OK` / `NET_BLOCKED` 记录了登录节点的可达情况。计算节点若
`COMPUTE_NODE_OFFLINE=yes` 则完全无外网。

任何**运行时从网上拉东西**的库都会在计算节点炸掉。典型的是 `transformers` 的
`kernels` 机制（从 HF Hub 下载预编译 kernel）。作业脚本里先声明离线，
让失败快速且信息明确：

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

### 5. 测试任务的临时目录必须建在家目录

针对任何集群提交测试或探针任务时，**不要使用 `/tmp`，也不要从根目录下创建临时
目录**。统一在共享家目录中创建，例如 `$HOME/.scnet-hpc/tmp/$SLURM_JOB_ID`，并在
作业中导出 `TMPDIR`、`TMP`、`TEMP` 指向该目录。这样登录节点、计算节点和后续作业
都能访问同一份临时文件。任务结束后只清理本次作业自己的子目录。

`TMP_SHARED=no` 表示系统 `/tmp` 不作为跨节点共享路径使用；即使某个集群实测 `/tmp`
可见，测试脚本仍默认遵循上述家目录规则。

### 6. 先验证二进制兼容性，再做完整安装

遇到 Python/C++/GPU 软件安装问题时，先确认系统 ABI、manylinux 标签、编译器/DTK 版本和运行节点网络条件，再选择版本。不要只根据 pip/conda 能否解析依赖判断可用性；必须在目标计算节点完成最小 import、kernel、功能和端到端验证。

## 提交作业

```bash
./scripts/new-job.sh <作业名> [加速器数] [cpu数] [时长]
./scripts/new-job.sh probe                 # 1 卡, 8 核, 20 分钟
./scripts/new-job.sh infer 8 32 01:30:00   # 8 卡, 32 核, 1.5 小时
./scripts/new-job.sh --cpu-only build 0 32 01:00:00
```

有独立 CPU 分区时使用 `--cpu-only`，脚本读取 `PARTITION_CPU` 并省略 `--gres`；
临时指定其他分区时使用 `--partition <名称>`。

上传后先验证配额而不真排队：

```bash
ssh <集群> 'sbatch --test-only <脚本路径>'
```

返回 `Job N to start at <时间>` 表示配额合法；`Requested node configuration is
not available` 是当前无空闲节点（配额没问题）；`too much memory` 才是超配额。

### ★ 作业脚本末尾必须写 `exit $rc`

**这是最容易被骗的地方。** bash 里 Python 崩了之后 bash 继续执行后面的行，
作业以最后一条命令的退出码结束：

```
$ sacct -j <JOB_ID>
<JOB_ID> | example-job | COMPLETED | 0:0 | 00:34:32     ← 可能是假的！
```

而日志里 Python 早就抛异常了，甚至还打印了脚本末尾的 "COMPLETE" 字样。

**判断作业成功不能只看 `sacct` 的 State，必须读日志。**

## 交互式调试（推荐）

通常比反复提交完整作业更适合试代码、查环境和验证假设；实际排队时间取决于分区负载：

```bash
srun -p <分区> --gres=<类型>:1 --cpus-per-task=8 --mem=30gb --time=00:10:00 \
  bash -lc 'module load <模块>
    source ~/<venv>/bin/activate
    python3 -c "import torch; print(torch.__version__)"'

# 交互 shell
srun -p <分区> --gres=<类型>:1 --cpus-per-task=8 --mem=30gb \
  --time=00:30:00 --pty bash
```

节点忙时会排队，可以 Ctrl-C 放弃改用 sbatch。

**调试策略**：先用 2 分钟的小探针确认假设，再提交几十分钟的大作业。大模型加载
动辄半小时，靠大作业试错代价太高。分层验证见 `references/troubleshooting.md`。

## 常用命令

```bash
squeue -u $USER                      # 我的队列
squeue -j <ID> --start               # 预计启动时间
sacct -j <ID> --format=JobID,State%14,ExitCode,Elapsed,MaxRSS -P
scancel <ID>
sinfo -p <分区> -o "%n %c %m %G %t"   # 节点资源和状态
```

`MaxRSS` 只在作业结束后、且只在 `.batch` 子步骤那行有值。节点状态里
`drain`/`drng` 不可调度，实际可用常少于总数。

## 加速器能力边界

用户询问海光开发环境、HIP、数学库、通信库、性能分析、CUDA 迁移或容器部署时，
先读 `references/hygon-dcu-development.md`。用它定位官方资料，再以目标集群的
module、计算节点探针和 profile 为准；不要把网页当前版本直接覆盖到集群环境。

**不要假设加速器支持什么。** 即使同属 SCNet，不同芯片、DTK/驱动和框架版本的
能力也可能不同。先读取目标 profile 的 `KNOWN_LIMITATIONS`，再用计算节点探针验证
设备枚举、dtype、kernel、通信和真实功能。海光 DCU/DTK 的开发资料入口见
`references/hygon-dcu-development.md`；软件兼容性验证顺序见
`references/software-compatibility.md`。

## 排查失败

1. **先读日志，不要相信 `sacct` 的 State**
2. `.err` 被 `Loading weights: ...%` 进度条刷屏时，`grep -v` 过滤掉再看
3. 按报错分类：

| 报错 | 原因 |
|---|---|
| `QOSMinGRES` | 忘了 `--gres` |
| `too much memory` | 违反 `cpus × DEF_MEM_PER_CPU` |
| `lib*.so: cannot open shared object file` | 没 `module load`，或在登录节点跑了 |
| `Name or service not known` / `offline mode` | 计算节点在访问外网 |
| `hipDrvLaunchKernelEx` | Triton 不可用，换纯 PyTorch 路线 |
| `libgcvm.so.17git: cannot open shared object file` | Triton 在当前 DTK/DCU 栈不可用 |
| `python3: command not found` | 昆山计算节点需 `module load python/3.8.10` |
| `sacct` COMPLETED 但结果不对 | 脚本缺 `exit $rc` |

完整手册见 `references/troubleshooting.md`。

## 公开报告与知识沉淀

将集群实测结果写入公开报告或仓库前，保留环境、方法、版本、结果和限制，移除或替换以下信息：用户名、SSH 主机/端口、内部域名、IP、节点名、作业编号、绝对家目录和私有镜像地址。可用 `<USER_HOME>`、`<DTK_ROOT>`、`<CLUSTER_HOST>`、`已脱敏作业` 等占位符。

公开技术记录按“环境与版本 → 问题与证据 → 解决方法 → 验证结果 → 已知限制 →
可复用经验”组织。结论必须标明测试环境、验证范围和未验证边界；视觉样式由具体发布
项目决定，不写进本 skill。

详细的兼容性排查和报告模板见 `references/software-compatibility.md`。
