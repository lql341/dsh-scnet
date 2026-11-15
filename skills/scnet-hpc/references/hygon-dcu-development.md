# 海光 DCU 开发与 ROCm 复用索引

本索引面向海光 DCU 上的开发、迁移、调优和集群验证。先选海光官方资料，再按需查
ROCm 上游文档；不以 ROCm 的“支持”声明推断 DTK/DCU 的实际能力。

## 先分清资料边界

| 名称 | 在本仓库中的含义 | 不能混用为 |
|---|---|---|
| SourceFind | 海光光合开发者社区及资源入口 | 某个已安装的软件包 |
| DTK | 海光面向 DCU 发布的开发套件，包含 HIP、编译器、运行时、数学库、通信库和分析工具 | AMD ROCm 的原样副本 |
| DAS | DCU 应用软件栈/资源库，提供框架适配、推理组件和算子库等上层软件 | 性能分析器或调试器 |
| ROCm | AMD 的上游 GPU 软件生态，可用于理解共同 API 和通用方法 | 与当前 DTK 版本一一对应 |
| `+das.*.dtk*` | 海光适配包的版本标记，例如 `torch-...+das.opt1.dtk2604` | 已安装 DAS 或某个固定版本 |
| `gfx` target | 计算节点实际暴露的 DCU 目标架构 | 可以从网页型号名称安全推断的常量 |

海光驱动、VBIOS、DTK 安装、支持的操作系统和 DCU 型号组合，以 SourceFind 当前产品选择
结果为准。已安装软件和计算节点探针的结果优先于本页链接中的示例。

## 按任务选入口

| 任务 | 首选资料 | 补充资料 | 验收证据 |
|---|---|---|---|
| 新机器/新系统部署 | [DCU 操作指南](https://developer.sourcefind.cn/developer-channel) | [DTK 文档目录](https://download.sourcefind.cn:65024/1/main/latest/Document)、目标版本安装手册 | `module list`、编译器版本、`rocminfo` |
| 编写 HIP 程序 | [DTK 资源页](https://developer.sourcefind.cn/dtk)中的对应版本 HIP/DCC 手册 | [HIP 编程模型](https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html)、[运行时 API](https://rocm.docs.amd.com/projects/HIP/en/latest/reference/hip_runtime_api_reference.html) | 最小 kernel 编译并运行 |
| 迁移 CUDA 工程 | DTK 资源页中的 GPUfusion/CUDA 兼容资料 | [HIP 移植指南](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_porting_guide.html)、[HIPIFY](https://rocm.docs.amd.com/projects/HIPIFY/en/latest/) | 构建通过且数值/边界测试通过 |
| 使用数学库 | DTK 目标版本中的 rocBLAS、FFT、SPARSE、SOLVER 等手册 | [ROCm 核心库总索引](https://rocm.docs.amd.com/en/latest/components/core.html) | 数据类型、布局、精度和数值结果测试 |
| 多卡/跨节点通信 | DTK 目标版本中的 RCCL、DUSHMEM 手册 | [RCCL 上游文档](https://rocm.docs.amd.com/projects/rccl/en/latest/) | 拓扑检查、集合通信和失败重试测试 |
| PyTorch/JAX/TensorFlow、vLLM、MIGraphX | [DAS 资源库](https://developer.sourcefind.cn/das)及组件详情 | 组件版本约束中的 DTK、Python、PyTorch 和 DCU 型号矩阵 | 导入成功、设备可见、最小前向/推理成功 |
| 性能分析与调试 | DTK 资源页中的性能分析、调试器和监控器资料 | [Compute Profiler](https://rocm.docs.amd.com/projects/rocprofiler-compute/en/latest/)、[Systems Profiler](https://rocm.docs.amd.com/projects/rocprofiler-systems/en/latest/)、[ROCgdb](https://rocm.docs.amd.com/projects/ROCgdb/en/latest/) | 可重复的 trace/metric、时间范围和运行命令 |
| 容器部署 | [DCU 操作指南](https://developer.sourcefind.cn/developer-channel)中的容器步骤 | [镜像仓库](https://harbor.sourcefind.cn:5443/) | 容器内设备映射、驱动/用户态兼容和 smoke test |
| 查安装与适配问题 | [文档中心](https://developer.sourcefind.cn/document/) | [SourceFind 论坛](https://forum.sourcefind.cn/)、[DAP](https://dap.sourcefind.cn/) | 完整版本、最小复现和计算节点输出 |

SourceFind 的 [DCU 上手指南](https://developer.sourcefind.cn/gitbook/dcu_tutorial/index.html)
适合按产品、系统版本走完整安装流程；它可能跳转统一登录，因此不适合作为无人值守脚本入口。

## 海光核心资源

以下入口是索引层，具体安装包和手册从页面中的产品/版本选择进入。

| 资源 | 用途 |
|---|---|
| [DCU 操作指南](https://developer.sourcefind.cn/developer-channel) | 选择 DCU 产品、操作系统和版本；驱动、VBIOS、DTK、DAS、容器部署 |
| [DTK 资源页](https://developer.sourcefind.cn/dtk) | DTK 软件栈、版本动态、教程、文档和常见问题 |
| [DTK 下载目录](https://download.sourcefind.cn:65024/1/main) | 按 DTK 版本选择安装包和同版本 `Document` 目录 |
| [DTK 最新文档目录](https://download.sourcefind.cn:65024/1/main/latest/Document) | 浏览最新版手册；实际环境应回到已安装版本 |
| [DAS 资源库](https://developer.sourcefind.cn/das) | 框架适配、推理引擎、算子库、版本约束和组件安装说明 |
| [文档中心](https://developer.sourcefind.cn/document/) | 官方文档检索；部分页面要求浏览器会话或登录 |
| [DAP](https://dap.sourcefind.cn/) | 开发与适配平台入口 |
| [DCU 上手指南](https://developer.sourcefind.cn/gitbook/dcu_tutorial/index.html) | 面向产品与系统的入门安装教程 |
| [SourceFind 论坛](https://forum.sourcefind.cn/) | 运行时、编译器、数学库和适配问题的社区检索 |

## DAS 软件栈

DAS 不是 Profiler。当前 [DAS 资源库](https://developer.sourcefind.cn/das) 主要承载 DCU
适配的框架、推理和算子组件，例如 PyTorch/JAX/TensorFlow 适配包、vLLM、MIGraphX 和
Lightop。旧的 `das.sourcefind.cn:55011/portal/` 链接目前会重定向到该资源库。

使用 DAS 组件时遵守以下顺序：

1. 在 DAS 资源库按组件名称检索，打开详情并确认其 DTK、Python、PyTorch 和 DCU 型号约束。
2. 先通过 `module list`、`rocminfo` 和框架探针确认底层 DTK/设备环境，再安装上层组件。
3. 选择与已安装 DTK 完全对应的 `+das.*.dtk*` 包，不从 PyPI 通用 wheel 覆盖厂商适配版。
4. 把组件版本约束视为安装和验证资料，不要在索引中复制会快速失效的完整版本表。

## 可复用的 ROCm 资料

ROCm 文档适合查通用编程语义、API 形态、库接口和方法论。涉及 DTK 安装、可用性、目标
架构、精度支持、工具命令和性能数字时，仍以海光版本的文档及目标节点实测为准。

| 范围 | 入口 | 复用方式 |
|---|---|---|
| HIP 总入口 | [HIP documentation](https://rocm.docs.amd.com/projects/HIP/en/latest/) | 学习语言、运行时、教程和错误模型 |
| 系统学习/离线阅读 | [AMD ROCm Programming Guide](https://rocm-handbook.amd.com/projects/amd-rocm-programming-guide/en/latest/) | 按专题串联 HIP、库、工具和优化方法；具体 API 仍回到版本化组件文档 |
| 编程模型 | [HIP programming model](https://rocm.docs.amd.com/projects/HIP/en/latest/understand/programming_model.html) | 线程、内存层级、kernel 和同步概念通常可迁移 |
| 运行时 API | [HIP Runtime API](https://rocm.docs.amd.com/projects/HIP/en/latest/reference/hip_runtime_api_reference.html) | 查接口语义；确认 DTK 头文件和运行时实际提供该 API |
| CUDA 迁移 | [Porting guide](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_porting_guide.html)、[CUDA-to-HIP API](https://rocm.docs.amd.com/projects/HIP/en/latest/reference/api_syntax.html)、[HIPIFY](https://rocm.docs.amd.com/projects/HIPIFY/en/latest/) | 概念和机械转换可复用；GPUfusion、编译器和目标架构以海光资料为主 |
| 性能方法 | [Performance guidelines](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/performance_guidelines.html) | 复用测量、访存、占用率和同步分析方法，不照搬 AMD GPU 指标或调优结论 |
| 数学/通信库 | [ROCm Core SDK components](https://rocm.docs.amd.com/en/latest/components/core.html)、[RCCL](https://rocm.docs.amd.com/projects/rccl/en/latest/) | 用总索引查 API；库名、版本、数据类型、拓扑和经验调优以 DTK 为准 |
| 设备与拓扑 | [rocminfo](https://rocm.docs.amd.com/projects/rocminfo/en/latest/) | 理解输出结构；设备名称、`gfx` target 和拓扑必须在目标计算节点确认 |
| 调试与分析 | [ROCgdb](https://rocm.docs.amd.com/projects/ROCgdb/en/latest/)、[Compute Profiler](https://rocm.docs.amd.com/projects/rocprofiler-compute/en/latest/)、[Systems Profiler](https://rocm.docs.amd.com/projects/rocprofiler-systems/en/latest/) | 复用调试思路和 profiling 概念；工具是否随 DTK 提供、命令和 metric 要实测 |
| 环境变量 | [ROCm environment variables](https://rocm.docs.amd.com/en/latest/reference/environment-variables/index.html) | 作为变量语义参考；不要绕过 module/厂商运行时长期堆叠全局变量 |

### 不要直接套用的内容

- AMD ROCm 的安装命令、发行版包源、驱动组合和产品兼容矩阵。
- ROCm 的 AMD GPU 架构、ISA、CU/SIMD 数量、显存和互联拓扑资料。
- “最新 ROCm 支持某 API”直接推导为“当前 DTK 和 DCU 支持该 API”。
- 上游 Profiler 的启动参数、可用 counter、输出字段和性能基线。
- 未在目标节点验证的 Triton、FP8、INT8、融合算子、通信算法或框架后端。

DTK 的版本可能对应不同的 ROCm 上游基线。先看 DTK 发布说明确认对应关系，再打开同版本
ROCm 文档；`latest` 和 `docs-*` 不能自动视为当前 DTK 的 API 契约。

## 最小环境与框架探针

在目标计算节点确认软件来源和实际设备，不要只检查登录节点或安装目录：

```bash
module list
command -v dcc || true
command -v hipcc || true
command -v rocminfo || true
hipcc --version || true
rocminfo || true
python -c 'import torch; print("torch", torch.__version__, "available", torch.cuda.is_available(), "count", torch.cuda.device_count()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "device unavailable")'
```

记录 `module list`、编译器版本、`rocminfo` 的设备名/`gfx` target、PyTorch 版本和 DAS
包后缀。这些字段足以区分驱动、DTK、目标架构和上层框架适配问题。

故障分流时先保持一个明确的 module/运行时组合：

- `rocminfo` 无设备更像驱动、设备权限或运行环境问题。
- `rocminfo` 正常但 HIP 编译失败，查 DTK 编译器、目标架构和安装完整性。
- HIP 可运行但 PyTorch 设备不可见，查 DAS/框架 wheel、Python 和 DTK 版本匹配。
- 应用能运行但缺少上游 API 或算子，查当前 DTK 基线和厂商适配能力。
- 只有 Profiler 失败时，查 DTK 工具可用性和目标设备/counter 支持，不要先改计算代码。

## 配套资源

| 资源 | 用途 |
|---|---|
| [代码仓库](https://developer.sourcefind.cn/codehub) | 示例、适配代码和项目；下载前确认许可与版本 |
| [模型仓库](https://developer.sourcefind.cn/modelzoo) | DCU 模型资源；仍需在目标 DTK/框架上验证 |
| [镜像仓库](https://harbor.sourcefind.cn:5443/) | 容器镜像；使用前确认登录、标签和拉取权限 |
| [科学计算](https://dos.sourcefind.cn:50275/portal/#/home) | 科学计算软件与服务 |
| [C86 DevKit](https://c86.sourcefind.cn/documents) | 海光 CPU/C86 资料；不属于 DCU/DTK 软件栈 |

SourceFind 的页面和下载目录会更新。入口失效时优先从开发指南、DTK 资源页或 DAS 资源库
重新检索，不把临时详情页、登录跳转或某一期安装包当成稳定文档地址。
