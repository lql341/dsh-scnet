# Installation

[简体中文](./installation.zh-CN.md)

## Requirements

- Node.js 22.19 or later
- A supported DeepSeek Harness installation
- Linux or macOS; Windows users should run the plugin through WSL2

Install the DSH CLI if it is not already available:

```sh
npm install --global @deepseek-ai/dsh
dsh --version
```

## Install from npm

```sh
dsh plugin --profile web add dsh-scnet
```

## Install from GitHub

Pin a commit for reproducible installation:

```sh
dsh plugin --profile web add "github:lql341/dsh-scnet#<commit>"
```

The entry point is plain JavaScript and requires no package build step.

## Install from a local checkout

```sh
git clone https://github.com/lql341/dsh-scnet.git
cd dsh-scnet
npm install --no-package-lock --ignore-scripts
npm run validate
dsh plugin --profile web add .
```

## Verify the bundle

Inspect the composed profile without starting the UI:

```sh
dsh --profile web --dump-config
```

The output should include the `scnet` tool row and the `scnet-skill-filesystem` row. Start the Web UI and ask the model to call `scnet_list_clusters`:

```sh
dsh web
```

## Credentials

Model credentials belong in the DSH credential store or its supported settings interface. SCNet private keys remain local and are supplied only when the user explicitly invokes SSH setup. Neither credential type belongs in this repository.
