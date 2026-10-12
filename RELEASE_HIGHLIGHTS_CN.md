- Desktop 主机可通过 `DSH_SCNET_PYTHON` 或 `SCNET_PYTHON` 注入经过校验的 Python 3
  解释器，本地入口不再强制要求命令名为 `python3`。
- 共享 shell 辅助函数会在运行 OpenAPI 或本地作业生成前拒绝 Python 2 和无效解释器路径。
