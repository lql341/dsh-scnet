## 国产超算软件兼容性排查

### 验证顺序

1. **系统 ABI**：确认发行版、glibc、CPU 架构和节点类型；检查 wheel 的 `manylinux` 标签是否高于目标 glibc。
2. **工具链**：记录 GCC/Clang、DTK、HIP、CMake、MPI、Python 和框架版本；登录节点可用不等于计算节点可用。
3. **最小探针**：在目标计算节点验证 import、设备枚举、最小 kernel、一个真实功能和退出码。
4. **依赖路径**：区分 pip/conda 解析失败、运行时动态库失败、框架 kernel 不支持和模型/数据下载失败。
5. **端到端结果**：记录成功条件、性能、显存/内存、失败日志和未验证范围。

### 已验证的典型边界

- **gfx936 / BW1000**：Triton、硬件 FP8 `torch._scaled_mm`、部分 bitsandbytes INT8 路径可能不可用；纯 PyTorch 软件反量化可作为推理兜底，但需要单独做性能和精度验证。
- **gfx906 / Z100**：CentOS 7.6 的 glibc 2.17 会限制 manylinux wheel 版本；安装 Python 软件时优先选 manylinux2014 / manylinux_2_17 兼容包。MinerU 场景中，Python 3.10 + onnxruntime 1.16.3 是已验证方向，magika 版本/API 需要随源码适配。
- **GROMACS HIP**：先验证 CMake 最低版本、DTK 的 `lib`/`lib64` CMake 路径、目标架构、FFTW 预置和 SIMD；CUDA 兼容层与原生 HIP 的性能不可直接互相推断。

### 作业验证模板

```bash
set -o pipefail
python3 -c 'import torch; print(torch.__version__); print(torch.cuda.is_available())'
python3 -c 'import <target_package>; print("import ok")'
<minimal_function_test>
rc=$?
echo "test_exit_code=$rc"
exit "$rc"
```

不要只看 `sacct` 的 `COMPLETED`。脚本必须显式传递最后一个测试命令的退出码，并同时读取 `.out/.err`。

### 公开报告模板

标题采用“项目 + 加速器/平台 + 编译与性能/兼容性测试报告”。正文建议按以下顺序：

1. 环境信息
2. 编译过程与主要难题
3. 最终方案与验证结果
4. 测试数据与资源占用
5. 已知限制与注意事项
6. 经验总结与通用建议
7. 附录：快速复现命令

发布前扫描：

```bash
rg -n -i 'ssh|password|token|secret|/home/|/public/|/Users/|@[A-Za-z0-9.-]+|192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.|job [0-9]+|作业编号|节点名' report.html
```

将命中项替换为占位符或概括描述；保留版本、架构、错误类型、性能数据和验证边界。
