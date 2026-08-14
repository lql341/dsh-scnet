# 安装 dsh-scnet

`dsh-scnet` 是一个 DeepSeek Harness（DSH）bundle 插件，把国产超算集群使用规范打包成 skill 和 5 个工具。

## 前置条件

- Node.js ≥ 22.19
- 已安装 `dsh` CLI：

```sh
npm install -g @deepseek-ai/dsh
dsh --version
```

## 方式一：从 npm 安装（推荐）

```sh
dsh plugin --profile web add dsh-scnet
```

## 方式二：从 GitHub 安装

```sh
dsh plugin --profile web add "github:lql341/dsh-scnet#main"
```

> 本插件入口是纯 JavaScript，无编译步骤，git 源安装不需要 `allowBuilds`。

## 方式三：本地目录安装

```sh
git clone https://github.com/lql341/dsh-scnet.git
cd dsh-scnet
dsh plugin --profile web add .
```

## 验证安装

启动 Web UI：

```sh
dsh web
```

浏览器打开 `http://127.0.0.1:3080`，发一条：

```text
用 scnet_list_clusters 看看现在有哪些可用的超算集群。
```

如果能返回集群列表，说明插件已安装并能被模型调用。

## 配置 DeepSeek API Key

首次使用需要配置模型 Key。打开 Web UI 后：

```text
设置 → 模型 → 在 DeepSeek 卡片填入 API Key → 保存
```

也可以直接编辑凭据文件：

```text
~/.dsh/.credentials.yaml
```

把其中的占位符替换成你的 Key：

```yaml
DEEPSEEK_API_KEY: sk-你的key
```

保存后无需重启，下一次请求即生效。Key 只保存在本机 `~/.dsh` 下，不会写入仓库。
