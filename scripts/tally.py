#!/usr/bin/env python3
"""Tally API CLI (agent-first JSON envelope)."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pathlib
import random
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.tally.so"
API_VERSION = "2025-05-30"
MAX_RETRIES = 4
MAX_ALL_PAGES = 200
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

FORM_STATUSES = ("BLANK", "DRAFT", "PUBLISHED", "DELETED")
SUBMISSION_FILTERS = ("all", "completed", "partial")
FIELD_TYPE_TO_BLOCK = {
    "text": "INPUT_TEXT",
    "email": "INPUT_EMAIL",
    "number": "INPUT_NUMBER",
    "phone": "INPUT_PHONE_NUMBER",
    "date": "INPUT_DATE",
    "time": "INPUT_TIME",
    "url": "INPUT_LINK",
    "textarea": "TEXTAREA",
    "file": "FILE_UPLOAD",
    "rating": "RATING",
}

_TOKEN_CACHE: Optional[Tuple[str, str]] = None


class CliError(Exception):
    def __init__(
        self,
        message: str,
        *,
        http_status: Optional[int] = None,
        fix: Optional[str] = None,
        retryable: bool = False,
        next_actions: Optional[List[Dict[str, str]]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.fix = fix
        self.retryable = retryable
        self.next_actions = next_actions or []
        self.request_id = request_id


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_command(argv: List[str]) -> str:
    if not argv:
        return "tally"
    return "tally " + " ".join(shlex.quote(part) for part in argv)


def emit(payload: Dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def ok(command: str, result: Dict[str, Any], next_actions: Optional[List[Dict[str, str]]] = None) -> None:
    payload: Dict[str, Any] = {
        "ok": True,
        "command": command,
        "timestamp": utc_now_iso(),
        "result": result,
        "next_actions": next_actions or [],
    }
    emit(payload, 0)


def err(
    command: str,
    message: str,
    *,
    http_status: Optional[int] = None,
    fix: Optional[str] = None,
    retryable: bool = False,
    next_actions: Optional[List[Dict[str, str]]] = None,
    request_id: Optional[str] = None,
    exit_code: int = 1,
) -> None:
    error_obj: Dict[str, Any] = {"message": message}
    if http_status is not None:
        error_obj["http_status"] = http_status
    if request_id:
        error_obj["request_id"] = request_id

    payload: Dict[str, Any] = {
        "ok": False,
        "command": command,
        "timestamp": utc_now_iso(),
        "error": error_obj,
        "retryable": retryable,
        "next_actions": next_actions or [],
    }
    if fix:
        payload["fix"] = fix

    emit(payload, exit_code)


def _next_action(command: str, description: str) -> Dict[str, str]:
    return {"command": command, "description": description}


def _redact(key: str) -> str:
    if not key or len(key) < 8:
        return "[redacted]"
    return f"{key[:4]}...{key[-2:]}"


def _token_from_env() -> Optional[str]:
    candidate = os.environ.get("TALLY_API_KEY", "").strip()
    return candidate or None


def _token_from_op() -> Optional[str]:
    try:
        result = subprocess.run(
            ["op", "read", "op://Development/Tally API/credential"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    candidate = result.stdout.strip()
    return candidate or None


def _resolve_token() -> Optional[Tuple[str, str]]:
    token = _token_from_env()
    if token:
        return token, "env"

    token = _token_from_op()
    if token:
        return token, "1password"

    return None


def _auth_status() -> Dict[str, Any]:
    found = _resolve_token()
    if not found:
        return {
            "configured": False,
            "source": "none",
            "api_key_preview": None,
            "hint": "Set TALLY_API_KEY or store in 1Password at op://Development/Tally API/credential",
        }
    token, source = found
    return {
        "configured": True,
        "source": source,
        "api_key_preview": _redact(token),
    }


def _get_token() -> Tuple[str, str]:
    global _TOKEN_CACHE

    if _TOKEN_CACHE is not None:
        return _TOKEN_CACHE

    found = _resolve_token()
    if not found:
        raise CliError(
            "Missing TALLY_API_KEY",
            fix=(
                "Set it with: export TALLY_API_KEY='tly-xxxx' "
                "or store in 1Password at op://Development/Tally API/credential"
            ),
            next_actions=[
                _next_action("tally", "Inspect auth status and available commands"),
                _next_action("tally health", "Verify auth and API connectivity after setting credentials"),
            ],
        )

    _TOKEN_CACHE = found
    return found


def _extract_request_id(headers: Any) -> Optional[str]:
    for key in ("x-request-id", "request-id", "x-correlation-id", "x-amzn-requestid"):
        value = headers.get(key)
        if value:
            return str(value)
    return None


def _parse_error_message(status: int, body_text: str) -> str:
    if body_text:
        try:
            parsed = json.loads(body_text)
            if isinstance(parsed, dict):
                for key in ("message", "error", "detail"):
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        except json.JSONDecodeError:
            pass

    if status == 401:
        return "Unauthorized: invalid or missing API token"
    if status == 403:
        return "Forbidden: token lacks permission for this resource"
    if status == 404:
        return "Resource not found"
    if status == 429:
        return "Rate limited by Tally API"
    return f"Tally API request failed with HTTP {status}"


def _request_with_retry(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    max_retries: int = MAX_RETRIES,
) -> Tuple[Dict[str, Any], Optional[str]]:
    token, _ = _get_token()

    query_params: Dict[str, Any] = {}
    if params:
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            query_params[key] = value

    url = f"{API_BASE}{path}"
    if query_params:
        url += "?" + urlencode(query_params, doseq=True)

    data = json.dumps(body).encode("utf-8") if body is not None else None

    attempt = 0
    while True:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "tally-version": API_VERSION,
            "User-Agent": "tally-skill/1.0",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        req = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as resp:
                request_id = _extract_request_id(resp.headers)
                if resp.status == 204:
                    return {}, request_id

                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}, request_id

                try:
                    return json.loads(raw), request_id
                except json.JSONDecodeError:
                    return {"raw": raw}, request_id

        except HTTPError as exc:
            request_id = _extract_request_id(exc.headers)
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8")[:5000]
            except Exception:
                body_text = ""

            if exc.code in TRANSIENT_HTTP and attempt < max_retries:
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_for = max(float(retry_after), 1.0)
                else:
                    sleep_for = min(60.0, 1.0 * (2 ** attempt)) + random.uniform(0.0, 1.0)
                time.sleep(sleep_for)
                attempt += 1
                continue

            raise CliError(
                _parse_error_message(exc.code, body_text),
                http_status=exc.code,
                fix="Check command arguments and verify access to the targeted form/workspace.",
                retryable=exc.code in TRANSIENT_HTTP,
                request_id=request_id,
            ) from exc

        except URLError as exc:
            if attempt < max_retries:
                sleep_for = min(60.0, 1.0 * (2 ** attempt)) + random.uniform(0.0, 1.0)
                time.sleep(sleep_for)
                attempt += 1
                continue

            raise CliError(
                f"Network error calling Tally API: {exc}",
                http_status=0,
                fix="Check network connectivity and try again.",
                retryable=True,
            ) from exc


def _safe_read_path(raw: str, flag: str) -> pathlib.Path:
    p = pathlib.Path(raw).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise CliError(f"{flag}: file not found or not a regular file: {p}")
    return p


def _safe_write_path(raw: str, flag: str) -> pathlib.Path:
    p = pathlib.Path(raw).expanduser().resolve()
    if not p.parent.exists():
        raise CliError(f"{flag}: directory does not exist: {p.parent}")
    return p


def _sanitize_csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in FORMULA_PREFIXES:
        return "'" + text
    return text


def _redact_signing_secret(obj: Any) -> Any:
    if isinstance(obj, dict):
        clean: Dict[str, Any] = {}
        for key, value in obj.items():
            if key == "signingSecret" and value is not None:
                clean[key] = "[redacted]"
            else:
                clean[key] = _redact_signing_secret(value)
        return clean
    if isinstance(obj, list):
        return [_redact_signing_secret(item) for item in obj]
    return obj


def _parse_simple_fields(raw: str) -> List[Tuple[str, str]]:
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    if not entries:
        raise CliError(
            "--fields is required and cannot be empty",
            fix="Example: --fields \"Full Name=text,Email=email,Comments=textarea\"",
        )

    parsed: List[Tuple[str, str]] = []
    for entry in entries:
        if "=" not in entry:
            raise CliError(
                f"Invalid field entry '{entry}'",
                fix="Each field must be label=type. Example: Email=email",
            )

        label, field_type = entry.split("=", 1)
        label = label.strip()
        field_type = field_type.strip().lower()

        if not label:
            raise CliError(
                f"Invalid field entry '{entry}'",
                fix="Field labels cannot be empty.",
            )

        if field_type not in FIELD_TYPE_TO_BLOCK:
            raise CliError(
                f"Unsupported field type '{field_type}'",
                fix="Allowed types: " + ", ".join(sorted(FIELD_TYPE_TO_BLOCK.keys())),
            )

        parsed.append((label, field_type))

    return parsed


def _safe_html_schema(text: str) -> List[Any]:
    return [[text]]


def _simple_question_blocks(label: str, field_type: str) -> List[Dict[str, Any]]:
    block_type = FIELD_TYPE_TO_BLOCK[field_type]
    question_group_uuid = str(uuid.uuid4())

    title_block = {
        "uuid": str(uuid.uuid4()),
        "type": "TITLE",
        "groupUuid": question_group_uuid,
        "groupType": "QUESTION",
        "payload": {"safeHTMLSchema": _safe_html_schema(label)},
    }

    input_payload: Dict[str, Any] = {}
    if block_type == "RATING":
        input_payload = {"stars": 5}

    input_block = {
        "uuid": str(uuid.uuid4()),
        "type": block_type,
        "groupUuid": str(uuid.uuid4()),
        "groupType": block_type,
        "payload": input_payload,
    }

    return [title_block, input_block]


def _build_simple_form_blocks(name: str, fields: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    title_group_uuid = str(uuid.uuid4())
    blocks: List[Dict[str, Any]] = [
        {
            "uuid": str(uuid.uuid4()),
            "type": "FORM_TITLE",
            "groupUuid": title_group_uuid,
            "groupType": "TEXT",
            "payload": {
                "title": name,
                "safeHTMLSchema": _safe_html_schema(name),
            },
        }
    ]

    for label, field_type in fields:
        blocks.extend(_simple_question_blocks(label, field_type))

    return blocks


def _load_blocks_file(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    file_path = _safe_read_path(path, "--blocks-file")
    try:
        parsed = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"--blocks-file is not valid JSON: {exc}") from exc

    if isinstance(parsed, list):
        return parsed, {}

    if isinstance(parsed, dict):
        blocks = parsed.get("blocks")
        if not isinstance(blocks, list):
            raise CliError(
                "--blocks-file object must contain a 'blocks' array",
                fix="Use either a raw array of blocks, or an object with {\"blocks\": [...]}.",
            )
        meta = {k: v for k, v in parsed.items() if k != "blocks"}
        return blocks, meta

    raise CliError(
        "--blocks-file JSON must be an array or object",
        fix="Use [ ...blocks ] or {\"blocks\": [...], ...optional fields }",
    )


def _paginate_by_page(
    *,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
    items_key: str,
) -> Dict[str, Any]:
    base_params = dict(params or {})
    start_page = int(base_params.get("page") or 1)

    pages_fetched = 0
    merged: List[Any] = []
    first: Optional[Dict[str, Any]] = None
    page = start_page
    has_more = True

    while has_more:
        page_params = dict(base_params)
        page_params["page"] = page
        data, _ = _request_with_retry(method, path, params=page_params)

        pages_fetched += 1
        if first is None:
            first = data

        chunk = data.get(items_key, [])
        if not isinstance(chunk, list):
            raise CliError(f"Unexpected API response: '{items_key}' is not a list")

        merged.extend(chunk)
        has_more = bool(data.get("hasMore"))
        if not has_more:
            break

        if pages_fetched >= MAX_ALL_PAGES:
            raise CliError(
                f"Reached pagination safety cap ({MAX_ALL_PAGES} pages)",
                fix="Narrow your query with filters or increase --limit.",
            )

        page += 1

    if first is None:
        first = {}

    result = dict(first)
    result[items_key] = merged
    result["pagesFetched"] = pages_fetched
    result["allPages"] = True
    return result


def _list_submissions(args: argparse.Namespace) -> Dict[str, Any]:
    path = f"/forms/{args.form_id}/submissions"

    params: Dict[str, Any] = {}
    if args.filter:
        params["filter"] = args.filter
    if args.start_date:
        params["startDate"] = args.start_date
    if args.end_date:
        params["endDate"] = args.end_date
    if args.limit is not None:
        params["limit"] = args.limit

    if not args.all:
        if args.page is not None:
            params["page"] = args.page
        if args.after_id:
            params["afterId"] = args.after_id
        data, _ = _request_with_retry("GET", path, params=params)
        data["pagesFetched"] = 1
        data["allPages"] = False
        return data

    if args.after_id:
        pages_fetched = 0
        merged_submissions: List[Dict[str, Any]] = []
        merged_questions: List[Dict[str, Any]] = []
        cursor = args.after_id
        final_has_more = False
        first_page_meta: Optional[Dict[str, Any]] = None

        while True:
            page_params = dict(params)
            page_params["afterId"] = cursor
            data, _ = _request_with_retry("GET", path, params=page_params)

            pages_fetched += 1
            if first_page_meta is None:
                first_page_meta = data

            if not merged_questions:
                merged_questions = data.get("questions", []) or []

            chunk = data.get("submissions", []) or []
            merged_submissions.extend(chunk)

            final_has_more = bool(data.get("hasMore"))
            if not final_has_more or not chunk:
                break

            if pages_fetched >= MAX_ALL_PAGES:
                raise CliError(
                    f"Reached pagination safety cap ({MAX_ALL_PAGES} pages)",
                    fix="Narrow filters or export in smaller windows.",
                )

            last_id = chunk[-1].get("id")
            if not last_id:
                break
            cursor = last_id

        merged = dict(first_page_meta or {})
        merged["questions"] = merged_questions
        merged["submissions"] = merged_submissions
        merged["hasMore"] = final_has_more
        merged["pagesFetched"] = pages_fetched
        merged["allPages"] = True
        return merged

    params["page"] = args.page if args.page is not None else 1
    return _paginate_by_page(method="GET", path=path, params=params, items_key="submissions")


def _headers_from_questions(questions: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, str]]:
    used: Dict[str, int] = {}
    headers: List[str] = []
    by_question_id: Dict[str, str] = {}

    for question in questions:
        qid = str(question.get("id", "")).strip()
        raw_title = str(question.get("title") or qid or "untitled").strip() or "untitled"
        n = used.get(raw_title, 0) + 1
        used[raw_title] = n
        header = raw_title if n == 1 else f"{raw_title}_{n}"
        headers.append(header)
        if qid:
            by_question_id[qid] = header

    return headers, by_question_id


def _flatten_submission_rows(
    submissions: List[Dict[str, Any]],
    headers: List[str],
    question_to_header: Dict[str, str],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for submission in submissions:
        row: Dict[str, str] = {header: "" for header in headers}
        for response in submission.get("responses", []) or []:
            question_id = str(response.get("questionId", "")).strip()
            if not question_id:
                continue

            header = question_to_header.get(question_id)
            if not header:
                continue

            row[header] = str(response.get("formattedAnswer") or "")

        rows.append(row)

    return rows


def _rows_to_csv(headers: List[str], rows: List[Dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([_sanitize_csv_cell(h) for h in headers])
    for row in rows:
        writer.writerow([_sanitize_csv_cell(row.get(h, "")) for h in headers])
    return out.getvalue()


def _get_signing_secret(signing_secret_env: Optional[str]) -> Optional[str]:
    if not signing_secret_env:
        return None

    secret = os.environ.get(signing_secret_env)
    if not secret:
        raise CliError(
            f"Env var {signing_secret_env} not set",
            fix=f"Set it with: export {signing_secret_env}='your_secret'",
        )

    return secret


def cmd_index(_args: argparse.Namespace, command: str) -> None:
    auth = _auth_status()
    result = {
        "api": {
            "base": API_BASE,
            "version_header": API_VERSION,
        },
        "auth": auth,
        "command_groups": {
            "auth": ["tally", "tally health", "tally me"],
            "forms": [
                "tally form list",
                "tally form get --id <formId>",
                "tally form create --blocks-file <path>",
                "tally form create-simple --name \"Contact\" --fields \"name=text,email=email\"",
                "tally form update --id <formId>",
                "tally form delete --id <formId>",
                "tally form questions --id <formId>",
            ],
            "submissions": [
                "tally submission list --form-id <formId>",
                "tally submission get --form-id <formId> --id <submissionId>",
                "tally submission delete --form-id <formId> --id <submissionId>",
                "tally submission export --form-id <formId> --format csv",
            ],
            "webhooks": [
                "tally webhook create --form-id <formId> --url <url>",
                "tally webhook list",
                "tally webhook delete --id <webhookId>",
                "tally webhook events --id <webhookId>",
                "tally webhook retry --id <webhookId> --event-id <eventId>",
            ],
            "workspaces": [
                "tally workspace list",
                "tally workspace get --id <workspaceId>",
            ],
        },
    }

    ok(
        command,
        result,
        next_actions=[
            _next_action("tally health", "Verify credentials and API connectivity"),
            _next_action("tally form list", "List available forms"),
        ],
    )


def cmd_health(_args: argparse.Namespace, command: str) -> None:
    token, source = _get_token()
    user, request_id = _request_with_retry("GET", "/users/me")

    result = {
        "status": "ok",
        "api": {
            "base": API_BASE,
            "version_header": API_VERSION,
            "request_id": request_id,
        },
        "auth": {
            "configured": True,
            "source": source,
            "api_key_preview": _redact(token),
        },
        "user": user,
    }

    ok(
        command,
        result,
        next_actions=[
            _next_action("tally workspace list", "List workspaces"),
            _next_action("tally form list", "List forms"),
        ],
    )


def cmd_me(_args: argparse.Namespace, command: str) -> None:
    user, _ = _request_with_retry("GET", "/users/me")
    ok(
        command,
        {"user": user},
        next_actions=[
            _next_action("tally workspace list", "List your workspaces"),
            _next_action("tally form list", "List forms you can access"),
        ],
    )


def cmd_form_list(args: argparse.Namespace, command: str) -> None:
    params: Dict[str, Any] = {}
    if args.limit is not None:
        params["limit"] = args.limit
    if args.page is not None:
        params["page"] = args.page
    if args.workspace_id:
        params["workspaceIds"] = [args.workspace_id]

    if args.all:
        data = _paginate_by_page(method="GET", path="/forms", params=params, items_key="items")
    else:
        data, _ = _request_with_retry("GET", "/forms", params=params)
        data["pagesFetched"] = 1
        data["allPages"] = False

    forms = data.get("items", [])
    has_more = bool(data.get("hasMore"))

    next_actions: List[Dict[str, str]] = []
    if forms:
        first_id = forms[0].get("id")
        if first_id:
            next_actions.append(_next_action(f"tally form get --id {first_id}", "View first form details"))
    if has_more and not args.all:
        next_page = int(data.get("page") or (args.page or 1)) + 1
        pieces = [f"tally form list --page {next_page}"]
        if args.limit is not None:
            pieces.append(f"--limit {args.limit}")
        if args.workspace_id:
            pieces.append(f"--workspace-id {shlex.quote(args.workspace_id)}")
        next_actions.append(_next_action(" ".join(pieces), "View next page of forms"))

    result = {
        "forms": forms,
        "page": data.get("page"),
        "limit": data.get("limit"),
        "total": data.get("total"),
        "hasMore": has_more,
        "pagesFetched": data.get("pagesFetched", 1),
        "allPages": data.get("allPages", False),
    }

    ok(command, result, next_actions=next_actions)


def cmd_form_get(args: argparse.Namespace, command: str) -> None:
    form, _ = _request_with_retry("GET", f"/forms/{args.id}")
    ok(
        command,
        {"form": form},
        next_actions=[
            _next_action(
                f"tally submission export --form-id {args.id} --format csv --output ./submissions-{args.id}.csv",
                "Export submissions before deleting this form",
            ),
            _next_action(f"tally form questions --id {args.id}", "List questions for this form"),
            _next_action(f"tally submission list --form-id {args.id}", "List submissions for this form"),
        ],
    )


def cmd_form_create(args: argparse.Namespace, command: str) -> None:
    blocks, meta = _load_blocks_file(args.blocks_file)

    body: Dict[str, Any] = dict(meta)
    body["blocks"] = blocks

    if args.status:
        body["status"] = args.status
    elif "status" not in body:
        body["status"] = "DRAFT"

    if args.workspace_id:
        body["workspaceId"] = args.workspace_id

    created, _ = _request_with_retry("POST", "/forms", body=body)
    form_id = created.get("id", "<form-id>")

    ok(
        command,
        {"form": created, "blockCount": len(blocks)},
        next_actions=[
            _next_action(
                f"tally webhook create --form-id {form_id} --url https://example.com/webhook",
                "Attach a webhook to this form",
            ),
            _next_action(f"tally submission list --form-id {form_id}", "Monitor form submissions"),
        ],
    )


def cmd_form_create_simple(args: argparse.Namespace, command: str) -> None:
    parsed_fields = _parse_simple_fields(args.fields)
    form_name = args.name.strip() if args.name and args.name.strip() else "Untitled Form"
    blocks = _build_simple_form_blocks(form_name, parsed_fields)

    body: Dict[str, Any] = {
        "status": args.status,
        "blocks": blocks,
    }
    if args.workspace_id:
        body["workspaceId"] = args.workspace_id

    created, _ = _request_with_retry("POST", "/forms", body=body)
    form_id = created.get("id", "<form-id>")

    ok(
        command,
        {
            "form": created,
            "fieldCount": len(parsed_fields),
            "fieldTypes": [field_type for _, field_type in parsed_fields],
        },
        next_actions=[
            _next_action(
                f"tally webhook create --form-id {form_id} --url https://example.com/webhook",
                "Set up a webhook for new responses",
            ),
            _next_action(f"tally submission list --form-id {form_id}", "Check for incoming submissions"),
        ],
    )


def cmd_form_update(args: argparse.Namespace, command: str) -> None:
    body: Dict[str, Any] = {}

    if args.name:
        body["name"] = args.name
    if args.status:
        body["status"] = args.status
    if args.blocks_file:
        blocks, _ = _load_blocks_file(args.blocks_file)
        body["blocks"] = blocks

    if not body:
        raise CliError(
            "No update fields provided",
            fix="Use at least one of --name, --status, or --blocks-file.",
        )

    updated, _ = _request_with_retry("PATCH", f"/forms/{args.id}", body=body)
    ok(
        command,
        {"form": updated},
        next_actions=[
            _next_action(f"tally form get --id {args.id}", "Confirm the updated form details"),
            _next_action(f"tally form questions --id {args.id}", "Review form questions"),
        ],
    )


def cmd_form_delete(args: argparse.Namespace, command: str) -> None:
    _request_with_retry("DELETE", f"/forms/{args.id}")
    ok(
        command,
        {"deleted": True, "formId": args.id},
        next_actions=[
            _next_action("tally form list", "List remaining forms"),
        ],
    )


def cmd_form_questions(args: argparse.Namespace, command: str) -> None:
    data, _ = _request_with_retry("GET", f"/forms/{args.id}/questions")

    questions = data.get("questions", [])
    has_responses = bool(data.get("hasResponses"))

    ok(
        command,
        {
            "questions": questions,
            "hasResponses": has_responses,
        },
        next_actions=[
            _next_action(f"tally submission list --form-id {args.id}", "List submissions for this form"),
            _next_action(
                f"tally submission export --form-id {args.id} --format csv",
                "Export responses as CSV",
            ),
        ],
    )


def cmd_submission_list(args: argparse.Namespace, command: str) -> None:
    data = _list_submissions(args)

    submissions = data.get("submissions", [])
    has_more = bool(data.get("hasMore"))

    next_actions: List[Dict[str, str]] = [
        _next_action(
            f"tally submission export --form-id {args.form_id} --format csv",
            "Export submissions to CSV",
        )
    ]

    if submissions:
        first_id = submissions[0].get("id")
        if first_id:
            next_actions.append(
                _next_action(
                    f"tally submission get --form-id {args.form_id} --id {first_id}",
                    "Inspect first submission in detail",
                )
            )

    if has_more and submissions and not args.all:
        last_id = submissions[-1].get("id")
        if last_id:
            next_actions.append(
                _next_action(
                    f"tally submission list --form-id {args.form_id} --after-id {last_id}",
                    "Fetch the next page using cursor pagination",
                )
            )

    result = {
        "formId": args.form_id,
        "filter": args.filter,
        "questions": data.get("questions", []),
        "submissions": submissions,
        "page": data.get("page"),
        "limit": data.get("limit"),
        "hasMore": has_more,
        "totalNumberOfSubmissionsPerFilter": data.get("totalNumberOfSubmissionsPerFilter"),
        "pagesFetched": data.get("pagesFetched", 1),
        "allPages": data.get("allPages", False),
    }

    ok(command, result, next_actions=next_actions)


def cmd_submission_get(args: argparse.Namespace, command: str) -> None:
    data, _ = _request_with_retry("GET", f"/forms/{args.form_id}/submissions/{args.id}")
    ok(
        command,
        data,
        next_actions=[
            _next_action(
                f"tally submission export --form-id {args.form_id} --format json",
                "Export submissions as structured JSON",
            ),
            _next_action(
                f"tally submission delete --form-id {args.form_id} --id {args.id}",
                "Delete this submission",
            ),
        ],
    )


def cmd_submission_delete(args: argparse.Namespace, command: str) -> None:
    _request_with_retry("DELETE", f"/forms/{args.form_id}/submissions/{args.id}")
    ok(
        command,
        {"deleted": True, "formId": args.form_id, "submissionId": args.id},
        next_actions=[
            _next_action(
                f"tally submission list --form-id {args.form_id}",
                "List remaining submissions",
            )
        ],
    )


def cmd_submission_export(args: argparse.Namespace, command: str) -> None:
    data = _list_submissions(args)

    submissions = data.get("submissions", []) or []
    questions = data.get("questions", []) or []
    headers, by_question_id = _headers_from_questions(questions)
    rows = _flatten_submission_rows(submissions, headers, by_question_id)

    output_path: Optional[pathlib.Path] = None
    if args.output:
        output_path = _safe_write_path(args.output, "--output")

    if args.format == "csv":
        csv_text = _rows_to_csv(headers, rows)
        if output_path:
            output_path.write_text(csv_text, encoding="utf-8")

        result: Dict[str, Any] = {
            "format": "csv",
            "formId": args.form_id,
            "columns": [_sanitize_csv_cell(h) for h in headers],
            "rowCount": len(rows),
            "pagesFetched": data.get("pagesFetched", 1),
            "allPages": data.get("allPages", False),
        }
        if output_path:
            result["outputPath"] = str(output_path)
        else:
            result["content"] = csv_text

    else:
        payload = {
            "formId": args.form_id,
            "questions": questions,
            "submissions": submissions,
            "rows": rows,
        }

        if output_path:
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        result = {
            "format": "json",
            "formId": args.form_id,
            "submissionCount": len(submissions),
            "pagesFetched": data.get("pagesFetched", 1),
            "allPages": data.get("allPages", False),
        }
        if output_path:
            result["outputPath"] = str(output_path)
        else:
            result["content"] = payload

    ok(
        command,
        result,
        next_actions=[
            _next_action(
                f"tally submission list --form-id {args.form_id}",
                "Review submissions in API format",
            ),
            _next_action(
                f"tally form questions --id {args.form_id}",
                "Inspect question metadata and IDs",
            ),
        ],
    )


def cmd_webhook_create(args: argparse.Namespace, command: str) -> None:
    secret = _get_signing_secret(args.signing_secret_env)

    body: Dict[str, Any] = {
        "formId": args.form_id,
        "url": args.url,
        "eventTypes": ["FORM_RESPONSE"],
    }
    if secret is not None:
        body["signingSecret"] = secret

    created, _ = _request_with_retry("POST", "/webhooks", body=body)
    redacted = _redact_signing_secret(created)
    webhook_id = redacted.get("id", "<webhook-id>")

    ok(
        command,
        {"webhook": redacted},
        next_actions=[
            _next_action(f"tally webhook events --id {webhook_id}", "Inspect webhook delivery events"),
            _next_action("tally webhook list", "List all webhooks"),
        ],
    )


def cmd_webhook_list(args: argparse.Namespace, command: str) -> None:
    params: Dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page
    if args.limit is not None:
        params["limit"] = args.limit

    if args.all:
        data = _paginate_by_page(method="GET", path="/webhooks", params=params, items_key="webhooks")
    else:
        data, _ = _request_with_retry("GET", "/webhooks", params=params)
        data["pagesFetched"] = 1
        data["allPages"] = False

    webhooks = _redact_signing_secret(data.get("webhooks", []))

    next_actions: List[Dict[str, str]] = []
    if webhooks:
        first_id = webhooks[0].get("id")
        if first_id:
            next_actions.append(_next_action(f"tally webhook events --id {first_id}", "View first webhook events"))
    if bool(data.get("hasMore")) and not args.all:
        next_page = int(data.get("page") or (args.page or 1)) + 1
        next_actions.append(_next_action(f"tally webhook list --page {next_page}", "View next page of webhooks"))

    ok(
        command,
        {
            "webhooks": webhooks,
            "page": data.get("page"),
            "limit": data.get("limit"),
            "hasMore": data.get("hasMore"),
            "totalCount": data.get("totalCount"),
            "pagesFetched": data.get("pagesFetched", 1),
            "allPages": data.get("allPages", False),
        },
        next_actions=next_actions,
    )


def cmd_webhook_delete(args: argparse.Namespace, command: str) -> None:
    _request_with_retry("DELETE", f"/webhooks/{args.id}")
    ok(
        command,
        {"deleted": True, "webhookId": args.id},
        next_actions=[
            _next_action("tally webhook list", "List remaining webhooks"),
        ],
    )


def cmd_webhook_events(args: argparse.Namespace, command: str) -> None:
    params: Dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page

    if args.all:
        data = _paginate_by_page(
            method="GET",
            path=f"/webhooks/{args.id}/events",
            params=params,
            items_key="events",
        )
    else:
        data, _ = _request_with_retry("GET", f"/webhooks/{args.id}/events", params=params)
        data["pagesFetched"] = 1
        data["allPages"] = False

    events = data.get("events", [])
    next_actions: List[Dict[str, str]] = []
    if events:
        event_id = events[0].get("id")
        if event_id:
            next_actions.append(
                _next_action(
                    f"tally webhook retry --id {args.id} --event-id {event_id}",
                    "Retry first event",
                )
            )

    ok(
        command,
        {
            "webhookId": args.id,
            "events": events,
            "page": data.get("page"),
            "limit": data.get("limit"),
            "hasMore": data.get("hasMore"),
            "totalNumberOfEvents": data.get("totalNumberOfEvents"),
            "pagesFetched": data.get("pagesFetched", 1),
            "allPages": data.get("allPages", False),
        },
        next_actions=next_actions,
    )


def cmd_webhook_retry(args: argparse.Namespace, command: str) -> None:
    _request_with_retry("POST", f"/webhooks/{args.id}/events/{args.event_id}")
    ok(
        command,
        {
            "retried": True,
            "webhookId": args.id,
            "eventId": args.event_id,
        },
        next_actions=[
            _next_action(f"tally webhook events --id {args.id}", "Inspect updated delivery status"),
        ],
    )


def cmd_workspace_list(args: argparse.Namespace, command: str) -> None:
    params: Dict[str, Any] = {}
    if args.page is not None:
        params["page"] = args.page

    if args.all:
        data = _paginate_by_page(method="GET", path="/workspaces", params=params, items_key="items")
    else:
        data, _ = _request_with_retry("GET", "/workspaces", params=params)
        data["pagesFetched"] = 1
        data["allPages"] = False

    items = data.get("items", [])
    next_actions: List[Dict[str, str]] = []
    if items:
        first_id = items[0].get("id")
        if first_id:
            next_actions.append(_next_action(f"tally workspace get --id {first_id}", "Inspect first workspace"))

    if bool(data.get("hasMore")) and not args.all:
        next_page = int(data.get("page") or (args.page or 1)) + 1
        next_actions.append(_next_action(f"tally workspace list --page {next_page}", "View next page"))

    ok(
        command,
        {
            "workspaces": items,
            "page": data.get("page"),
            "limit": data.get("limit"),
            "total": data.get("total"),
            "hasMore": data.get("hasMore"),
            "pagesFetched": data.get("pagesFetched", 1),
            "allPages": data.get("allPages", False),
        },
        next_actions=next_actions,
    )


def cmd_workspace_get(args: argparse.Namespace, command: str) -> None:
    workspace, _ = _request_with_retry("GET", f"/workspaces/{args.id}")
    ok(
        command,
        {"workspace": workspace},
        next_actions=[
            _next_action("tally workspace list", "List all accessible workspaces"),
            _next_action(f"tally form list --workspace-id {args.id}", "List forms in this workspace"),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tally", description="Tally API CLI (agent-first JSON output)")
    subparsers = parser.add_subparsers(dest="group")

    health = subparsers.add_parser("health", help="Verify credentials and API reachability")
    health.set_defaults(func=cmd_health)

    me = subparsers.add_parser("me", help="Show current user")
    me.set_defaults(func=cmd_me)

    form = subparsers.add_parser("form", help="Form operations")
    form_sub = form.add_subparsers(dest="action")

    form_list = form_sub.add_parser("list", help="List forms")
    form_list.add_argument("--workspace-id")
    form_list.add_argument("--limit", type=int)
    form_list.add_argument("--page", type=int)
    form_list.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    form_list.set_defaults(func=cmd_form_list)

    form_get = form_sub.add_parser("get", help="Get a form")
    form_get.add_argument("--id", required=True)
    form_get.set_defaults(func=cmd_form_get)

    form_create = form_sub.add_parser("create", help="Create a form from blocks JSON")
    form_create.add_argument("--blocks-file", required=True)
    form_create.add_argument("--workspace-id")
    form_create.add_argument("--status", choices=FORM_STATUSES)
    form_create.set_defaults(func=cmd_form_create)

    form_create_simple = form_sub.add_parser("create-simple", help="Create form from label=type DSL")
    form_create_simple.add_argument("--name", required=True)
    form_create_simple.add_argument("--fields", required=True)
    form_create_simple.add_argument("--workspace-id")
    form_create_simple.add_argument("--status", choices=FORM_STATUSES, default="DRAFT")
    form_create_simple.set_defaults(func=cmd_form_create_simple)

    form_update = form_sub.add_parser("update", help="Update form")
    form_update.add_argument("--id", required=True)
    form_update.add_argument("--name")
    form_update.add_argument("--status", choices=FORM_STATUSES)
    form_update.add_argument("--blocks-file")
    form_update.set_defaults(func=cmd_form_update)

    form_delete = form_sub.add_parser("delete", help="Delete form")
    form_delete.add_argument("--id", required=True)
    form_delete.set_defaults(func=cmd_form_delete)

    form_questions = form_sub.add_parser("questions", help="List form questions")
    form_questions.add_argument("--id", required=True)
    form_questions.set_defaults(func=cmd_form_questions)

    submission = subparsers.add_parser("submission", help="Submission operations")
    submission_sub = submission.add_subparsers(dest="action")

    submission_list = submission_sub.add_parser("list", help="List submissions")
    submission_list.add_argument("--form-id", required=True)
    submission_list.add_argument("--filter", choices=SUBMISSION_FILTERS)
    submission_list.add_argument("--start-date")
    submission_list.add_argument("--end-date")
    submission_list.add_argument("--limit", type=int)
    submission_list.add_argument("--page", type=int)
    submission_list.add_argument("--after-id")
    submission_list.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    submission_list.set_defaults(func=cmd_submission_list)

    submission_get = submission_sub.add_parser("get", help="Get a single submission")
    submission_get.add_argument("--form-id", required=True)
    submission_get.add_argument("--id", required=True)
    submission_get.set_defaults(func=cmd_submission_get)

    submission_delete = submission_sub.add_parser("delete", help="Delete a submission")
    submission_delete.add_argument("--form-id", required=True)
    submission_delete.add_argument("--id", required=True)
    submission_delete.set_defaults(func=cmd_submission_delete)

    submission_export = submission_sub.add_parser("export", help="Export submissions to CSV or JSON")
    submission_export.add_argument("--form-id", required=True)
    submission_export.add_argument("--filter", choices=SUBMISSION_FILTERS)
    submission_export.add_argument("--start-date")
    submission_export.add_argument("--end-date")
    submission_export.add_argument("--limit", type=int)
    submission_export.add_argument("--page", type=int)
    submission_export.add_argument("--after-id")
    submission_export.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    submission_export.add_argument("--format", choices=("csv", "json"), default="csv")
    submission_export.add_argument("--output")
    submission_export.set_defaults(func=cmd_submission_export)

    webhook = subparsers.add_parser("webhook", help="Webhook operations")
    webhook_sub = webhook.add_subparsers(dest="action")

    webhook_create = webhook_sub.add_parser("create", help="Create webhook")
    webhook_create.add_argument("--form-id", required=True)
    webhook_create.add_argument("--url", required=True)
    webhook_create.add_argument("--signing-secret-env")
    webhook_create.set_defaults(func=cmd_webhook_create)

    webhook_list = webhook_sub.add_parser("list", help="List webhooks")
    webhook_list.add_argument("--page", type=int)
    webhook_list.add_argument("--limit", type=int)
    webhook_list.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    webhook_list.set_defaults(func=cmd_webhook_list)

    webhook_delete = webhook_sub.add_parser("delete", help="Delete webhook")
    webhook_delete.add_argument("--id", required=True)
    webhook_delete.set_defaults(func=cmd_webhook_delete)

    webhook_events = webhook_sub.add_parser("events", help="List webhook events")
    webhook_events.add_argument("--id", required=True)
    webhook_events.add_argument("--page", type=int)
    webhook_events.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    webhook_events.set_defaults(func=cmd_webhook_events)

    webhook_retry = webhook_sub.add_parser("retry", help="Retry webhook event")
    webhook_retry.add_argument("--id", required=True)
    webhook_retry.add_argument("--event-id", required=True)
    webhook_retry.set_defaults(func=cmd_webhook_retry)

    workspace = subparsers.add_parser("workspace", help="Workspace operations")
    workspace_sub = workspace.add_subparsers(dest="action")

    workspace_list = workspace_sub.add_parser("list", help="List workspaces")
    workspace_list.add_argument("--page", type=int)
    workspace_list.add_argument("--all", action="store_true", help=f"Auto-paginate up to {MAX_ALL_PAGES} pages")
    workspace_list.set_defaults(func=cmd_workspace_list)

    workspace_get = workspace_sub.add_parser("get", help="Get workspace")
    workspace_get.add_argument("--id", required=True)
    workspace_get.set_defaults(func=cmd_workspace_get)

    return parser


def main() -> None:
    argv = sys.argv[1:]
    command = make_command(argv)

    parser = build_parser()

    if not argv:
        cmd_index(argparse.Namespace(), command)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        err(
            command,
            "Invalid command or arguments",
            fix="Run `tally` for command index or `tally --help` for usage.",
            retryable=False,
            next_actions=[_next_action("tally", "Show command index")],
        )

    func = getattr(args, "func", None)
    if func is None:
        err(
            command,
            "Incomplete command",
            fix="Run `tally` to view command groups and examples.",
            next_actions=[_next_action("tally", "Show command index")],
        )

    try:
        func(args, command)
    except CliError as exc:
        err(
            command,
            exc.message,
            http_status=exc.http_status,
            fix=exc.fix,
            retryable=exc.retryable,
            next_actions=exc.next_actions,
            request_id=exc.request_id,
        )
    except KeyboardInterrupt:
        err(command, "Interrupted", retryable=True)
    except SystemExit:
        raise
    except Exception as exc:  # defensive fallback
        err(
            command,
            f"Unexpected error: {exc}",
            retryable=False,
            fix="Inspect the command arguments and try again.",
        )


if __name__ == "__main__":
    main()
