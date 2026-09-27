"""CLI adapter for the internal SCNet service client."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

from scnet_backends.base import BackendContext, BackendError

from .client import SCNetClient
from .notebook import NotebookService


def add_notebook_parser(subparsers: Any) -> None:
    notebook = subparsers.add_parser(
        "notebook", help="inspect SCNet Notebook resources and instances"
    )
    notebook.add_argument(
        "--region",
        default=argparse.SUPPRESS,
        help="region name or ID; otherwise use the saved Notebook default",
    )
    commands = notebook.add_subparsers(
        dest="notebook_operation", required=True
    )
    regions = commands.add_parser("regions", help="list Notebook-capable regions")

    resources = commands.add_parser(
        "resources", help="list Notebook accelerator resources"
    )
    resources.add_argument("--region", default=argparse.SUPPRESS)
    resources.add_argument("--resource-id", default="")

    images = commands.add_parser("images", help="list Notebook images")
    images.add_argument("--region", default=argparse.SUPPRESS)
    images.add_argument("--access", choices=("public", "private"), default="public")
    images.add_argument("--type", dest="image_type", default="")
    images.add_argument("--accelerator-type", default="")
    images.add_argument("--name", default="")
    images.add_argument("--start", type=int, default=0)
    images.add_argument("--limit", type=int, default=20)

    listing = commands.add_parser("list", help="list Notebook instances")
    listing.add_argument("--region", default=argparse.SUPPRESS)
    listing.add_argument("--name", default="")
    listing.add_argument("--status", default="")
    listing.add_argument("--page", type=int, default=1)
    listing.add_argument("--size", type=int, default=20)

    show = commands.add_parser("show", help="show one Notebook instance")
    show.add_argument("--region", default=argparse.SUPPRESS)
    show.add_argument("notebook_id")

    url = commands.add_parser("url", help="show the Jupyter access status")
    url.add_argument("--region", default=argparse.SUPPRESS)
    url.add_argument("notebook_id")
    url.add_argument(
        "--reveal",
        action="store_true",
        help="include the sensitive URL with embedded credentials",
    )

    create = commands.add_parser(
        "create", help="create a minimal Notebook with safe automatic defaults"
    )
    create.add_argument("--region", default=argparse.SUPPRESS)
    create.add_argument("--resource-group", default="")
    create.add_argument("--image-id", default="")
    create.add_argument("--cards", type=int, default=1)
    create.add_argument("--no-mount-home", action="store_true")
    create.add_argument("--start-command", default="")
    create.add_argument("--no-wait", action="store_true")
    create.add_argument("--timeout", type=int, default=600)
    create.add_argument("--yes", action="store_true")

    start = commands.add_parser("start", help="start a stopped Notebook")
    start.add_argument("--region", default=argparse.SUPPRESS)
    start.add_argument("notebook_id")
    start.add_argument("--no-wait", action="store_true")
    start.add_argument("--timeout", type=int, default=600)
    start.add_argument("--yes", action="store_true")

    stop = commands.add_parser("stop", help="stop a running Notebook")
    stop.add_argument("--region", default=argparse.SUPPRESS)
    stop.add_argument("notebook_id")
    stop.add_argument("--save-environment", action="store_true")
    stop.add_argument("--no-wait", action="store_true")
    stop.add_argument("--timeout", type=int, default=300)
    stop.add_argument("--yes", action="store_true")

    release = commands.add_parser(
        "release", help="permanently release a Notebook"
    )
    release.add_argument("--region", default=argparse.SUPPRESS)
    release.add_argument("notebook_id")
    release.add_argument("--yes", action="store_true")

    rename = commands.add_parser("rename", help="rename a Notebook")
    rename.add_argument("--region", default=argparse.SUPPRESS)
    rename.add_argument("notebook_id")
    rename.add_argument("name")
    rename.add_argument("--yes", action="store_true")

    smoke = commands.add_parser(
        "smoke",
        help="create, validate, stop, and release a minimal Notebook",
    )
    smoke.add_argument("--region", default=argparse.SUPPRESS)
    smoke.add_argument("--resource-group", default="")
    smoke.add_argument("--image-id", default="")
    smoke.add_argument("--cards", type=int, default=1)
    smoke.add_argument("--timeout", type=int, default=600)
    smoke.add_argument("--yes", action="store_true")


def _default_region(
    args: argparse.Namespace, config: Mapping[str, Any]
) -> str:
    region = getattr(args, "region", None)
    if region:
        return str(region)
    openapi = config.get("openapi")
    if isinstance(openapi, dict):
        value = (
            openapi.get("default_notebook_region_id")
            or openapi.get("default_region_id")
            or openapi.get("region_id")
        )
        if value:
            return str(value)
    raise BackendError(
        "Notebook region is not configured; run `notebook regions` "
        "or pass --region"
    )


def _confirm(args: argparse.Namespace, message: str, expected: str = "") -> None:
    if getattr(args, "yes", False):
        return
    if not sys.stdin.isatty():
        raise BackendError("confirmation required; rerun with --yes")
    if expected:
        answer = input(f"{message}\n输入 {expected} 确认: ").strip()
        if answer != expected:
            raise BackendError("confirmation did not match")
        return
    answer = input(f"{message} [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise BackendError("operation cancelled")


def _plan_summary(plan: Mapping[str, Any]) -> str:
    summary = plan.get("summary") or {}
    return (
        f"区域={summary.get('region')}, "
        f"资源={summary.get('resource')}, "
        f"卡数={summary.get('cards')}, "
        f"CPU={summary.get('cpu')}, RAM={summary.get('ram')}, "
        f"镜像={summary.get('image')}, "
        f"挂载Home={summary.get('mount_home')}"
    )


def execute_notebook(
    args: argparse.Namespace,
    context: BackendContext,
    config: Mapping[str, Any],
) -> Any:
    service = NotebookService(SCNetClient(context))
    operation = args.notebook_operation
    if operation == "regions":
        return service.regions()
    region = _default_region(args, config)
    if operation == "resources":
        return service.resources(region, args.resource_id)
    if operation == "images":
        return service.images(
            region,
            access=args.access,
            image_type=args.image_type,
            accelerator_type=args.accelerator_type,
            name=args.name,
            start=args.start,
            limit=args.limit,
        )
    if operation == "list":
        return service.list_instances(
            region,
            name=args.name,
            status=args.status,
            page=args.page,
            size=args.size,
        )
    if operation == "show":
        return service.detail(region, args.notebook_id)
    if operation == "url":
        return service.url(
            region, args.notebook_id, reveal=args.reveal
        )
    if operation == "create":
        plan = service.create_plan(
            region,
            resource_group=args.resource_group,
            image_id=args.image_id,
            accelerator_number=args.cards,
            mount_home=not args.no_mount_home,
            start_command=args.start_command,
        )
        if args.dry_run:
            return {"dry_run": True, "plan": plan["summary"]}
        _confirm(
            args,
            "将创建可能计费的 Notebook：\n" + _plan_summary(plan),
        )
        created = service.create(region, plan)
        notebook_id = str(created.get("notebookId") or "")
        if not notebook_id or args.no_wait:
            return {"created": created, "plan": plan["summary"]}
        detail = service.wait_status(
            region,
            notebook_id,
            {"Running", "Failed"},
            timeout=args.timeout,
        )
        return {
            "created": created,
            "detail": detail,
            "plan": plan["summary"],
        }
    if operation == "start":
        if args.dry_run:
            return {
                "dry_run": True,
                "operation": "start",
                "notebook_id": args.notebook_id,
            }
        _confirm(
            args,
            f"启动 Notebook {args.notebook_id} 可能恢复计费。",
        )
        result = service.start(region, args.notebook_id)
        if args.no_wait:
            return {"requested": result}
        return {
            "requested": result,
            "detail": service.wait_status(
                region,
                args.notebook_id,
                {"Running", "Failed"},
                timeout=args.timeout,
            ),
        }
    if operation == "stop":
        if args.dry_run:
            return {
                "dry_run": True,
                "operation": "stop",
                "notebook_id": args.notebook_id,
                "save_environment": args.save_environment,
            }
        _confirm(args, f"停止 Notebook {args.notebook_id}。")
        result = service.stop(
            region,
            args.notebook_id,
            save_environment=args.save_environment,
        )
        if args.no_wait:
            return {"requested": result}
        return {
            "requested": result,
            "detail": service.wait_status(
                region,
                args.notebook_id,
                {"Terminated", "Failed"},
                timeout=args.timeout,
            ),
        }
    if operation == "release":
        if args.dry_run:
            return {
                "dry_run": True,
                "operation": "release",
                "notebook_id": args.notebook_id,
                "destructive": True,
            }
        _confirm(
            args,
            f"释放 Notebook {args.notebook_id} 不可恢复。",
            expected=args.notebook_id,
        )
        return {
            "released": service.release(region, args.notebook_id),
            "notebook_id": args.notebook_id,
        }
    if operation == "rename":
        if args.dry_run:
            return {
                "dry_run": True,
                "operation": "rename",
                "notebook_id": args.notebook_id,
                "name": args.name,
            }
        _confirm(
            args,
            f"将 Notebook {args.notebook_id} 重命名为 {args.name!r}。",
        )
        return {
            "renamed": service.rename(
                region, args.notebook_id, args.name
            )
        }
    if operation == "smoke":
        plan = service.create_plan(
            region,
            resource_group=args.resource_group,
            image_id=args.image_id,
            accelerator_number=args.cards,
            mount_home=True,
        )
        if args.dry_run:
            return {
                "dry_run": True,
                "operation": "smoke",
                "plan": plan["summary"],
                "cleanup": "stop and release",
            }
        _confirm(
            args,
            "将创建一个可能计费的临时 Notebook，"
            "验证后自动停止并释放：\n"
            + _plan_summary(plan),
        )
        record: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "plan": plan["summary"],
            "events": [],
        }
        notebook_id = ""
        error: Exception | None = None
        try:
            created = service.create(region, plan)
            notebook_id = str(created.get("notebookId") or "")
            record["created"] = created
            if not notebook_id:
                raise BackendError("create returned no notebookId")
            detail = service.wait_status(
                region,
                notebook_id,
                {"Running", "Failed"},
                timeout=args.timeout,
            )
            record["running_detail"] = detail
            if detail.get("notebookStatus") != "Running":
                raise BackendError("Notebook did not reach Running")
            url = service.url(region, notebook_id)
            record["url"] = url
            if url.get("status") != "active":
                raise BackendError("Jupyter URL is not active")
            record["validated"] = True
        except Exception as exc:
            error = exc
            record["error"] = str(exc)
        finally:
            if notebook_id:
                try:
                    record["stop"] = service.stop(region, notebook_id)
                    record["stopped_detail"] = service.wait_status(
                        region,
                        notebook_id,
                        {"Terminated", "Failed"},
                        timeout=min(args.timeout, 300),
                    )
                except Exception as exc:
                    record["stop_error"] = str(exc)
                try:
                    record["release"] = service.release(
                        region, notebook_id
                    )
                except Exception as exc:
                    record["release_error"] = str(exc)
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["ok"] = (
            bool(record.get("validated"))
            and "release_error" not in record
        )
        if error or not record["ok"]:
            raise BackendError(
                "Notebook smoke failed after cleanup: "
                + str(error or record.get("release_error"))
            )
        return record
    raise BackendError(f"unsupported Notebook operation: {operation}")
