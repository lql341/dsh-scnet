- The connector now exposes stable error codes and JSON-safe envelopes for authentication,
  callback, network, scope, region, and platform failures.
- OAuth callback sessions are one-shot and reject replay; platform keyring adapters have no
  plaintext fallback.
