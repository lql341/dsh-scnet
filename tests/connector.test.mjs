import test from 'node:test'
import assert from 'node:assert/strict'
import { request as httpRequest } from 'node:http'

import {
  CONNECTOR_ERROR_CODES,
  ConnectorError,
  createCredentialStoreAdapter,
  MemoryCredentialStore,
  TokenLifecycle,
  assertCapability,
  createAuthorizationRequest,
  createAuthorizationSession,
  createConnectorDescriptor,
  createPkceChallenge,
  createRefreshTokenRequest,
  createTokenExchangeRequest,
  listenLoopbackCallback,
  normalizeTokenResponse,
  validateAuthorizationCallback,
} from '../connector/index.mjs'

const requestOptions = {
  authorizationEndpoint: 'https://auth.example.test/oauth/authorize',
  clientId: 'dsh-scnet-desktop',
  redirectUri: 'http://127.0.0.1:43817/callback',
  issuer: 'https://auth.example.test',
  scope: ['openid', 'scnet.read'],
  state: 'state-1',
  nonce: 'nonce-1',
  codeVerifier: 'verifier-1',
}

test('creates an S256 PKCE authorization request without a client secret', () => {
  const request = createAuthorizationRequest(requestOptions)
  const url = new URL(request.url)
  assert.equal(url.searchParams.get('client_id'), requestOptions.clientId)
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256')
  assert.equal(url.searchParams.get('code_challenge'), createPkceChallenge('verifier-1'))
  assert.equal(url.searchParams.get('scope'), 'openid scnet.read')
  assert.equal(url.searchParams.has('client_secret'), false)
})

test('builds token exchange and refresh requests without a client secret', () => {
  const exchange = createTokenExchangeRequest({
    tokenEndpoint: 'https://auth.example.test/oauth/token',
    clientId: 'dsh-scnet-desktop',
    code: 'code-1',
    redirectUri: 'http://127.0.0.1:43817/callback',
    codeVerifier: 'verifier-1',
  })
  assert.equal(exchange.method, 'POST')
  assert.equal(exchange.headers['content-type'], 'application/x-www-form-urlencoded')
  assert.match(exchange.body, /grant_type=authorization_code/)
  assert.match(exchange.body, /code_verifier=verifier-1/)
  assert.doesNotMatch(exchange.body, /client_secret/)

  const refresh = createRefreshTokenRequest({
    tokenEndpoint: 'https://auth.example.test/oauth/token',
    clientId: 'dsh-scnet-desktop',
    refreshToken: 'refresh-1',
    scope: 'scnet.read',
  })
  assert.match(refresh.body, /grant_type=refresh_token/)
  assert.match(refresh.body, /scope=scnet.read/)
})

test('accepts a matching callback and rejects state or redirect mismatches', () => {
  const request = createAuthorizationRequest(requestOptions)
  assert.deepEqual(
    validateAuthorizationCallback(
      'http://127.0.0.1:43817/callback?code=abc&state=state-1&iss=https%3A%2F%2Fauth.example.test',
      request,
    ),
    { code: 'abc', state: 'state-1', issuer: 'https://auth.example.test' },
  )
  assert.throws(
    () => validateAuthorizationCallback('http://127.0.0.1:43817/callback?code=abc&state=wrong', request),
    /state mismatch/,
  )
  assert.throws(
    () => validateAuthorizationCallback('http://127.0.0.1:43818/callback?code=abc&state=state-1', request),
    /redirect URI does not match/,
  )
})

test('authorization sessions consume a callback once and classify replay', () => {
  const session = createAuthorizationSession(requestOptions)
  assert.equal(session.consumed, false)
  assert.deepEqual(
    session.consumeCallback(
      'http://127.0.0.1:43817/callback?code=abc&state=state-1&iss=https%3A%2F%2Fauth.example.test',
    ),
    { code: 'abc', state: 'state-1', issuer: 'https://auth.example.test' },
  )
  assert.equal(session.consumed, true)
  assert.throws(
    () => session.consumeCallback('http://127.0.0.1:43817/callback?code=abc&state=state-1'),
    (error) => error instanceof ConnectorError && error.code === 'CALLBACK_REPLAY',
  )
})

test('loopback callback listener consumes one matching request and closes', async () => {
  let session
  const listener = await listenLoopbackCallback({
    redirectUri: 'http://127.0.0.1:0/callback',
    consumeCallback: (url) => session.consumeCallback(url),
  })
  session = createAuthorizationSession({ ...requestOptions, redirectUri: listener.redirectUri })
  const callback = new URL(listener.redirectUri)
  callback.search = '?code=abc&state=state-1&iss=https%3A%2F%2Fauth.example.test'
  const response = await new Promise((resolve, reject) => {
    const request = httpRequest(callback, (res) => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => { body += chunk })
      res.on('end', () => resolve({ status: res.statusCode, body }))
    })
    request.on('error', reject)
    request.end()
  })
  assert.equal(response.status, 200)
  assert.match(response.body, /doctype html/)
  assert.deepEqual(await listener.waitForCallback(), {
    code: 'abc',
    state: 'state-1',
    issuer: 'https://auth.example.test',
  })
  assert.equal(session.consumed, true)
})

test('loopback callback listener rejects a wrong path and times out without exposing details', async () => {
  const listener = await listenLoopbackCallback({
    redirectUri: 'http://127.0.0.1:0/callback',
    consumeCallback: () => {
      throw new Error('private callback detail')
    },
    timeoutMs: 25,
  })
  const wrongPath = new URL(listener.redirectUri)
  wrongPath.pathname = '/other'
  const response = await new Promise((resolve, reject) => {
    const request = httpRequest(wrongPath, (res) => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => { body += chunk })
      res.on('end', () => resolve({ status: res.statusCode, body }))
    })
    request.on('error', reject)
    request.end()
  })
  assert.equal(response.status, 404)
  assert.doesNotMatch(response.body, /private callback detail/)
  await assert.rejects(listener.waitForCallback(), (error) => error.code === 'CALLBACK_MISMATCH' && /timed out/.test(error.message))
})

test('connector errors produce stable safe envelopes', () => {
  assert.ok(CONNECTOR_ERROR_CODES.includes('AUTHENTICATION_REQUIRED'))
  const error = new ConnectorError('NETWORK_TIMEOUT', 'SCNet request timed out', {
    operation: 'listRegions',
    retryable: true,
  })
  assert.deepEqual(error.toJSON(), {
    ok: false,
    error_code: 'NETWORK_TIMEOUT',
    error: 'SCNet request timed out',
    operation: 'listRegions',
    retryable: true,
  })
  assert.doesNotMatch(JSON.stringify(error.toJSON()), /access|refresh|secret|token/i)
})

test('credential store adapter namespaces keys and has no plaintext fallback', async () => {
  const values = new Map()
  const calls = []
  const adapter = createCredentialStoreAdapter({
    namespace: 'desktop.scnet',
    backend: {
      async get(key) {
        calls.push(['get', key])
        return values.get(key)
      },
      async set(key, value) {
        calls.push(['set', key])
        values.set(key, value)
      },
      async delete(key) {
        calls.push(['delete', key])
        values.delete(key)
      },
    },
  })
  await adapter.set('tokens', { accessToken: 'secret' })
  assert.deepEqual(await adapter.get('tokens'), { accessToken: 'secret' })
  assert.deepEqual(calls.slice(0, 2), [
    ['set', 'desktop.scnet.tokens'],
    ['get', 'desktop.scnet.tokens'],
  ])
  assert.equal(typeof adapter.clear, 'function')
  await adapter.delete('tokens')
  assert.equal(await adapter.get('tokens'), undefined)
})

test('rejects an authorization error and an unexpected issuer', () => {
  const request = createAuthorizationRequest(requestOptions)
  assert.throws(
    () =>
      validateAuthorizationCallback(
        'http://127.0.0.1:43817/callback?error=access_denied&error_description=cancelled&state=state-1',
        request,
      ),
    /access_denied \(cancelled\)/,
  )
  assert.throws(
    () =>
      validateAuthorizationCallback(
        'http://127.0.0.1:43817/callback?code=abc&state=state-1&iss=https%3A%2F%2Fevil.example.test',
        request,
      ),
    /issuer mismatch/,
  )
})

test('normalizes token responses without exposing token values in status', async () => {
  const lifecycle = new TokenLifecycle({
    now: () => 1000,
  })
  await lifecycle.save({
    access_token: 'access-secret',
    refresh_token: 'refresh-secret',
    token_type: 'Bearer',
    expires_in: 3600,
    scope: 'openid scnet.read',
  })
  assert.deepEqual(await lifecycle.status(), {
    authenticated: true,
    expiresAt: 3601000,
    hasRefreshToken: true,
    scope: 'openid scnet.read',
  })
})

test('refreshes an expired token once for concurrent callers', async () => {
  let now = 1000
  let refreshes = 0
  const lifecycle = new TokenLifecycle({
    now: () => now,
    store: new MemoryCredentialStore(),
  })
  await lifecycle.save({
    access_token: 'old',
    refresh_token: 'refresh',
    expires_in: 1,
  })
  now = 40000
  const refresh = async (refreshToken) => {
    refreshes += 1
    assert.equal(refreshToken, 'refresh')
    return { access_token: 'new', refresh_token: 'refresh', expires_in: 3600 }
  }
  assert.deepEqual(await Promise.all([lifecycle.accessToken({ refresh }), lifecycle.accessToken({ refresh })]), [
    'new',
    'new',
  ])
  assert.equal(refreshes, 1)
})

test('clears credentials and reports authentication as required', async () => {
  const lifecycle = new TokenLifecycle()
  await lifecycle.save({ access_token: 'secret', expires_in: 3600 })
  await lifecycle.clear()
  assert.deepEqual(await lifecycle.status(), { authenticated: false, expiresAt: undefined })
  await assert.rejects(() => lifecycle.accessToken(), /authentication required/)
})

test('describes platform capability states and protects unsupported operations', () => {
  const descriptor = createConnectorDescriptor({
    issuer: 'https://auth.example.test',
    capabilities: {
      listRegions: 'supported',
      submitJob: 'requires-remote-host',
    },
  })
  assert.equal(assertCapability(descriptor, 'listRegions').mutatesRemote, false)
  assert.equal(assertCapability(descriptor, 'listRegions').scope, 'scnet.read')
  assert.throws(() => assertCapability(descriptor, 'submitJob'), /requires a remote host/)
  assert.equal(assertCapability(descriptor, 'submitJob', { allowRemoteHost: true }).supportsDryRun, true)
})
