import { createHash, randomBytes, randomUUID } from 'node:crypto'

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '[::1]', 'localhost'])

function requiredString(value, label) {
  const normalized = String(value ?? '').trim()
  if (!normalized) throw new TypeError(`${label} must be a non-empty string`)
  return normalized
}

function parseUrl(value, label) {
  let parsed
  try {
    parsed = new URL(requiredString(value, label))
  } catch {
    throw new TypeError(`${label} must be a valid URL`)
  }
  return parsed
}

function assertHttpsEndpoint(value, label) {
  const parsed = parseUrl(value, label)
  if (parsed.protocol !== 'https:') {
    throw new TypeError(`${label} must use https`)
  }
  return parsed
}

function assertRedirectUri(value) {
  const parsed = parseUrl(value, 'redirectUri')
  const isLoopback = parsed.protocol === 'http:' && LOOPBACK_HOSTS.has(parsed.hostname)
  if (parsed.protocol !== 'https:' && !isLoopback) {
    throw new TypeError('redirectUri must use https or a loopback http address')
  }
  return parsed
}

function base64url(value) {
  return Buffer.from(value).toString('base64url')
}

export function createCodeVerifier() {
  return base64url(randomBytes(32))
}

export function createPkceChallenge(codeVerifier) {
  const verifier = requiredString(codeVerifier, 'codeVerifier')
  return base64url(createHash('sha256').update(verifier).digest())
}

export function createAuthorizationRequest({
  authorizationEndpoint,
  clientId,
  redirectUri,
  issuer,
  scope = [],
  state = randomUUID(),
  nonce = randomUUID(),
  codeVerifier = createCodeVerifier(),
} = {}) {
  const endpoint = assertHttpsEndpoint(authorizationEndpoint, 'authorizationEndpoint')
  const redirect = assertRedirectUri(redirectUri)
  const client = requiredString(clientId, 'clientId')
  const normalizedIssuer = issuer === undefined ? undefined : assertHttpsEndpoint(issuer, 'issuer').origin
  const scopes = Array.isArray(scope) ? scope : String(scope).split(/\s+/)
  const normalizedScopes = [...new Set(scopes.map((item) => String(item).trim()).filter(Boolean))]
  if (normalizedScopes.length === 0) throw new TypeError('scope must contain at least one value')

  const params = new URLSearchParams({
    client_id: client,
    redirect_uri: redirect.href,
    response_type: 'code',
    scope: normalizedScopes.join(' '),
    code_challenge: createPkceChallenge(codeVerifier),
    code_challenge_method: 'S256',
    state: requiredString(state, 'state'),
    nonce: requiredString(nonce, 'nonce'),
  })
  return Object.freeze({
    url: `${endpoint.href}${endpoint.search ? '&' : '?'}${params}`,
    authorizationEndpoint: endpoint.href,
    clientId: client,
    redirectUri: redirect.href,
    issuer: normalizedIssuer,
    scope: Object.freeze(normalizedScopes),
    state,
    nonce,
    codeVerifier,
  })
}

function assertExactRedirect(callbackUrl, redirectUri) {
  const actual = parseUrl(callbackUrl, 'callbackUrl')
  const expected = assertRedirectUri(redirectUri)
  if (actual.origin !== expected.origin || actual.pathname !== expected.pathname) {
    throw new Error('OAuth callback redirect URI does not match the request')
  }
  if (actual.port !== expected.port || actual.hash !== expected.hash) {
    throw new Error('OAuth callback redirect URI does not match the request')
  }
  for (const [key, value] of expected.searchParams) {
    if (actual.searchParams.get(key) !== value) {
      throw new Error('OAuth callback redirect URI does not match the request')
    }
  }
  return actual
}

export function validateAuthorizationCallback(callbackUrl, request) {
  const callback = assertExactRedirect(callbackUrl, request.redirectUri)
  const returnedState = callback.searchParams.get('state')
  if (returnedState !== request.state) throw new Error('OAuth state mismatch')

  const error = callback.searchParams.get('error')
  if (error) {
    const description = callback.searchParams.get('error_description')
    throw new Error(`OAuth authorization failed: ${error}${description ? ` (${description})` : ''}`)
  }

  const code = callback.searchParams.get('code')
  if (!code) throw new Error('OAuth callback did not contain an authorization code')
  if (request.issuer !== undefined) {
    const returnedIssuer = callback.searchParams.get('iss')
    if (returnedIssuer !== request.issuer) throw new Error('OAuth issuer mismatch')
  }
  return Object.freeze({
    code,
    state: returnedState,
    issuer: callback.searchParams.get('iss') || undefined,
  })
}

export function createTokenExchangeRequest({
  tokenEndpoint,
  clientId,
  code,
  redirectUri,
  codeVerifier,
}) {
  const endpoint = assertHttpsEndpoint(tokenEndpoint, 'tokenEndpoint')
  const redirect = assertRedirectUri(redirectUri)
  const params = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: requiredString(clientId, 'clientId'),
    code: requiredString(code, 'code'),
    redirect_uri: redirect.href,
    code_verifier: requiredString(codeVerifier, 'codeVerifier'),
  })
  return Object.freeze({
    method: 'POST',
    url: endpoint.href,
    headers: Object.freeze({ 'content-type': 'application/x-www-form-urlencoded' }),
    body: params.toString(),
  })
}

export function createRefreshTokenRequest({ tokenEndpoint, clientId, refreshToken, scope } = {}) {
  const endpoint = assertHttpsEndpoint(tokenEndpoint, 'tokenEndpoint')
  const params = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: requiredString(clientId, 'clientId'),
    refresh_token: requiredString(refreshToken, 'refreshToken'),
  })
  if (scope !== undefined) params.set('scope', requiredString(scope, 'scope'))
  return Object.freeze({
    method: 'POST',
    url: endpoint.href,
    headers: Object.freeze({ 'content-type': 'application/x-www-form-urlencoded' }),
    body: params.toString(),
  })
}

export function normalizeTokenResponse(response, now = Date.now()) {
  if (!response || typeof response !== 'object') throw new TypeError('token response must be an object')
  const accessToken = requiredString(response.access_token, 'access_token')
  const refreshToken = response.refresh_token === undefined ? undefined : requiredString(response.refresh_token, 'refresh_token')
  const tokenType = String(response.token_type || 'Bearer')
  const expiresIn = Number(response.expires_in)
  if (!Number.isFinite(expiresIn) || expiresIn <= 0) throw new TypeError('expires_in must be a positive number')
  return Object.freeze({
    accessToken,
    refreshToken,
    tokenType,
    scope: response.scope ? String(response.scope) : undefined,
    expiresAt: now + expiresIn * 1000,
  })
}

export class MemoryCredentialStore {
  #values = new Map()

  async get(key) {
    return this.#values.get(requiredString(key, 'credential key'))
  }

  async set(key, value) {
    const normalizedKey = requiredString(key, 'credential key')
    if (value === undefined) throw new TypeError('credential value must not be undefined')
    this.#values.set(normalizedKey, structuredClone(value))
  }

  async delete(key) {
    this.#values.delete(requiredString(key, 'credential key'))
  }

  async clear() {
    this.#values.clear()
  }
}

export class TokenLifecycle {
  #store
  #key
  #now
  #refreshPromise

  constructor({ store = new MemoryCredentialStore(), key = 'scnet.tokens', now = () => Date.now() } = {}) {
    this.#store = store
    this.#key = requiredString(key, 'token key')
    this.#now = now
  }

  async save(tokenResponse) {
    const token = normalizeTokenResponse(tokenResponse, this.#now())
    await this.#store.set(this.#key, token)
    return this.status()
  }

  async status() {
    const token = await this.#store.get(this.#key)
    if (!token) return { authenticated: false, expiresAt: undefined }
    return {
      authenticated: true,
      expiresAt: token.expiresAt,
      hasRefreshToken: Boolean(token.refreshToken),
      scope: token.scope,
    }
  }

  async accessToken({ refresh } = {}) {
    const token = await this.#store.get(this.#key)
    if (!token) throw new Error('SCNet authentication required')
    if (token.expiresAt > this.#now() + 30000) return token.accessToken
    if (typeof refresh !== 'function' || !token.refreshToken) {
      throw new Error('SCNet access token expired; re-authentication required')
    }
    if (!this.#refreshPromise) {
      this.#refreshPromise = Promise.resolve()
        .then(() => refresh(token.refreshToken))
        .then((response) => this.save(response))
        .finally(() => {
          this.#refreshPromise = undefined
        })
    }
    await this.#refreshPromise
    const refreshed = await this.#store.get(this.#key)
    return refreshed.accessToken
  }

  async clear() {
    await this.#store.delete(this.#key)
  }
}
