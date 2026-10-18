- 优化首次 AK/SK 配置：检查粘贴错误、隐藏双密钥、显示实际来源，保存后读回验证，
  明确区分区域元数据与凭据持久保存。
- 支持 Windows 凭据管理器，解释 macOS Keychain、Linux 密钥环依赖、PowerShell 会话
  作用域与 Windows/WSL2 环境隔离。
- 提前展示 SSH 私钥安装计划与实际配置，补充集群用户名、密钥有效期和 Windows OpenSSH
  指引，并增加 Linux、macOS、Windows 三平台配置回归测试。
