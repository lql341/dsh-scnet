function requiredString(value, label) {
  const normalized = String(value ?? '').trim()
  if (!normalized) throw new TypeError(`${label} must be a non-empty string`)
  return normalized
}

function assertBackend(backend) {
  if (!backend || typeof backend !== 'object') {
    throw new TypeError('credential backend is required')
  }
  for (const method of ['get', 'set', 'delete']) {
    if (typeof backend[method] !== 'function') {
      throw new TypeError(`credential backend must implement ${method}()`)
    }
  }
  return backend
}

/**
 * Adapt a platform keyring implementation without providing a plaintext fallback.
 * The backend owns encryption, locking, and OS-specific Secret Service behavior.
 */
export function createCredentialStoreAdapter({ backend, namespace = 'scnet' } = {}) {
  const store = assertBackend(backend)
  const prefix = requiredString(namespace, 'credential namespace')
  const keyOf = (key) => `${prefix}.${requiredString(key, 'credential key')}`
  return Object.freeze({
    async get(key) {
      return store.get(keyOf(key))
    },
    async set(key, value) {
      if (value === undefined) throw new TypeError('credential value must not be undefined')
      return store.set(keyOf(key), structuredClone(value))
    },
    async delete(key) {
      return store.delete(keyOf(key))
    },
    async clear() {
      if (typeof store.clear === 'function') return store.clear(prefix)
    },
  })
}
