import test from 'node:test'
import assert from 'node:assert/strict'

import {
  MemoryCredentialStore,
  TokenLifecycle,
  assertCapability,
  createAuthorizationRequest,
  createConnectorDescriptor,
  createPkceChallenge,
  createRefreshTokenRequest,
  createTokenExchangeRequest,
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
