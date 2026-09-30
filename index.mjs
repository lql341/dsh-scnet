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

function runBash(script, args, timeoutMs = 120000, cwd = SKILL_DIR) {
  return new Promise((resolve) => {
    execFile(
      'bash',
      [script, ...args],
      { cwd, timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 },
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

function runScnet(args, timeoutMs = 120000) {
  return new Promise((resolve) => {
    execFile(
      'python3',
      [join(SCRIPTS_DIR, 'scnet.py'), '--json', ...args],
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

function scnetResult(res, action) {
  if (res.ok) return res.stdout.trim() || '{}'
  return `${action}失败（exit ${res.code}）：\n${res.stderr.trim() || res.stdout.trim()}`
}

function regionArgs(region) {
  const value = String(region || '').trim()
  return value ? ['--region', value] : []
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

// ---- 作业生命周期（submit / job / logs / cancel）辅助 ----
//
// 设计约束来自 scnet-hpc Skill 的 SKILL.md：
//   - 变更操作必须解析到一个确定目标（OpenAPI 允许默认区域，SSH 多 profile 时必须显式）
//   - 提交/取消绝不自动重试
//   - 缺失参数一次只提示一个，并给出可执行的下一步

const JOB_BACKENDS = new Set(['openapi', 'ssh'])

const MISSING_HINTS = {
  name: '缺 name：请给这个作业起一个名字。',
  command: '缺 command：请给出要在计算节点上执行的命令或脚本体。',
  work_dir: '缺 work_dir：请给出一个绝对路径作为作业工作目录（日志默认也落在那里）。',
  queue: '缺 queue：请指定队列；不确定可先看该区域的空闲队列。',
  remote_path: '缺 remote_path：SSH 模式请给出远端已存在的 Slurm 脚本绝对路径。',
  job_id: '缺 job_id：请给出作业号。',
  path: '缺 path：请给出远端日志文件的绝对路径。',
}

// 与 CLI 的必填顺序保持一致（openapi.py 的 _submit_payload：name → command → work_dir → queue）。
// queue 不在这里：它由队列预检统一处理，可能是自动选择、也可能是"请补一个"。
const SUBMIT_REQUIRED_ORDER = ['name', 'command', 'work_dir']

function firstMissingRequired(args, keys) {
  for (const key of keys) {
    if (!String(args[key] ?? '').trim()) return key
  }
  return ''
}

// backend 默认 openapi，不强制用户填写
function pickBackend(value) {
  const raw = String(value ?? '').trim().toLowerCase()
  if (!raw) return { backend: 'openapi', argv: ['--backend', 'openapi'] }
  if (!JOB_BACKENDS.has(raw)) return { error: `backend 只支持 openapi 或 ssh，收到 ${value}。` }
  return { backend: raw, argv: ['--backend', raw] }
}

// region / scheduler_id 交给后端自行解析：只有用户显式给了才透传
function openapiTargetArgs(args) {
  const argv = []
  const region = String(args.region ?? '').trim()
  if (region) argv.push('--region', region)
  const scheduler = String(args.scheduler_id ?? '').trim()
  if (scheduler) argv.push('--scheduler-id', scheduler)
  return argv
}

// SSH：恰好一个 profile 时自动选择；多个才要求用户补 cluster 一个参数
async function sshClusterArg(args) {
  const cluster = String(args.cluster ?? '').trim()
  if (cluster) return { argv: ['--cluster', cluster], cluster }
  const ids = await listClusterIds()
  if (ids.length === 1) return { argv: ['--cluster', ids[0]], cluster: ids[0] }
  return {
    error: `存在多个集群 profile，请补 cluster 一个参数。可选：${ids.join('、') || '（无）'}`,
  }
}

async function resolveTarget(args) {
  const pick = pickBackend(args.backend)
  if (pick.error) return pick
  const argv = [...pick.argv]
  if (pick.backend === 'openapi') {
    argv.push(...openapiTargetArgs(args))
    return { backend: pick.backend, argv }
  }
  const ssh = await sshClusterArg(args)
  if (ssh.error) return ssh
  argv.push(...ssh.argv)
  return { backend: pick.backend, argv, cluster: ssh.cluster }
}

// 失败时把 --json 错误信封里的 error 取出来
function errorTextFrom(res) {
  const raw = String(res.stdout || '').trim() || String(res.stderr || '').trim()
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && typeof parsed.error === 'string') {
      return parsed.error
    }
  } catch {
    // 非 JSON，退回纯文本解析
  }
  const matched = raw.match(/error:\s*(.+)/)
  return matched ? matched[1].trim() : raw
}

// 一次只给一条可执行的提示（不展示整套参数清单）
function translateScnetError(text) {
  const value = String(text || '')
  const missing = value.match(/missing required option:\s*([A-Za-z_]+)/)
  if (missing) return MISSING_HINTS[missing[1]] || `缺 ${missing[1]}：这是必填参数。`
  if (/multiple schedulers are available/i.test(value)) {
    const list = value.split('use --scheduler-id:')[1] || ''
    return `该区域有多个调度器，请补 scheduler_id 一个参数。候选：${list.trim()}`
  }
  if (/job endpoint returned an unexpected data shape/i.test(value)) {
    return (
      '平台没有返回这个作业的记录：作业完成一段时间后可能会从该接口消失。' +
      '若只想看日志，请直接给日志文件的 path；若刚提交不久，可稍后重试。'
    )
  }
  return value
}

function scnetJobResult(res, action) {
  if (res.ok) return res.stdout.trim() || '{}'
  return `${action}失败（exit ${res.code}）：\n${translateScnetError(errorTextFrom(res))}`
}

async function runScnetEnvelope(argv) {
  const res = await runScnet(argv)
  if (!res.ok) return { ok: false, error: translateScnetError(errorTextFrom(res)) }
  try {
    const parsed = JSON.parse(res.stdout)
    return { ok: true, envelope: parsed, data: parsed?.data }
  } catch {
    return { ok: false, error: '后端返回的不是合法 JSON。' }
  }
}

function parseWalltimeSeconds(value) {
  const matched = String(value || '').trim().match(/^(?:(\d+)-)?(\d{1,2}):(\d{2}):(\d{2})$/)
  if (!matched) return null
  const [, days, hours, minutes, seconds] = matched
  return Number(days || 0) * 86400 + Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds)
}

// 按是否需要加速器筛队列，空闲节点多的优先（只用于"推荐一个"，不用于静默多选一）
function queueCandidates(queues, wantsAccelerator) {
  return queues
    .filter((item) => {
      const maxDcu = Number(item?.max_dcus_per_node ?? 0)
      return wantsAccelerator ? maxDcu > 0 : maxDcu === 0
    })
    .sort((a, b) => Number(b?.free_nodes ?? 0) - Number(a?.free_nodes ?? 0))
}

// best-effort 队列预检：查得到就校验，查不到不阻塞提交
async function precheckQueue(target, args) {
  const check = await runScnetEnvelope([...target.argv, 'queues'])
  if (!check.ok) return { note: `队列预检已跳过（${check.error}）` }
  const queues = Array.isArray(check.data) ? check.data : []
  if (queues.length === 0) return { note: '队列预检已跳过（该区域没有返回队列信息）' }

  const queue = String(args.queue ?? '').trim()
  const dcus = Number(String(args.dcus ?? '').trim() || 0)

  if (!queue) {
    const candidates = queueCandidates(queues, dcus > 0)
    if (candidates.length === 1) {
      const only = candidates[0]
      return { queue: String(only.partition), note: `已自动选择队列 ${only.partition}` }
    }
    if (candidates.length > 1) {
      const best = candidates[0]
      return {
        error:
          `请补 queue 一个参数：该区域有 ${candidates.length} 个可用队列，` +
          `按你要的资源建议 ${best.partition}（空闲 ${best.free_nodes} 节点）。`,
      }
    }
    return {}
  }

  const hit = queues.find((item) => String(item?.partition) === queue)
  if (!hit) {
    const candidates = queueCandidates(queues, dcus > 0)
    const pool = candidates.length ? candidates : queues
    return {
      error: `队列 ${queue} 不存在。可用队列：${pool.map((item) => item.partition).join('、')}`,
    }
  }

  const walltime = String(args.walltime ?? '').trim()
  if (walltime) {
    const wanted = parseWalltimeSeconds(walltime)
    const limit = Number(hit?.max_walltime ?? 0)
    if (wanted !== null && Number.isFinite(limit) && limit > 0 && wanted > limit) {
      return { error: `walltime ${walltime} 超过队列 ${queue} 的上限（${limit} 秒）。` }
    }
  }

  const maxDcu = Number(hit?.max_dcus_per_node ?? 0)
  if (dcus > 0 && Number.isFinite(maxDcu) && maxDcu > 0 && dcus > maxDcu) {
    return { error: `dcus ${dcus} 超过队列 ${queue} 单节点上限 ${maxDcu}。` }
  }

  return { queue, note: `队列预检通过（${queue}）` }
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
      name: 'scnet_status',
      description: '只读查看 scnet-hpc 当前默认 backend、SSH profile 和 OpenAPI 区域配置；不会连接远端或修改配置。',
      parameters: {},
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute() {
        return scnetResult(await runScnet(['config']), '读取 SCNet 配置')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_openapi_regions',
      description: '通过已配置的 SCNet OpenAPI 凭据只读列出授权计算区域，不显示 token。',
      parameters: {},
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute() {
        return scnetResult(
          await runScnet(['--backend', 'openapi', 'clusters']),
          '查询 OpenAPI 区域',
        )
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_job_queues',
      description: '通过 OpenAPI 只读查询目标区域可访问的 Slurm 队列、空闲资源和单作业限制。',
      parameters: {
        region: { type: 'string', description: '区域名称或 ID；省略时使用已保存的默认区域' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        return scnetResult(
          await runScnet(['--backend', 'openapi', ...regionArgs(args.region), 'queues']),
          '查询作业队列',
        )
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_submit_job',
      description:
        '提交一个 SCNet 作业。默认走 OpenAPI；backend=ssh 时提交远端已存在的 Slurm 脚本。这是变更操作，会占用配额，执行前应确认目标、资源与时长。region/cluster/scheduler 能自动解析；dry_run=true 只预览请求不提交。提交成功后返回 job_id 与日志路径，可直接交给 scnet_job_logs。',
      parameters: {
        backend: { type: 'string', description: 'openapi（默认）或 ssh' },
        region: { type: 'string', description: 'OpenAPI 区域；省略时由后端回落已保存的默认区域' },
        scheduler_id: { type: 'string', description: 'OpenAPI 调度器 ID；省略时该区域只有一个调度器则自动选择' },
        cluster: { type: 'string', description: 'SSH 集群短名；只有一个 profile 时自动选择，多个则必须指定' },
        remote_path: { type: 'string', description: 'SSH 模式必填：远端已存在的 Slurm 脚本绝对路径' },
        name: { type: 'string', description: 'OpenAPI 必填：作业名' },
        command: { type: 'string', description: 'OpenAPI 必填：命令或脚本体（可多行）' },
        work_dir: { type: 'string', description: 'OpenAPI 必填：作业工作目录（绝对路径，日志默认落在这里）' },
        queue: { type: 'string', description: 'OpenAPI 必填：队列名；省略时仅在候选唯一时自动选择，否则会问你一个' },
        nodes: { type: 'string', description: '节点数，默认 1' },
        cpus: { type: 'string', description: 'CPU 核数，默认 1' },
        dcus: { type: 'string', description: 'DCU 卡数，默认 0；部分队列的 QOS 要求至少 1（如昆山 kshdnormal）' },
        gpus: { type: 'string', description: 'GPU 卡数，默认 0' },
        memory: { type: 'string', description: '内存，如 12gb；省略时用调度器默认' },
        walltime: { type: 'string', description: '时长，默认 24:00:00，格式 HH:MM:SS 或 D-HH:MM:SS' },
        stdout: { type: 'string', description: '显式覆盖 stdout 路径；会破坏 scnet_job_logs 的便捷模式' },
        stderr: { type: 'string', description: '显式覆盖 stderr 路径；会破坏 scnet_job_logs 的便捷模式' },
        exclusive: { type: 'boolean', description: '独占节点（默认否）' },
        scheduler_options: {
          type: 'array',
          items: { type: 'string' },
          description: '额外的 #SBATCH 选项，逐条透传',
        },
        dry_run: { type: 'boolean', description: '只预览将要发送的请求，不真正提交（默认否）' },
      },
      timeoutMs: 180000,
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const target = await resolveTarget(args)
        if (target.error) return target.error

        const globals = [...target.argv]
        if (args.dry_run === true) globals.push('--dry-run')

        if (target.backend === 'ssh') {
          const remotePath = String(args.remote_path ?? '').trim()
          if (!remotePath) return MISSING_HINTS.remote_path
          const res = await runScnet([...globals, 'submit', '--remote-path', remotePath])
          return scnetJobResult(res, '提交作业')
        }

        for (const key of ['nodes', 'cpus', 'dcus', 'gpus']) {
          const checked = positiveInt(args[key], key)
          if (checked && checked.error) return checked.error
        }

        // 按 CLI 的必填顺序先做本地检查，一次只提示一个，
        // 并避免在参数不全时就发起队列查询。
        const missing = firstMissingRequired(args, SUBMIT_REQUIRED_ORDER)
        if (missing) return MISSING_HINTS[missing]

        const precheck = await precheckQueue(target, args)
        if (precheck.error) return precheck.error
        const queue = precheck.queue || String(args.queue ?? '').trim()

        const argv = [...globals, 'submit']
        const name = String(args.name ?? '').trim()
        const command = String(args.command ?? '')
        const workDir = String(args.work_dir ?? '').trim()
        if (name) argv.push('--name', name)
        if (command.trim()) argv.push('--command', command)
        if (workDir) argv.push('--work-dir', workDir)
        if (queue) argv.push('--queue', queue)
        for (const [flag, key] of [
          ['--nodes', 'nodes'],
          ['--cpus', 'cpus'],
          ['--dcus', 'dcus'],
          ['--gpus', 'gpus'],
        ]) {
          const checked = positiveInt(args[key], key)
          if (checked && checked.value) argv.push(flag, checked.value)
        }
        for (const [flag, key] of [
          ['--memory', 'memory'],
          ['--walltime', 'walltime'],
          ['--stdout', 'stdout'],
          ['--stderr', 'stderr'],
        ]) {
          const value = String(args[key] ?? '').trim()
          if (value) argv.push(flag, value)
        }
        if (args.exclusive === true) argv.push('--exclusive')
        const options = Array.isArray(args.scheduler_options) ? args.scheduler_options : []
        for (const option of options) {
          const value = String(option ?? '').trim()
          if (value) argv.push('--scheduler-option', value)
        }

        const res = await runScnet(argv)
        if (!res.ok) return scnetJobResult(res, '提交作业')
        if (args.dry_run === true) return res.stdout.trim() || '{}'

        let jobId = ''
        try {
          const parsed = JSON.parse(res.stdout)
          jobId = String(parsed?.data?.job_id ?? parsed?.job_id ?? '')
        } catch {
          // 保底走下面的原始输出分支
        }
        if (!jobId) return `提交请求已发出，但没能解析出 job_id。原始返回：\n${res.stdout.trim()}`

        // 提交后立刻取一次权威的 work_dir / 日志路径；作业较旧时该接口可能不再返回记录
        const jobRes = await runScnetEnvelope([...target.argv, 'job', jobId])
        let resolvedWorkDir = workDir
        let stdoutPath = String(args.stdout ?? '').trim()
        let stderrPath = String(args.stderr ?? '').trim()
        let source = 'default-rule'
        if (jobRes.ok && jobRes.data) {
          resolvedWorkDir = String(jobRes.data.work_dir || resolvedWorkDir || '')
          stdoutPath = String(jobRes.data.stdout || stdoutPath || '')
          stderrPath = String(jobRes.data.stderr || stderrPath || '')
          source = 'job'
        }
        if (!stdoutPath && resolvedWorkDir) {
          const base = resolvedWorkDir.replace(/\/+$/, '')
          stdoutPath = `${base}/std.out.${jobId}`
          stderrPath = stderrPath || `${base}/std.err.${jobId}`
        }

        const summary = {
          backend: target.backend,
          region: String(args.region ?? '').trim() || '（由后端默认区域解析）',
          scheduler_id: String(args.scheduler_id ?? '').trim() || undefined,
          job_id: jobId,
          queue: queue || undefined,
          work_dir: resolvedWorkDir || undefined,
          stdout: stdoutPath || undefined,
          stderr: stderrPath || undefined,
          log_paths_source: source,
          precheck: precheck.note || undefined,
          note: '用 scnet_job_logs 读日志：直接传上面的 path，或传 job_id + work_dir。',
        }
        return JSON.stringify(summary, null, 2)
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_job_show',
      description:
        '只读查询一个作业的状态与资源（state / exit_code / work_dir / stdout / stderr）。作业完成较久后平台可能不再返回记录，此时用 scnet_job_logs 的 path 模式读日志即可。',
      parameters: {
        job_id: { type: 'string', required: true, description: '作业号' },
        backend: { type: 'string', description: 'openapi（默认）或 ssh' },
        region: { type: 'string', description: 'OpenAPI 区域；省略时用已保存的默认区域' },
        scheduler_id: { type: 'string', description: 'OpenAPI 调度器 ID；省略时自动' },
        cluster: { type: 'string', description: 'SSH 集群短名；省略时若只有一个 profile 则自动选择' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const jobId = String(args.job_id ?? '').trim()
        if (!jobId) return MISSING_HINTS.job_id
        const target = await resolveTarget(args)
        if (target.error) return target.error
        return scnetJobResult(await runScnet([...target.argv, 'job', jobId]), '查询作业')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_job_logs',
      description:
        '只读读取作业日志。两种模式：显式给 path（远端绝对路径，SSH 下只能用这个）；或给 job_id + work_dir + stream，内部按平台默认命名 std.out/std.err.{job_id} 推导。path 优先。',
      parameters: {
        path: { type: 'string', description: '显式模式：远端日志文件的绝对路径' },
        job_id: { type: 'string', description: '便捷模式：作业号' },
        work_dir: { type: 'string', description: '便捷模式：作业工作目录；省略时会尝试查一次作业' },
        stream: { type: 'string', description: '便捷模式：stdout（默认）或 stderr' },
        lines: { type: 'string', description: '读取行数，默认 200（1-10000）' },
        direction: { type: 'string', description: 'head 或 tail（默认 tail）' },
        backend: { type: 'string', description: 'openapi（默认）或 ssh' },
        region: { type: 'string', description: 'OpenAPI 区域；省略时用已保存的默认区域' },
        scheduler_id: { type: 'string', description: 'OpenAPI 调度器 ID；省略时自动' },
        cluster: { type: 'string', description: 'SSH 集群短名；省略时若只有一个 profile 则自动选择' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const target = await resolveTarget(args)
        if (target.error) return target.error

        const lines = positiveInt(args.lines, 'lines')
        if (lines && lines.error) return lines.error

        let path = String(args.path ?? '').trim()
        const jobId = String(args.job_id ?? '').trim()
        let derived = false

        if (!path) {
          if (target.backend === 'ssh') {
            return 'SSH 模式的日志路径由作业脚本里的 #SBATCH --output 决定，无法推导；请用 path 给出远端日志文件的绝对路径。'
          }
          if (!jobId) return `${MISSING_HINTS.path}（或给 job_id + work_dir 走便捷模式。）`
          const stream = String(args.stream ?? 'stdout').trim().toLowerCase()
          if (stream !== 'stdout' && stream !== 'stderr') return 'stream 只支持 stdout 或 stderr。'
          let workDir = String(args.work_dir ?? '').trim()
          if (!workDir) {
            const jobRes = await runScnetEnvelope([...target.argv, 'job', jobId])
            if (jobRes.ok && jobRes.data?.work_dir) {
              workDir = String(jobRes.data.work_dir)
            } else {
              return `缺 work_dir：查不到作业 ${jobId} 的工作目录（${jobRes.error || '平台无记录'}）。请补 work_dir，或直接用 path。`
            }
          }
          const suffix = stream === 'stderr' ? 'err' : 'out'
          path = `${workDir.replace(/\/+$/, '')}/std.${suffix}.${jobId}`
          derived = true
        }

        const argv = [...target.argv, 'logs', '--path', path]
        if (lines && lines.value) argv.push('--lines', lines.value)
        const direction = String(args.direction ?? '').trim()
        if (direction) argv.push('--direction', direction)

        const res = await runScnet(argv)
        if (!res.ok) return scnetJobResult(res, '读取日志')
        const body = res.stdout.trim() || '{}'
        return derived ? `${body}\n\n（日志路径由 job_id 与 work_dir 推导：${path}）` : body
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_job_cancel',
      description:
        '取消一个作业。这是变更操作，执行前应确认 job_id 与目标区域；dry_run=true 只预览不发送。超时后不要自动重试，先查状态。',
      parameters: {
        job_id: { type: 'string', required: true, description: '作业号' },
        backend: { type: 'string', description: 'openapi（默认）或 ssh' },
        region: { type: 'string', description: 'OpenAPI 区域；省略时用已保存的默认区域' },
        scheduler_id: { type: 'string', description: 'OpenAPI 调度器 ID；省略时自动' },
        cluster: { type: 'string', description: 'SSH 集群短名；省略时若只有一个 profile 则自动选择' },
        dry_run: { type: 'boolean', description: '只预览，不发送取消请求（默认否）' },
      },
      timeoutMs: 180000,
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const jobId = String(args.job_id ?? '').trim()
        if (!jobId) return MISSING_HINTS.job_id
        const target = await resolveTarget(args)
        if (target.error) return target.error
        const argv = [...target.argv]
        if (args.dry_run === true) argv.push('--dry-run')
        argv.push('cancel', jobId)
        return scnetJobResult(await runScnet(argv), '取消作业')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_file_list',
      description: '通过 OpenAPI 只读列出区域共享存储中的文件和目录。',
      parameters: {
        region: { type: 'string', description: '区域名称或 ID；省略时使用默认区域' },
        path: { type: 'string', description: '绝对目录路径；省略时使用区域用户主目录' },
        limit: { type: 'number', description: '最多返回条数，默认 100' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const argv = ['--backend', 'openapi', ...regionArgs(args.region), 'files']
        if (args.path) argv.push('--path', String(args.path))
        if (args.limit) argv.push('--limit', String(args.limit))
        return scnetResult(await runScnet(argv), '查询文件')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_notebook_regions',
      description: '只读列出支持 SCNet Notebook 服务的授权区域。',
      parameters: {},
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute() {
        return scnetResult(
          await runScnet(['--backend', 'openapi', 'notebook', 'regions']),
          '查询 Notebook 区域',
        )
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_notebook_resources',
      description: '只读查询目标区域可用于 Notebook 的 CPU/GPU/DCU 资源及当前空闲卡数。',
      parameters: {
        region: { type: 'string', description: '区域名称或 ID；省略时使用默认区域' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const argv = ['--backend', 'openapi', 'notebook', 'resources']
        if (args.region) argv.push('--region', String(args.region))
        return scnetResult(await runScnet(argv), '查询 Notebook 资源')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_notebook_list',
      description: '只读列出目标区域的 Notebook 实例；密码和带凭据的 URL 默认脱敏。',
      parameters: {
        region: { type: 'string', description: '区域名称或 ID；省略时使用默认区域' },
        status: { type: 'string', description: '可选状态过滤，如 Running、Terminated、Failed' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const argv = ['--backend', 'openapi', 'notebook', 'list']
        if (args.region) argv.push('--region', String(args.region))
        if (args.status) argv.push('--status', String(args.status))
        return scnetResult(await runScnet(argv), '查询 Notebook 实例')
      },
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'scnet_notebook_show',
      description: '只读查询一个 Notebook 实例详情；敏感字段默认脱敏。',
      parameters: {
        notebook_id: { type: 'string', required: true, description: 'Notebook 实例 ID' },
        region: { type: 'string', description: '区域名称或 ID；省略时使用默认区域' },
      },
      output: {
        schema: { type: 'string' },
        render: (_args, value) => textBlock(value),
      },
      async execute(args) {
        const id = String(args.notebook_id || '').trim()
        if (!id) return '缺少必填参数 notebook_id。'
        const argv = ['--backend', 'openapi', 'notebook', 'show', id]
        if (args.region) argv.push('--region', String(args.region))
        return scnetResult(await runScnet(argv), '查询 Notebook 详情')
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
        '按目标集群约束生成 Slurm 作业脚本。支持加速器作业、cpu_only CPU 分区和显式 partition 覆盖；自动计算内存、按需申请 GRES、加载 module、设置离线环境并传播退出码。',
      parameters: {
        name: { type: 'string', required: true, description: '作业名（slurm --job-name 和输出文件名）' },
        accelerators: { type: 'string', description: '加速器数量，默认 1' },
        cpus: { type: 'string', description: 'CPU 核数，默认 8' },
        time: { type: 'string', description: '时长，默认 00:20:00，格式 HH:MM:SS 或 D-HH:MM:SS' },
        cluster: { type: 'string', description: '集群短名；省略时若只有一个 profile 则自动选择' },
        remote_user: { type: 'string', description: '远端用户名；与本地不同时填写（日志路径需要真实用户名）' },
        cpu_only: { type: 'boolean', description: '使用 profile 的 PARTITION_CPU 且不申请 GRES（默认否）' },
        partition: { type: 'string', description: '显式覆盖目标 Slurm 分区；需自行确认该分区的 GRES 规则' },
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
        if (args.cpu_only === true) argv.push('--cpu-only')
        const partition = String(args.partition || '').trim()
        if (partition) argv.push('--partition', partition)
        if (args.refresh === true) argv.push('--refresh')
        if (args.no_auto === true) argv.push('--no-auto')
        argv.push(nameVal)
        const time = String(args.time || '').trim()
        if (accelerators || cpus || time) {
          argv.push(accelerators?.value || (args.cpu_only === true ? '0' : '1'))
        }
        if (cpus || time) argv.push(cpus?.value || '8')
        if (time) argv.push(time)

        const timeoutMs = args.refresh === true ? 240000 : 30000
        const res = await runBash(join(SCRIPTS_DIR, 'new-job.sh'), argv, timeoutMs, process.cwd())
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

// 仅供 tests/ 使用：把作业生命周期里的纯函数暴露出来做单元测试。
export const __testables = {
  MISSING_HINTS,
  SUBMIT_REQUIRED_ORDER,
  errorTextFrom,
  firstMissingRequired,
  parseWalltimeSeconds,
  pickBackend,
  queueCandidates,
  translateScnetError,
}
