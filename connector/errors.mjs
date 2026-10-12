const ERROR_CODES = [
  'AUTHENTICATION_REQUIRED',
  'AUTHENTICATION_FAILED',
  'SCOPE_INSUFFICIENT',
  'NETWORK_TIMEOUT',
  'REGION_UNAVAILABLE',
  'PLATFORM_UNSUPPORTED',
  'CALLBACK_REPLAY',
  'CALLBACK_MISMATCH',
  'CONFIGURATION_REQUIRED',
  'INTERNAL_ERROR',
]

export const CONNECTOR_ERROR_CODES = Object.freeze(ERROR_CODES)

function requiredString(value, label) {
  const normalized = String(value ?? '').trim()
  if (!normalized) throw new TypeError(`${label} must be a non-empty string`)
  return normalized
}

export class ConnectorError extends Error {
  constructor(code, message, { operation, retryable = false } = {}) {
    if (!CONNECTOR_ERROR_CODES.includes(code)) {
      throw new RangeError(`unsupported connector error code: ${code}`)
    }
    super(requiredString(message, 'error message'))
    this.name = 'ConnectorError'
    this.code = code
    this.operation = operation === undefined ? undefined : requiredString(operation, 'operation')
    this.retryable = Boolean(retryable)
  }

  toJSON() {
    return {
      ok: false,
      error_code: this.code,
      error: this.message,
      ...(this.operation ? { operation: this.operation } : {}),
      retryable: this.retryable,
    }
  }
}

export function connectorError(code, message, options) {
  return new ConnectorError(code, message, options)
}

export function errorEnvelope(error, { operation } = {}) {
  if (error instanceof ConnectorError) {
    return error.toJSON()
  }
  return new ConnectorError(
    'INTERNAL_ERROR',
    error instanceof Error ? error.message : String(error || 'unknown connector error'),
    { operation },
  ).toJSON()
}
