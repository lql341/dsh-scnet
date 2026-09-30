"""SSH/Slurm backend."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .base import Backend, BackendError, require_option
from .profile import list_profiles


def _split_pipe(line: str, fields: list[str]) -> dict[str, str]:
    values = line.rstrip("\n").split("|")
    values += [""] * max(0, len(fields) - len(values))
    return dict(zip(fields, values))


class SSHBackend(Backend):
    name = "ssh"
    capabilities = frozenset(
        {
            "clusters",
            "queues",
            "limits",
            "job",
            "logs",
            "submit",
            "cancel",
            "upload",
            "download",
            "exec",
        }
    )

    def _alias(self) -> str:
        alias = self.context.profile.get("CLUSTER_ID")
        if not alias:
            raise BackendError("SSH operations require --cluster and a CLUSTER_ID profile field")
        return alias

    def _run(self, argv: list[str], *, input_text: str | None = None) -> str:
        try:
            completed = subprocess.run(
                argv,
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.context.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendError(str(exc)) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise BackendError(
                f"command failed with exit {completed.returncode}: {detail or argv[0]}"
            )
        return completed.stdout

    def _ssh(self, remote_command: str) -> str:
        return self._run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={min(self.context.timeout, 30)}",
                self._alias(),
                remote_command,
            ]
        )

    def op_clusters(self, options: Mapping[str, Any]) -> Any:
        del options
        return list_profiles(self.context.repo_root)

    def op_queues(self, options: Mapping[str, Any]) -> Any:
        del options
        output = self._ssh(
            "LC_ALL=C sinfo -h -o '%P|%a|%l|%D|%C|%G'"
        )
        fields = [
            "partition",
            "availability",
            "max_walltime",
            "nodes",
            "cpu_state",
            "gres",
        ]
        rows = [_split_pipe(line, fields) for line in output.splitlines() if line.strip()]
        for row in rows:
            row["partition"] = row["partition"].rstrip("*")
        return rows

    def op_limits(self, options: Mapping[str, Any]) -> Any:
        partition = (
            options.get("partition")
            or self.context.profile.get("PARTITION")
            or self.context.profile.get("PARTITION_CPU")
        )
        if not partition:
            raise BackendError("limits requires --partition or a PARTITION profile field")
        if not str(partition).replace("-", "").replace("_", "").isalnum():
            raise BackendError("partition contains unsafe characters")
        output = self._ssh(
            f"LC_ALL=C scontrol show partition {shlex.quote(str(partition))} -o"
        ).strip()
        parsed: dict[str, str] = {"partition": str(partition)}
        for token in output.split():
            if "=" in token:
                key, value = token.split("=", 1)
                parsed[key] = value
        keep = {
            "partition",
            "State",
            "TotalNodes",
            "TotalCPUs",
            "DefMemPerCPU",
            "DefMemPerNode",
            "MaxMemPerCPU",
            "MaxMemPerNode",
            "MaxTime",
            "MinNodes",
            "MaxNodes",
            "AllowAccounts",
            "AllowQos",
            "QoS",
            "TRES",
        }
        return {key: value for key, value in parsed.items() if key in keep}

    def op_job(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        if not job_id.replace("_", "").isalnum():
            raise BackendError("job id contains unsafe characters")
        fields = [
            "job_id",
            "state",
            "partition",
            "elapsed",
            "time_limit",
            "nodes",
            "cpus",
            "reason_or_nodes",
        ]
        output = self._ssh(
            "LC_ALL=C squeue -h "
            f"-j {shlex.quote(job_id)} -o '%i|%T|%P|%M|%l|%D|%C|%R'"
        ).strip()
        if output:
            return _split_pipe(output.splitlines()[0], fields)
        output = self._ssh(
            "LC_ALL=C sacct -n -X "
            f"-j {shlex.quote(job_id)} "
            "--format=JobIDRaw,State,Partition,Elapsed,Timelimit,NNodes,NCPUS,ExitCode -P"
        ).strip()
        if not output:
            raise BackendError(f"job {job_id!r} was not found")
        history_fields = fields[:-1] + ["exit_code"]
        return _split_pipe(output.splitlines()[0], history_fields)

    def op_logs(self, options: Mapping[str, Any]) -> Any:
        path = str(require_option(options, "path"))
        if not path.startswith("/") or "\n" in path or "\x00" in path:
            raise BackendError("remote log path must be a safe absolute path")
        lines = int(options.get("lines") or 200)
        if lines < 1 or lines > 10000:
            raise BackendError("--lines must be between 1 and 10000")
        direction = options.get("direction") or "tail"
        command = "tail" if direction == "tail" else "head"
        output = self._ssh(
            f"{command} -n {lines} -- {shlex.quote(path)}"
        )
        return {"path": path, "direction": direction, "lines": output.splitlines()}

    def op_submit(self, options: Mapping[str, Any]) -> Any:
        remote_path = str(require_option(options, "remote_path"))
        if not remote_path.startswith("/") or "\n" in remote_path:
            raise BackendError("SSH submit requires a safe absolute --remote-path")
        output = self._ssh(
            f"sbatch --parsable -- {shlex.quote(remote_path)}"
        ).strip()
        return {"job_id": output.split(";", 1)[0], "raw": output}

    def preview_submit(self, options: Mapping[str, Any]) -> Any:
        remote_path = str(require_option(options, "remote_path"))
        if not remote_path.startswith("/") or "\n" in remote_path:
            raise BackendError("SSH submit requires a safe absolute --remote-path")
        return {
            "backend": self.name,
            "operation": "submit",
            "command": [
                "ssh",
                self._alias(),
                "sbatch --parsable -- " + shlex.quote(remote_path),
            ],
            "remote_path": remote_path,
        }

    def op_cancel(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        if not job_id.replace("_", "").isalnum():
            raise BackendError("job id contains unsafe characters")
        self._ssh(f"scancel -- {shlex.quote(job_id)}")
        return {"job_id": job_id, "cancelled": True}

    def preview_cancel(self, options: Mapping[str, Any]) -> Any:
        job_id = str(require_option(options, "job_id"))
        if not job_id.replace("_", "").isalnum():
            raise BackendError("job id contains unsafe characters")
        return {
            "backend": self.name,
            "operation": "cancel",
            "command": ["ssh", self._alias(), "scancel -- " + shlex.quote(job_id)],
            "job_id": job_id,
        }

    def op_upload(self, options: Mapping[str, Any]) -> Any:
        local_path = Path(str(require_option(options, "local_path"))).expanduser()
        remote_path = str(
            options.get("remote_dir")
            or require_option(options, "remote_path")
        )
        if not local_path.is_file():
            raise BackendError(f"local file does not exist: {local_path}")
        if not remote_path.startswith("/") or "\n" in remote_path:
            raise BackendError("remote path must be a safe absolute path")
        remote_q = shlex.quote(remote_path)
        name_q = shlex.quote(local_path.name)
        check = self._ssh(
            f"target={remote_q}; "
            f"if test -d \"$target\"; then target=\"$target\"/{name_q}; fi; "
            "if test -e \"$target\"; then state=EXISTS; else state=MISSING; fi; "
            "printf '%s\\n%s\\n' \"$state\" \"$target\""
        ).splitlines()
        state = check[0] if check else ""
        destination = check[1] if len(check) > 1 else remote_path
        if state == "EXISTS" and not options.get("cover"):
            raise BackendError("remote path already exists; pass --cover to overwrite it")
        self._run(["scp", str(local_path), f"{self._alias()}:{remote_path}"])
        return {"local_path": str(local_path), "remote_path": destination}

    def op_download(self, options: Mapping[str, Any]) -> Any:
        remote_path = str(require_option(options, "remote_path"))
        local_path = Path(str(require_option(options, "local_path"))).expanduser()
        if not remote_path.startswith("/") or "\n" in remote_path:
            raise BackendError("remote path must be a safe absolute path")
        if local_path.exists() and not options.get("cover"):
            raise BackendError("local path already exists; pass --cover to overwrite it")
        self._run(["scp", "-r", f"{self._alias()}:{remote_path}", str(local_path)])
        return {"remote_path": remote_path, "local_path": str(local_path)}

    def op_exec(self, options: Mapping[str, Any]) -> Any:
        command = str(require_option(options, "command"))
        if "\x00" in command:
            raise BackendError("command contains a NUL byte")
        output = self._ssh(command)
        return {"stdout": output}
