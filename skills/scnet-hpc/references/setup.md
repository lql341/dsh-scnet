# 连接配置详解

集群的主机名、端口等参数来自 `clusters/<集群短名>.conf`。
本文用 `<集群>`、`<主机名>`、`<端口>` 表示从 profile 读出的值。

## 首次配置前先分清三件事

1. **凭据**：在控制台选择目标区域，进入“命令行 E-Shell → 左上角 SSH 连接”，下载私钥并
   记录域名和端口（[官方步骤](https://www2.scnet.cn/help/docs/mainsite/hpc/advanced-guide/advanced-efile/index.html)）。
   它与 OpenAPI 的 AK/SK 不同；保留原始文件，可能以 `_rsa.txt` 结尾，不要选择 `.pub` 公钥。
2. **用户名**：填写区域内的集群/Linux 用户名，不一定等于 SCNet 平台登录名；文件名只作为
   自动推断线索，不确定时在该区域网页 E-Shell 中执行 `whoami` 核对。
3. **运行环境**：macOS/Linux/WSL2 可运行自动安装脚本。Windows 原生 OpenSSH 的配置和
   WSL2 里的 `~/.ssh` 不共享，在哪个环境运行作业工具，就在该环境配置 SSH。

在 macOS/Linux/WSL2 运行 `./scripts/setup.sh new --backend ssh`，或
`python3 scripts/scnet.py setup new --mode ssh`。路径带空格时可使用外层引号；向导只需要路径，
不要粘贴私钥正文。安装前会显示主机、端口、目标位置，安装后显示实际生效的 `ssh -G` 参数。

安装位置为 `~/.ssh/id_rsa_<集群>`，配置为 `~/.ssh/config`。不同的旧私钥先备份；只更新
本工具管理的 Host 块，其他已有 Host 保留。保留旧 Host 时，务必核对实际 IdentityFile
是否指向新密钥。`--skip-connect` 只保存元数据，不代表私钥已安装或连接已验证。

私钥有口令时先执行 `ssh-add <私钥文件路径>`；如果无法解析但没有设置口令，重新下载原始
文件，不要把损坏的格式误认为“有口令”。`Permission denied` 还可能表示私钥过期、用户名
不匹配或 IP 白名单限制，不只是输入错误。

## Windows 原生 OpenSSH（手工配置）

若使用完整 Bash 工作流，优先在 WSL2 运行上方安装向导。若只使用 Python SSH backend，
可手工配置 Windows OpenSSH，然后运行 `python scripts/scnet.py setup modify --mode ssh`
接管已有别名；这不会让 Bash 安装脚本变成 Windows 原生脚本。

1. 在 PowerShell 执行 `Get-Command ssh,scp,ssh-keygen`，确认 Windows OpenSSH 客户端已安装。
2. 把下载的私钥复制到 `$env:USERPROFILE\.ssh\id_rsa_<集群>`；路径可自选，但需与配置一致。
3. 对复制的目标私钥限制访问权限（下方路径占位符需替换）：

```powershell
$sshKeyPath = "$env:USERPROFILE\.ssh\id_rsa_<集群>"
$sshIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls $sshKeyPath /inheritance:r
icacls $sshKeyPath /grant:r "${sshIdentity}:(R)"
notepad "$env:USERPROFILE\.ssh\config"
```

在编辑器里追加以下块，替换为 profile 和账号中的实际值，保存为无 BOM 的 UTF-8 文本；
保留已有无关的 Host 配置。Windows 不添加 `UseKeychain` 和 Unix socket 连接复用选项：

```text
Host <集群>
  HostName <主机名>
  Port <端口>
  User <集群用户名>
  IdentityFile ~/.ssh/id_rsa_<集群>
  IdentitiesOnly yes
  ServerAliveInterval 60
  ServerAliveCountMax 3
```

先执行 `ssh -G <集群>` 核对 `hostname/user/port/identityfile`，再执行 `ssh <集群>`。
首次主机指纹请与平台提供的指纹核对。口令私钥需要当前环境的 ssh-agent，Windows 中的
`ssh-add` 与 WSL2 中的 ssh-agent 也互相独立。

## 手工配置

```bash
# 1. 装私钥
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cp <下载的私钥> ~/.ssh/id_rsa_<集群>
chmod 600 ~/.ssh/id_rsa_<集群>

# macOS：清除下载文件的隔离属性，否则某些工具拒绝读取
xattr -c ~/.ssh/id_rsa_<集群>

# 2. 建 socket 目录（长连接用）
mkdir -p ~/.ssh/sockets && chmod 700 ~/.ssh/sockets

# 3. 追加下面的段到 ~/.ssh/config，然后 chmod 600 ~/.ssh/config
```

```
Host <集群> <主机名>
  HostName <主机名>
  User <你的用户名>
  Port <端口>
  IdentityFile ~/.ssh/id_rsa_<集群>
  IdentitiesOnly yes
  # UseKeychain 仅适用于 Apple OpenSSH；Linux 上省略
  UseKeychain yes
  # 标准 OpenSSH 选项，需要运行 ssh-agent
  AddKeysToAgent yes
  # 长连接
  ControlMaster auto
  ControlPath ~/.ssh/sockets/%r@%h-%p
  ControlPersist 10m
  # 保活
  ServerAliveInterval 60
  ServerAliveCountMax 3
  TCPKeepAlive yes
  # 仅当 profile 里 NEEDS_UPDATE_HOSTKEYS_NO=yes 时才加这行
  UpdateHostKeys no
```

## SSH 选项说明

**`ControlPersist 10m` 而非 `yes`**：永久驻留的 master 在笔记本休眠或换网络后会
变成失效 socket，可能留下需要清理的失效 socket。10 分钟覆盖一次交互操作的节奏，又能自然回收。
实测复用后单条命令从约 2 秒降到 0.57 秒。

**`ServerAliveInterval 60`**：应用层心跳，防止空闲 SSH 会话被中间网关静默切断。
用于保持长时间空闲会话。`TCPKeepAlive` 是 TCP 层的，两者互补。

**`UpdateHostKeys no`**：部分平台的服务端对主机密钥轮换扩展返回错误签名：

```
client_global_hostkeys_prove_confirm: server gave bad signature for RSA key 0
```

该设置仅禁用服务端主机密钥轮换扩展；首次主机密钥仍按正常流程校验。仅在出现该告警且 profile 标记 `NEEDS_UPDATE_HOSTKEYS_NO=yes` 的集群上使用。

**`IdentitiesOnly yes`**：只用指定的私钥。ssh-agent 里密钥多时，避免因尝试次数
过多被服务端拒绝。

## macOS 与 Linux 差异

| 项 | macOS | Linux |
|---|---|---|
| `UseKeychain` | Apple OpenSSH 支持 | 不支持，应省略 |
| `AddKeysToAgent` | 支持 | 支持，需要运行 ssh-agent |
| 下载文件隔离属性 | 需 `xattr -c` | 无此概念 |
| `sed -i` | 需 `sed -i ''`（BSD sed） | `sed -i`（GNU sed） |

`setup-ssh.sh` 检测 `uname -s` 自动处理前两项。

## 长连接管理

```bash
ssh -O check <集群>     # 查看 master 状态
ssh -O exit <集群>      # 手工断开（网络切换后卡住时用）
```

## 密钥有效期

超算平台的私钥通常有有效期，文件名里就带，例如
`<用户名>_<主机>_RsaKeyExpireTime_2026-10-29_12-51-40.txt` 表示 2026-10-29 过期。
到期前从控制台重新下载并重跑 setup 脚本。

可以重复运行 `scripts/setup.sh` 更新某个 profile 的用户名和私钥。面板会从密钥文件名
中的 `RsaKeyExpireTime_YYYY-MM-DD` 自动记录有效期，`python3 scripts/scnet.py doctor`
会报告剩余天数和已过期状态。密钥内容不会进入配置文件。

profile 里的 `KEY_NAME_MARKER` 就是用来从这种文件名里提取用户名的；公开
`scnet-hpc` profile 使用 `_<CLUSTER_HOST>_` 占位符，所以安装时通常需要显式传
用户名，或在本地私有 profile 中补齐真实标记。

查看密钥指纹：

```bash
ssh-keygen -lf ~/.ssh/id_rsa_<集群>
```

## 加 passphrase（可选）

```bash
ssh-keygen -p -f ~/.ssh/id_rsa_<集群>
```

配合 macOS 的 `UseKeychain yes` + `AddKeysToAgent yes`，只需首次输入一次。

## 常见连接失败

| 现象 | 原因 |
|---|---|
| `Permission denied (publickey)` | 私钥过期，或本机 IP 不在平台白名单 |
| `Connection timed out` | 端口被本地网络阻断（超算常用非 22 端口）|
| `Bad owner or permissions on config` | `chmod 600 ~/.ssh/config` |
| `WARNING: UNPROTECTED PRIVATE KEY` | `chmod 600 ~/.ssh/id_rsa_<集群>` |
| 首次连接等待主机指纹确认 | 在等确认主机指纹，加 `-o StrictHostKeyChecking=accept-new` |

多数超算平台有 **IP 白名单**，换网络（家里/公司/热点）后可能连不上，
需要去控制台加当前 IP。

## 在脚本里调用

```bash
ssh -o BatchMode=yes <集群> '<命令>'
```

`BatchMode=yes` 让认证失败立刻返回，而不是卡在密码提示上等输入。写自动化脚本时
应启用，以避免自动化流程等待交互输入。

## 文件传输

```bash
scp local.py <集群>:/public/home/$USER/scripts/
scp <集群>:/public/home/$USER/scripts/logs/job_123.log .
rsync -avz --progress ./dir/ <集群>:/public/home/$USER/dir/   # 大量文件
```

上述命令复用 SSH profile 中的连接参数。
