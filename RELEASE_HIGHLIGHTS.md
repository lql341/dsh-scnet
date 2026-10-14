- Default CLI output is compact across OpenAPI and SSH, with `--details` and `--raw` for
  progressively richer responses and bounded internal job waiting to reduce repeated output.
- OpenAPI completion is confirmed against accounting before it becomes terminal, and SSH job
  lookup falls back to accounting after a job leaves the live queue.
- First-use setup defaults to OpenAPI, retains existing backend preferences, and preserves
  unrelated configuration fields when settings are updated.
