// 作业生命周期工具的纯逻辑单元测试。运行：npm test（node --test）
import test from 'node:test'
import assert from 'node:assert/strict'

import { __testables } from '../index.mjs'

const {
  MISSING_HINTS,
  SUBMIT_REQUIRED_ORDER,
  errorTextFrom,
  errorCodeFrom,
  firstMissingRequired,
  parseWalltimeSeconds,
  pickBackend,
  queueCandidates,
  translateScnetError,
} = __testables

test('firstMissingRequired 按 CLI 必填顺序一次只报一个，且不含 queue', () => {
  assert.deepEqual(SUBMIT_REQUIRED_ORDER, ['name', 'command', 'work_dir'])
  assert.equal(firstMissingRequired({}, SUBMIT_REQUIRED_ORDER), 'name')
  assert.equal(firstMissingRequired({ name: 'j' }, SUBMIT_REQUIRED_ORDER), 'command')
  assert.equal(
    firstMissingRequired({ name: 'j', command: 'echo' }, SUBMIT_REQUIRED_ORDER),
    'work_dir',
  )
  assert.equal(
    firstMissingRequired({ name: 'j', command: 'echo', work_dir: '/w' }, SUBMIT_REQUIRED_ORDER),
    '',
  )
  // queue 交给队列预检：可能是自动选择，也可能是"请补一个"，不参与本地顺序
  assert.ok(!SUBMIT_REQUIRED_ORDER.includes('queue'))
})

test('parseWalltimeSeconds 支持 HH:MM:SS 与 D-HH:MM:SS', () => {
  assert.equal(parseWalltimeSeconds('00:05:00'), 300)
  assert.equal(parseWalltimeSeconds('24:00:00'), 86400)
  assert.equal(parseWalltimeSeconds('3-00:00:00'), 259200)
  assert.equal(parseWalltimeSeconds('333-08:00:00'), 28800000)
  assert.equal(parseWalltimeSeconds(''), null)
  assert.equal(parseWalltimeSeconds('5min'), null)
})

test('pickBackend 默认 openapi、显式值透传、非法值拒绝', () => {
  assert.deepEqual(pickBackend(undefined), {
    backend: 'openapi',
    argv: ['--backend', 'openapi'],
  })
  assert.deepEqual(pickBackend('  SSH '), { backend: 'ssh', argv: ['--backend', 'ssh'] })
  assert.match(pickBackend('slurm').error, /只支持 openapi 或 ssh/)
})

test('errorTextFrom 能从 --json 错误信封里取出 error', () => {
  const envelope = JSON.stringify({
    ok: false,
    operation: 'submit',
    error: 'missing required option: command',
  })
  assert.equal(
    errorTextFrom({ ok: false, stdout: envelope, stderr: '' }),
    'missing required option: command',
  )
  assert.equal(errorTextFrom({ ok: false, stdout: '', stderr: 'error: boom' }), 'boom')
})

test('errorCodeFrom 能读取结构化错误类别', () => {
  assert.equal(
    errorCodeFrom({ stdout: JSON.stringify({ error_code: 'NETWORK_TIMEOUT' }) }),
    'NETWORK_TIMEOUT',
  )
  assert.equal(errorCodeFrom({ stdout: 'plain error' }), '')
})

test('译错：缺失参数一次只给一条可执行提示', () => {
  assert.match(translateScnetError('missing required option: name'), /缺 name/)
  const workDir = translateScnetError('missing required option: work_dir')
  assert.match(workDir, /缺 work_dir/)
  assert.doesNotMatch(workDir, /name|queue|command/)
})

test('译错：多个调度器时保留候选列表', () => {
  const text = translateScnetError(
    'multiple schedulers are available; use --scheduler-id: cancon(1), other(2)',
  )
  assert.match(text, /补 scheduler_id 一个参数/)
  assert.match(text, /cancon\(1\)/)
})

test('译错：job 端点形状错误给出可执行解释，而不是原始内部报错', () => {
  const text = translateScnetError('job endpoint returned an unexpected data shape')
  assert.match(text, /path/)
  assert.doesNotMatch(text, /unexpected data shape/)
})

test('译错：实时和历史都无记录时提示核对作业号和区域', () => {
  const text = translateScnetError('realtime and history endpoints returned no job record')
  assert.match(text, /核对 job_id 和区域/)
  assert.doesNotMatch(text, /endpoints returned/)
})

test('译错：未命中的错误原样透出', () => {
  assert.equal(translateScnetError('some other failure'), 'some other failure')
})

test('MISSING_HINTS 覆盖 CLI 会要求的作业字段', () => {
  for (const key of ['name', 'command', 'work_dir', 'queue', 'remote_path', 'job_id', 'path']) {
    assert.equal(typeof MISSING_HINTS[key], 'string', `${key} 应有提示`)
    assert.ok(MISSING_HINTS[key].length > 0, `${key} 提示不应为空`)
  }
})

test('queueCandidates 按是否需要加速器筛选，并按空闲节点降序', () => {
  const queues = [
    { partition: 'cpu', max_dcus_per_node: '0', free_nodes: '0' },
    { partition: 'dcu-small', max_dcus_per_node: '4', free_nodes: '3' },
    { partition: 'dcu-big', max_dcus_per_node: '4', free_nodes: '279' },
  ]
  assert.deepEqual(
    queueCandidates(queues, true).map((q) => q.partition),
    ['dcu-big', 'dcu-small'],
  )
  assert.deepEqual(
    queueCandidates(queues, false).map((q) => q.partition),
    ['cpu'],
  )
})
