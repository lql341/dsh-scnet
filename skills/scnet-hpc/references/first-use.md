# 首次使用：准备什么、从哪里获取

首次介绍或缺少凭据时，先按用户当前任务说明下面的信息，再给本机配置命令。
使用用户的语言；已经可用的配置直接复用，说明用法或离线准备无需先配置凭据。

## 先选需要的连接方式

| 现在要做什么 | 推荐方式 | 用户需要准备 |
| --- | --- | --- |
| 查询队列、文件或管理标准 HPC 作业 | OpenAPI（默认） | SCNet 平台用户名、AK、SK |
| 安装环境、编译、执行远程 shell、API 未覆盖的操作 | SSH | 目标集群、集群/Linux 用户名、下载的 SSH 私钥文件路径 |
| 阅读说明、讨论参数、离线准备作业内容 | 暂不连接 | 无需凭据 |

不要求用户同时准备两套凭据。平台账号需要已开通目标区域资源；只有 AK/SK 并不会开通资源。
若还没有账号或资源，参考[SCNet 新手指南](https://www.scnet.cn/help/docs/mainsite/hpc/beginner-guide/)。

## OpenAPI：三个输入从哪里来

登录 SCNet，进入 **个人中心 → 访问控制**，生成并下载授权码文件。
按[官方 AK/SK 说明](https://www.scnet.cn/ac/openapi/doc/2.0/api/safecertification/get-user-tokens-aksk.html)对应填写：

| 向导里的字段 | 填什么 |
| --- | --- |
| 平台用户名 | SCNet 平台用户名，不是区域内的 Linux 用户名或账号密码 |
| AccessKey / AK | 下载文件中 `Accesskey` 列的值 |
| SecretKey / SK | 同一份文件中 `Secretkey` 列的值 |

每次仅复制一个值，不复制列名、整行表格或 `export` / `$env:` 赋值命令。
这里使用 HPC OpenAPI 授权码，不使用模型服务的 API Key。用户无需手填区域 ID、调度器 ID
或接口地址；认证后向导会发现已授权区域，再让用户选择。

AK/SK 只在用户自己的终端输入，两个字段都隐藏，输入时不显示星号是正常现象。
不要求用户把授权码文件、密钥或带密钥的截图发到聊天。

## SSH：下载什么、核对什么

在 SCNet 控制台选择目标区域，进入 **命令行 E-Shell → 左上角 SSH 连接**，下载私钥，
同时记录连接域名和端口。下载文件可能以 `_rsa.txt` 结尾，`.txt` 本身不代表文件选错。
参见[官方 SSH 下载步骤](https://www2.scnet.cn/help/docs/mainsite/hpc/advanced-guide/advanced-efile/index.html)。

- 集群用户名取该区域实际 Linux 用户名；可在网页 E-Shell 中运行 `whoami` 核对。
- 私钥字段填本机下载文件的路径，保留原文件，不填私钥正文，也不选 `.pub` 公钥。
- 主机和端口默认来自所选 `clusters/<集群>.conf`；与控制台不一致时先处理 profile，避免连错目标。
- SSH 私钥和 AK/SK 不互通。配置、保存位置、有效期及 Windows OpenSSH 步骤见
  [连接配置详解](setup.md)。

## 给用户能直接运行的本机命令

Agent 应将下面的 `<Skill目录>` 替换为实际安装目录的绝对路径，保留引号，按用户系统提供
一组命令。交互向导必须在用户可见且可输入的本机终端运行，不能在 Agent 后台工具里等待秘密输入。

Windows PowerShell（OpenAPI）：

```powershell
python "<Skill目录>/scripts/scnet.py" setup new --mode openapi
python "<Skill目录>/scripts/scnet.py" setup status
python "<Skill目录>/scripts/scnet.py" doctor
```

macOS / Linux（OpenAPI）：

```bash
python3 "<Skill目录>/scripts/scnet.py" setup new --mode openapi
python3 "<Skill目录>/scripts/scnet.py" setup status
python3 "<Skill目录>/scripts/scnet.py" doctor
```

已有配置需更换凭据时，用 `setup modify --mode openapi`。SSH 自动安装在 macOS/Linux/WSL2
使用 `python3 "<Skill目录>/scripts/scnet.py" setup new --mode ssh`，然后选择目标集群。
Windows 原生使用 OpenAPI 无需 WSL2；SSH 自动安装需要 WSL2 或按连接详解手工配置。

保存提示要与本机相符：Windows 用系统凭据管理器，macOS 用系统 Keychain，Linux 用
`secret-tool`（Ubuntu/Debian 的 `libsecret-tools`）和已解锁的会话密钥环。
无密钥环的服务器可用宿主秘密注入；完整示例与 PowerShell 会话范围见 [OpenAPI 说明](openapi.md)。

`setup status` 查看实际凭据来源及配置状态；`doctor` 只读检查认证和连接。
区域配置完成不等于凭据已保存；不能仅凭 setup 成功就宣称以后不需要提供凭据。

## 首次介绍示例

> 建议先用 OpenAPI 配置查询和作业管理。你需要 SCNet 平台用户名，以及“个人中心 →
> 访问控制”下载文件中的 Accesskey、Secretkey 两项。请只在本机终端向导里填写，
> 不要发到聊天。我会给你当前安装目录对应的命令，完成后用 status 和 doctor 检查。
> 如需远程编译或装环境，再到目标区域的“命令行 E-Shell → SSH 连接”下载 SSH 私钥。
