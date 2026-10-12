import { createServer } from 'node:http'
import { ConnectorError } from './errors.mjs'

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', '[::1]', 'localhost'])
const CALLBACK_TIMEOUT_MS = 120000

function requiredString(value, label) {
  const normalized = String(value ?? '').trim()
  if (!normalized) throw new TypeError(`${label} must be a non-empty string`)
  return normalized
}

function parseLoopbackRedirect(value) {
  let redirect
  try {
    redirect = new URL(requiredString(value, 'redirectUri'))
  } catch {
    throw new TypeError('redirectUri must be a valid URL')
  }
  if (redirect.protocol !== 'http:' || !LOOPBACK_HOSTS.has(redirect.hostname)) {
    throw new TypeError('redirectUri must use an http loopback address')
  }
  if (!redirect.pathname || redirect.pathname === '/') {
    throw new TypeError('redirectUri must include a callback path')
  }
  if (redirect.username || redirect.password || redirect.hash) {
    throw new TypeError('redirectUri must not include credentials or a fragment')
  }
  return redirect
}

function responseBody(res, statusCode, body) {
  const content = Buffer.from(body, 'utf8')
  res.writeHead(statusCode, {
    'content-type': 'text/html; charset=utf-8',
    'content-length': content.byteLength,
    connection: 'close',
  })
  res.end(content)
}

/**
 * Start a one-shot local OAuth callback listener.
 *
 * The listener is deliberately protocol-neutral: the caller owns the
 * authorization session and provides its callback consumer. No token or
 * callback error is written to the browser response.
 */
export async function listenLoopbackCallback({
  redirectUri,
  consumeCallback,
  timeoutMs = CALLBACK_TIMEOUT_MS,
} = {}) {
  const requested = parseLoopbackRedirect(redirectUri)
  if (typeof consumeCallback !== 'function') {
    throw new TypeError('consumeCallback must be a function')
  }
  const timeout = Number(timeoutMs)
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new TypeError('timeoutMs must be a positive number')
  }

  const server = createServer((req, res) => {
    if (settled) {
      responseBody(res, 410, '<!doctype html><title>Callback closed</title>')
      return
    }
    const host = req.headers.host
    const callbackUrl = host ? new URL(req.url || '/', `${requested.protocol}//${host}`) : undefined
    if (req.method !== 'GET' || !callbackUrl || callbackUrl.pathname !== requested.pathname) {
      responseBody(res, 404, '<!doctype html><title>Not found</title>')
      return
    }
    settle(callbackUrl.href, res)
  })

  let settled = false
  let timer
  let resolveResult
  let rejectResult
  const result = new Promise((resolve, reject) => {
    resolveResult = resolve
    rejectResult = reject
  })

  function closeServer() {
    if (timer) clearTimeout(timer)
    if (server.listening) server.close()
  }

  function settle(callbackUrl, res) {
    if (settled) return
    settled = true
    try {
      const value = consumeCallback(callbackUrl)
      if (res) responseBody(res, 200, '<!doctype html><title>Authorization complete</title>')
      resolveResult(value)
    } catch (error) {
      if (res) responseBody(res, 400, '<!doctype html><title>Authorization failed</title>')
      rejectResult(
        error instanceof ConnectorError
          ? error
          : new ConnectorError('CALLBACK_MISMATCH', error?.message || 'OAuth callback rejected', {
              operation: 'login',
            }),
      )
    } finally {
      closeServer()
    }
  }

  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen({
      host: requested.hostname,
      port: requested.port,
      exclusive: true,
    }, resolve)
  }).catch((error) => {
    closeServer()
    throw new ConnectorError('CALLBACK_MISMATCH', 'Unable to open the local OAuth callback listener', {
      operation: 'login',
    })
  })

  const address = server.address()
  if (!address || typeof address === 'string') {
    closeServer()
    throw new ConnectorError('CALLBACK_MISMATCH', 'Local OAuth callback listener returned no address', {
      operation: 'login',
    })
  }
  const actualRedirect = new URL(requested.href)
  actualRedirect.port = String(address.port)

  timer = setTimeout(() => {
    if (settled) return
    settled = true
    rejectResult(new ConnectorError('CALLBACK_MISMATCH', 'OAuth callback timed out', { operation: 'login' }))
    closeServer()
  }, timeout)
  timer.unref?.()

  return Object.freeze({
    redirectUri: actualRedirect.href,
    waitForCallback: () => result,
    close() {
      if (settled) return
      settled = true
      rejectResult(new ConnectorError('CALLBACK_MISMATCH', 'OAuth callback listener closed', { operation: 'login' }))
      closeServer()
    },
  })
}
