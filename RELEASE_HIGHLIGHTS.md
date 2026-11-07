- Refuse `--partition` on OpenAPI `limits` (it reports account quota) and point at `queues`,
  which already exposes partition node counts, free resources and max walltime.
- Report only the `AllowAccounts` count from SSH `limits` (full list stays behind `--raw`),
  removing thousands of unrelated user names from normal output.
- Strip Slurm's right-padded `%P` field so `queues` and `job` render identically from SSH and
  OpenAPI, and keep legitimate zero GPU/DCU counts in normalized jobs.
- Stream OpenAPI downloads through a temporary file instead of buffering the whole file, and give
  SSH `scp` transfers a long timeout so `--timeout 30` cannot abort a large transfer.
- Fix `SSH_PORT` resolution so a profile without a port uses the `~/.ssh/config` port, quote the
  remote `scontrol` argument, guard probe job IDs, and stop generating accelerator probes for
  CPU-only job skeletons.
- Add a `quota` operation on both backends and fix multi-node submits to send total cores, so
  requested CPU/DCU capacity matches what the scheduler is asked for.
