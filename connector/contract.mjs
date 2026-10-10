const OPERATION_DEFINITIONS = {
  login: { scope: 'openid', mutatesRemote: false, supportsDryRun: false },
  status: { scope: 'scnet.read', mutatesRemote: false, supportsDryRun: false },
  refresh: { scope: 'openid', mutatesRemote: false, supportsDryRun: false },
  logout: { scope: 'openid', mutatesRemote: true, supportsDryRun: false },
  linkAccount: { scope: 'account.link', mutatesRemote: true, supportsDryRun: true },
  unlinkAccount: { scope: 'account.link', mutatesRemote: true, supportsDryRun: true },
  listRegions: { scope: 'scnet.read', mutatesRemote: false, supportsDryRun: false },
  listSchedulers: { scope: 'scnet.read', mutatesRemote: false, supportsDryRun: false },
  listQueues: { scope: 'scnet.read', mutatesRemote: false, supportsDryRun: false },
  submitJob: { scope: 'jobs.submit', mutatesRemote: true, supportsDryRun: true },
  getJob: { scope: 'jobs.read', mutatesRemote: false, supportsDryRun: false },
  cancelJob: { scope: 'jobs.cancel', mutatesRemote: true, supportsDryRun: true },
  listFiles: { scope: 'files.read', mutatesRemote: false, supportsDryRun: false },
  transferFile: { scope: 'files.write', mutatesRemote: true, supportsDryRun: true },
}

export const SCNET_CONNECTOR_CONTRACT_VERSION = '0.1.0'
export const CONNECTOR_OPERATION_DEFINITIONS = Object.freeze(
  Object.fromEntries(
    Object.entries(OPERATION_DEFINITIONS).map(([name, definition]) => [name, Object.freeze({ ...definition })]),
  ),
)
export const CONNECTOR_CAPABILITY_STATES = Object.freeze([
  'supported',
  'unsupported',
  'requires-remote-host',
])

function nonEmptyString(value, label) {
  const normalized = String(value ?? '').trim()
  if (!normalized) throw new TypeError(`${label} must be a non-empty string`)
  return normalized
}

function normalizeState(value, operation) {
  const state = nonEmptyString(value, `capability ${operation}`)
  if (!CONNECTOR_CAPABILITY_STATES.includes(state)) {
    throw new TypeError(
      `capability ${operation} must be one of ${CONNECTOR_CAPABILITY_STATES.join(', ')}`,
    )
  }
  return state
}

export function createCapabilityMatrix(entries = {}) {
  if (entries === null || typeof entries !== 'object' || Array.isArray(entries)) {
    throw new TypeError('capabilities must be an object')
  }
  return Object.freeze(
    Object.fromEntries(
      Object.keys(OPERATION_DEFINITIONS).map((operation) => [
        operation,
        normalizeState(entries[operation] ?? 'unsupported', operation),
      ]),
    ),
  )
}

export function createConnectorDescriptor({
  id = 'scnet',
  version = SCNET_CONNECTOR_CONTRACT_VERSION,
  issuer,
  capabilities = {},
} = {}) {
  const descriptor = {
    contractVersion: SCNET_CONNECTOR_CONTRACT_VERSION,
    id: nonEmptyString(id, 'connector id'),
    version: nonEmptyString(version, 'connector version'),
    issuer: nonEmptyString(issuer, 'issuer'),
    capabilities: createCapabilityMatrix(capabilities),
  }
  return Object.freeze(descriptor)
}

export function getOperationDefinition(operation) {
  const name = nonEmptyString(operation, 'operation')
  const definition = CONNECTOR_OPERATION_DEFINITIONS[name]
  if (!definition) throw new RangeError(`unsupported connector operation: ${name}`)
  return definition
}

export function assertCapability(descriptor, operation, { allowRemoteHost = false } = {}) {
  if (!descriptor || typeof descriptor !== 'object') {
    throw new TypeError('connector descriptor is required')
  }
  const definition = getOperationDefinition(operation)
  const state = descriptor.capabilities?.[operation]
  if (state === 'supported' || (state === 'requires-remote-host' && allowRemoteHost)) {
    return definition
  }
  if (state === 'requires-remote-host') {
    throw new Error(`${operation} requires a remote host`)
  }
  throw new Error(`${operation} is not supported by connector ${descriptor.id || 'unknown'}`)
}
