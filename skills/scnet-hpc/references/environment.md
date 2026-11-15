# 集群环境

具体参数在 `clusters/<集群短名>.conf`，本文讲通用方法。

## 读取和核验集群参数

```bash
cat clusters/<集群短名>.conf
```

任务依赖当前状态时，执行现场核验：

```bash
ssh <集群> 'scontrol show partition <分区>'     # DefMemPerCPU / MaxTime / TotalNodes
ssh <集群> 'sinfo -p <分区> -o "%n %c %m %G %t"'  # 每节点 CPU/内存/GRES/状态
ssh <集群> 'sacctmgr show qos where name=<QOS名> format=Name,MinTRES%30,MaxTRES%30 -P'
```

也可使用动态刷新脚本，登录节点只读探测不会提交作业：

```bash
./scripts/refresh-cluster.sh --cluster <集群短名> --dry-run
```

其中分区节点数 `NODE_COUNT` 默认每次加载集群时实时查询 `TotalNodes`。

节点状态含义：`idle` 空闲、`mix` 部分占用、`alloc` 全占、`drain`/`drng` 不可调度
（维护中）。实际可用节点常少于总数。

**登录节点常有负载均衡**，两次 `hostname` 结果可能不同。这不影响使用（家目录共享），
但如果在某台登录节点起了后台进程，下次登录可能落到另一台看不到它。

## 加速器软件栈

国产超算的加速器 SDK 通常通过 module 加载。先从 profile 读取实际模块组合，
不要从其他集群复制模块名或版本：

```bash
module load <MODULE_LOADS>
```

DTK 是海光对 ROCm 的发行版，含 HIP、编译器、运行时、数学库和通信库。它复用部分
ROCm API，但库名、版本和可用能力仍由目标 DTK 决定。资料入口和 ROCm 复用边界见
[`hygon-dcu-development.md`](hygon-dcu-development.md)。

列出可用模块：

```bash
ssh <集群> 'module avail 2>&1'
```

## Python 环境

### 本地脚本解释器

Linux Desktop 可将随包 Python 的绝对路径注入本地脚本：

```bash
export DSH_SCNET_PYTHON=/path/to/bundled/python
# 通用环境也可使用：
export SCNET_PYTHON=/path/to/python3
```

`DSH_SCNET_PYTHON` 优先于 `SCNET_PYTHON`。脚本会验证解释器确实是 Python 3；
未注入时才按 `python3`、`python` 顺序探测。该设置只影响本机的 OpenAPI CLI 和作业
脚本生成，不会把本机解释器路径传到远端计算节点。

超算通常没有系统级的 torch，用 venv 或 conda env。profile 的 `DEFAULT_VENV`
记录默认环境路径（相对家目录）。

```bash
module load <MODULE_LOADS>                       # 必须先 load
source ~/<DEFAULT_VENV>/bin/activate
```

必须先加载工具链模块，再激活 Python 环境；否则，`import torch` 会报缺共享库：

```
ImportError: libgalaxyhip.so.5: cannot open shared object file
```

如果计算节点没有 `python3`，先使用 profile 中的 `PYTHON_MODULE`：

```bash
module load <PYTHON_MODULE>
```

字段为空时，再用 `module avail` 选择 Python 3 模块，并在计算节点验证
`command -v python3`。不要把某个集群的 Python module 名当作全局默认值。

## 厂商预编译的 wheel

国产加速器的 torch 等框架需要厂商适配版，文件名带厂商标记。海光示例：

```
torch-2.7.1+das.opt1.dtk2604-cp312-...whl
flash_attn-2.8.3+das.opt1.dtk2604.torch271-...whl
```

`+das.opt1.dtk2604` 表示针对 DTK 26.04 编译。**不要用 PyPI 的通用版覆盖这些**
——通用版是 CUDA 或上游 ROCm 编译的，在国产加速器上跑不起来。装其他包时如果
pip 想升级 torch，加 `--no-deps` 阻止。

## 装依赖

当计算节点无外网时，在具备网络访问的登录节点准备依赖：

```bash
source ~/<venv>/bin/activate
pip install -i <PIP_INDEX> <包名>
```

`PIP_INDEX` 在 profile 里。镜像选择以 profile 和现场可达性为准。

安装后在目标计算节点验证（登录节点可能 import 不了框架）：

```bash
srun -p <分区> --gres=<类型>:1 --cpus-per-task=8 --mem=30gb --time=00:05:00 \
  bash -lc 'module load <模块>
    source ~/<venv>/bin/activate
    python3 -c "import <包名>; print(\"ok\")"'
```

## 下载模型

profile 的 `NET_BLOCKED` 记录了不可达的站点。国内超算通常 `huggingface.co`
不通，用 modelscope：

```bash
python3 -c "
from modelscope import snapshot_download
snapshot_download('<repo>', cache_dir='/public/home/$USER/models/_ms_cache')
"
```

若 ModelScope 首次下载结果不完整或只保留 `.lock` 文件，可使用
`allow_patterns` 单独补：

```python
snapshot_download(repo, cache_dir=..., allow_patterns=["inference/*", "*.json"])
```

下载后核验所需文件、数量和校验信息。

## 家目录布局约定

```
models/                所有模型权重
scripts/               作业脚本
├── lib/               可复用的 Python 模块（作业里通过 PYTHONPATH 引用）
├── probes/            诊断/探针脚本
├── deprecated/        已确认走不通的路线（隔开避免误用）
└── logs/              作业日志（所有 #SBATCH --output 指向这里）
softwares/             代码、venv、编译产物
├── projects/          各项目工作目录
└── _archive/          历史日志、一次性脚本
```

让所有 `#SBATCH --output` 指向 `scripts/logs/`，否则日志会散落在提交目录。

## 迁移环境目录

**移动含 venv / conda env 的目录前，检查 `bin/` 下的 shebang。** conda 把解释器
绝对路径写死在 `pip`、`torchrun` 等入口点第一行，直接移动会报 bad interpreter：

```bash
cd <env>/bin
for f in *; do
  head -c2 "$f" 2>/dev/null | grep -q '^#!' || continue
  head -1 "$f" | grep -q "<旧路径>" && sed -i "1s|<旧路径>|<新路径>|" "$f"
done
```

迁移后验证入口脚本和环境前缀：

```bash
<新路径>/bin/python -c "import sys; print(sys.prefix)"
<新路径>/bin/pip --version
```

同时检查作业脚本里的硬编码路径（`#SBATCH --output`、`source .../activate`、
`PYTHONPATH`）。

## 磁盘

```bash
df -h ~                    # 文件系统使用情况
du -sh */ | sort -h        # 各目录体积（大目录很慢，考虑放后台）
```

`df` 显示的是**整个文件系统**的容量，不一定是你的个人配额。查个人配额要用
平台特定的命令（如 `lfs quota`）或看控制台。

模型权重是主要占用，几个大模型就是几百 GB。
