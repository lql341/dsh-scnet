- SSH 实时节点数探测失败时，回退到 profile/cache，继续生成 Slurm 作业脚本；
  使用模拟 SSH 覆盖各类探测结果，回归测试不依赖真实网络。
- 修复 Windows 配置文件权限诊断误报，补充 Windows 提示与 WSL2 使用指引。
- 三个仓库统一保持 shell 脚本使用 LF；源仓库 main 校验通过后，自动同步下游版本与
  中英文 README 发布说明。
