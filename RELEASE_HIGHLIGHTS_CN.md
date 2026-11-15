- 完善海光 DCU 开发索引，按任务串联 SourceFind、DTK、DAS、HIP、可复用 ROCm 文档、
  性能分析和计算节点验证，并明确哪些资料和结论不能跨环境直接套用。
- 环境与排障说明改为从 profile 获取 module 和 Python 配置，并按 DTK、框架、软件包及
  目标架构限定兼容性结论。
- 仅由 `main` 分支推送后的成功校验触发自动发版。
