- Desktop hosts can inject a verified Python 3 interpreter through `DSH_SCNET_PYTHON` or
  `SCNET_PYTHON`; local entrypoints no longer require the command name `python3`.
- Shared shell helpers reject Python 2 and invalid configured interpreters before running
  OpenAPI or local job-generation code.
