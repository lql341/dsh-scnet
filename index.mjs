import { execFile } from 'node:child_process'
import { promises as fs } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'scnet-hpc'
export const inject = ['tools']

const __dirname = dirname(fileURLToPath(import.meta.url))
const SKILL_DIR = join(__dirname, 'skills', 'scnet-hpc')
const SCRIPTS_DIR = join(SKILL_DIR, 'scripts')
const CLUSTERS_DIR = join(SKILL_DIR, 'clusters')

function runBash(script, args, timeoutMs = 120000) {
  return new Promise((resolve) => {
    execFile(
      'bash',
      [script, ...args],
      { cwd: SKILL_DIR, timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) => {
        const code = error ? (typeof error.code === 'number' ? error.code : 1) : 0
        resolve({
          ok: code === 0,
          code,
          stdout: String(stdout || ''),
          stderr: String(stderr || ''),
        })
      },
    )
  })
}

function textBlock(value) {
  return [{ type: 'text', text: value }]
}

async function listClusterIds() {
  let entries = []
  try {
    entries = await fs.readdir(CLUSTERS_DIR)
  } catch {
    return []
  }
  return entries
    .filter((entry) => entry.endsWith('.conf') && !entry.startsWith('_'))
    .map((entry) => entry.replace(/\.conf$/, ''))
    .sort()
}

async function readProfile(id) {
  return fs.readFile(join(CLUSTERS_DIR, `${id}.conf`), 'utf8')
}

function fieldOf(text, key) {
  const match = text.match(new RegExp(`^${key}="?(.*?)"?$`, 'm'))
  return match ? match[1] : ''
}

function positiveInt(value, label) {
  if (value === undefined || value === null || String(value).trim() === '') return null
  if (!/^[0-9]+$/.test(String(value).trim())) {
    return { error: `${label} 必须是正整数` }
  }
  return { value: String(value).trim() }
}

export function apply(ctx) {
  ctx.tools.register(
    defineTool({
      name: 'scnet_list_clusters',
      description:
        '列出 scnet-hpc 插件中已配置的超算集群 profile（短名与描述）。生成作业或配 SSH 前用它确认可用的集群短名。',
      parameters: {},
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute() {
        const ids = await listClusterIds()
        if (ids.length === 0) {
          return '没有可用的集群 profile。请在 skills/scnet-hpc/clusters/ 下新增 <短名>.conf。'
        }
        const lines = []
        for (const id of ids) {
          const text = await readProfile(id)
          lines.push(`${id}\t${fieldOf(text, 'CLUSTER_DESC') || '（未填写描述）'}`)
        }
        return lines.join('\n')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_show_cluster',
      description:
        '读取指定集群 profile 的完整参数（内存上限、分区、GRES、DTK 路径、已知限制等）。回答硬件规格或配额问题时必须读 profile，不要凭记忆。',
      parameters: {
        cluster: {
          type: 'string',
          description: '集群短名；省略时，若只有一个 profile 则自动选择，否则报错提示可选项。',
        },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        let id = String(args.cluster || '').trim()
        const ids = await listClusterIds()
        if (!id && ids.length === 1) id = ids[0]
        if (!id) {
          return `请指定 cluster。可用集群：${ids.join(', ') || '（无）'}`
        }
        try {
          return await readProfile(id)
        } catch {
          return `找不到 profile：${id}。可用集群：${ids.join(', ') || '（无）'}`
        }
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_generate_job',
      description:
        '按目标集群的约束生成合规的 Slurm 作业脚本（自动算 --mem、--gres、module load、离线环境变量，并在末尾写 exit $rc）。会写一个 <name>.slurm 到当前目录并返回上传/提交命令。',
      parameters: {
        name: { type: 'string', required: true, description: '作业名（slurm --job-name 和输出文件名）' },
        accelerators: { type: 'string', description: '加速器数量，默认 1' },
        cpus: { type: 'string', description: 'CPU 核数，默认 8' },
        time: { type: 'string', description: '时长，默认 00:20:00，格式 HH:MM:SS 或 D-HH:MM:SS' },
        cluster: { type: 'string', description: '集群短名；省略时若只有一个 profile 则自动选择' },
        remote_user: { type: 'string', description: '远端用户名；与本地不同时填写（日志路径需要真实用户名）' },
        refresh: { type: 'boolean', description: '是否在生成前运行 refresh-cluster.sh 刷新动态规则（默认否）' },
        no_auto: { type: 'boolean', description: '是否忽略 clusters/.cache/*.auto.conf 动态缓存（默认否）' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const nameVal = String(args.name || '').trim()
        if (!nameVal) return '缺少必填参数 name。'

        const accelerators = positiveInt(args.accelerators, 'accelerators')
        if (accelerators && accelerators.error) return accelerators.error
        const cpus = positiveInt(args.cpus, 'cpus')
        if (cpus && cpus.error) return cpus.error

        const argv = []
        const cluster = String(args.cluster || '').trim()
        if (cluster) argv.push('--cluster', cluster)
        const remoteUser = String(args.remote_user || '').trim()
        if (remoteUser) argv.push('--user', remoteUser)
        if (args.refresh === true) argv.push('--refresh')
        if (args.no_auto === true) argv.push('--no-auto')
        argv.push(nameVal)
        if (accelerators) argv.push(accelerators.value)
        if (cpus) argv.push(cpus.value)
        if (args.time && String(args.time).trim()) argv.push(String(args.time).trim())

        const timeoutMs = args.refresh === true ? 240000 : 30000
        const res = await runBash(join(SCRIPTS_DIR, 'new-job.sh'), argv, timeoutMs)
        if (res.ok) return res.stdout.trim() || res.stderr.trim()
        return `生成失败（exit ${res.code}）：\n${res.stderr.trim() || res.stdout.trim()}`
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_refresh_cluster',
      description:
        '动态刷新指定集群的规则缓存（分区、内存、GRES、网络、登录节点缺库等）。默认只做登录节点只读探测；compute=true 会额外提交一个约 10 分钟的计算节点能力探针，会 SSH 到远端并写 clusters/.cache/<短名>.auto.conf。',
      parameters: {
        cluster: { type: 'string', description: '集群短名；省略时若只有一个 profile 则自动选择' },
        compute: { type: 'boolean', description: '是否额外提交计算节点能力探针（默认否）' },
        dry_run: { type: 'boolean', description: '只输出将要写入的缓存，不落盘（默认否）' },
      },
      timeoutMs: 900000,
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const argv = []
        const cluster = String(args.cluster || '').trim()
        if (cluster) argv.push('--cluster', cluster)
        if (args.compute === true) argv.push('--compute')
        if (args.dry_run === true) argv.push('--dry-run')

        const timeoutMs = args.compute === true ? 900000 : 240000
        const res = await runBash(join(SCRIPTS_DIR, 'refresh-cluster.sh'), argv, timeoutMs)
        if (res.ok) return res.stdout.trim() || res.stderr.trim()
        return `刷新失败（exit ${res.code}）：\n${res.stderr.trim() || res.stdout.trim()}`
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_setup_ssh',
      description:
        '在本地 macOS/Linux 上配置到超算集群的 SSH 连接：安装私钥到 ~/.ssh、写 ~/.ssh/config、测试连接。幂等，重复运行只补缺失项。会修改本机 SSH 配置，执行前应向用户确认私钥路径与集群。',
      parameters: {
        key_path: { type: 'string', required: true, description: '从超算平台控制台下载的私钥文件绝对路径（.txt 或 PEM 私钥）' },
        cluster: { type: 'string', description: '集群短名；省略时若只有一个 profile 则自动选择' },
        username: { type: 'string', description: '远端用户名；省略时尝试从私钥文件名推断' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const keyPath = String(args.key_path || '').trim()
        if (!keyPath) return '缺少必填参数 key_path。'
        const argv = []
        const cluster = String(args.cluster || '').trim()
        if (cluster) argv.push('--cluster', cluster)
        argv.push(keyPath)
        if (args.username && String(args.username).trim()) argv.push(String(args.username).trim())
        const res = await runBash(join(SCRIPTS_DIR, 'setup-ssh.sh'), argv, 90000)
        const out = `${res.stdout.trim()}\n${res.stderr.trim()}`.trim()
        return out || `setup-ssh.sh 退出码 ${res.code}，但没有输出。`
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_run_compute_probe',
      description:
        '在已配置 SSH 的集群计算节点上运行最小能力探针，输出 PROBE_ 开头的结果（加速器架构、FP8、Triton、bitsandbytes、外网等）。会提交一个 1 卡、4 核、10 分钟的小作业并等待完成。',
      parameters: {
        cluster: { type: 'string', required: true, description: '集群短名' },
        accelerators: { type: 'string', description: '加速器数量，默认 1' },
        cpus: { type: 'string', description: 'CPU 核数，默认 4' },
        time: { type: 'string', description: '作业时长，默认 00:10:00' },
        remote_user: { type: 'string', description: '远端用户名；与本地不同时填写' },
      },
      timeoutMs: 900000,
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const cluster = String(args.cluster || '').trim()
        if (!cluster) return '缺少必填参数 cluster。'

        const accelerators = positiveInt(args.accelerators, 'accelerators')
        if (accelerators && accelerators.error) return accelerators.error
        const cpus = positiveInt(args.cpus, 'cpus')
        if (cpus && cpus.error) return cpus.error

        const argv = ['--cluster', cluster]
        const remoteUser = String(args.remote_user || '').trim()
        if (remoteUser) argv.push('--user', remoteUser)
        if (cpus) argv.push('--cpus', cpus.value)
        if (args.time && String(args.time).trim()) argv.push('--time', String(args.time).trim())
        if (accelerators) argv.push('--accelerators', accelerators.value)

        const res = await runBash(join(SCRIPTS_DIR, 'run-compute-probe.sh'), argv, 900000)
        if (res.ok) return res.stdout.trim()
        return `计算节点探针失败（exit ${res.code}）：\n${res.stderr.trim() || res.stdout.trim()}`
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_probe_cluster',
      description:
        '探测一个已能 SSH 登录的集群（调度器、分区、内存、GRES、网络、登录节点 torch 可用性），生成可直接保存为 profile 的配置文本。结果需要写回 clusters/<短名>.conf 并补齐探测不到的项。',
      parameters: {
        target: { type: 'string', required: true, description: 'ssh 别名或主机名（须已能免密登录）' },
        name: { type: 'string', description: '集群短名，默认与 target 相同' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const target = String(args.target || '').trim()
        if (!target) return '缺少必填参数 target。'
        const argv = [target]
        if (args.name && String(args.name).trim()) argv.push(String(args.name).trim())
        const res = await runBash(join(SCRIPTS_DIR, 'probe-cluster.sh'), argv, 180000)
        if (res.ok) return res.stdout.trim()
        return `探测失败（exit ${res.code}）：\n${res.stderr.trim() || res.stdout.trim()}`
      },
    }),
  )
}
