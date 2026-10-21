"""Inspect private mail settings; send one explicitly authorized, owned check."""
from __future__ import annotations

import argparse
import hashlib
import imaplib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses, parsedate_to_datetime
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / ".local-keys" / "notification-delivery.private.env"
SECURITY_SOURCE = ROOT / "apps" / "api" / "app" / "security.py"
RUN_PATTERN = re.compile(r"[a-f0-9]{32}")
ATTEMPT_SCOPE = "Owned SMTP transport check through candidate helper; no alert-outbox or production configuration claim"
BINDING_FIELDS = ("schema", "run_id", "message_id", "recipient_sha256", "source_sha256",
                  "message_date", "reserved_at_utc", "retry_forbidden", "scope")
ALLOWED_KEYS = frozenset({
    "SMTP_HOST", "SMTP_PORT", "SMTP_USE_TLS", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM",
    "DELIVERY_TEST_RECIPIENT", "DELIVERY_IMAP_HOST", "DELIVERY_IMAP_PORT",
    "DELIVERY_IMAP_USERNAME", "DELIVERY_IMAP_PASSWORD",
})


class ProbeError(Exception):
    """An input or receipt gate failed; private values stay out of the error."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def source_hash() -> str:
    return digest(SECURITY_SOURCE.read_bytes())


def write_exclusive(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def validate_attempt(attempt: dict, expected_run: str | None = None) -> None:
    if not isinstance(attempt, dict):
        raise ProbeError("attempt_receipt_invalid")
    run_id = attempt.get("run_id")
    if (not isinstance(run_id, str) or not RUN_PATTERN.fullmatch(run_id)
            or (expected_run is not None and run_id != expected_run)
            or type(attempt.get("schema")) is not int or attempt["schema"] != 1
            or attempt.get("message_id") != "<nerkhbaan-delivery-" + run_id + "@nerkhbaan.invalid>"
            or attempt.get("retry_forbidden") is not True or attempt.get("scope") != ATTEMPT_SCOPE):
        raise ProbeError("attempt_receipt_invalid")
    for key in ("recipient_sha256", "source_sha256"):
        if not isinstance(attempt.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", attempt[key]):
            raise ProbeError("attempt_receipt_invalid")
    try:
        for key in ("reserved_at_utc", "message_date"):
            if not isinstance(attempt.get(key), str) or len(attempt[key]) > 100 or not no_controls(attempt[key]):
                raise ValueError()
        reserved = datetime.fromisoformat(attempt["reserved_at_utc"])
        dated = parsedate_to_datetime(attempt["message_date"])
        if any(value.utcoffset() is None or value.utcoffset().total_seconds() != 0 for value in (reserved, dated)):
            raise ValueError()
        if abs((reserved - dated).total_seconds()) > 60:
            raise ValueError()
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        raise ProbeError("attempt_receipt_invalid") from error


def validate_smtp_receipt(attempt: dict, smtp: dict, expected_run: str) -> None:
    validate_attempt(attempt, expected_run)
    if (not isinstance(smtp, dict) or smtp.get("smtp_accepted") is not True
            or smtp.get("smtp_outcome") != "accepted"
            or any(type(smtp.get(key)) is not type(attempt[key]) or smtp[key] != attempt[key] for key in BINDING_FIELDS)):
        raise ProbeError("smtp_attempt_binding_invalid")
    try:
        finished = datetime.fromisoformat(smtp["finished_at_utc"])
        if finished.utcoffset() is None or finished.utcoffset().total_seconds() != 0:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError) as error:
        raise ProbeError("smtp_attempt_binding_invalid") from error


def read_receipt(path: Path) -> dict:
    if path.stat().st_size > 65_536:
        raise ProbeError("receipt_oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def load_private_settings(path: Path) -> dict[str, str]:
    from dotenv import dotenv_values

    if not path.is_file() or path.stat().st_size > 65_536:
        raise ProbeError("private_input_missing_or_oversized")
    text = path.read_text(encoding="utf-8-sig")
    names = re.findall(r"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", text)
    known = [name for name in names if name in ALLOWED_KEYS]
    if len(known) != len(set(known)):
        raise ProbeError("private_input_duplicate_key")
    parsed = dotenv_values(stream=__import__("io").StringIO(text), interpolate=False)
    return {key: str(value or "") for key, value in parsed.items() if key in ALLOWED_KEYS}


def no_controls(value: str) -> bool:
    return not any(ord(char) < 32 or ord(char) == 127 for char in value)


def address(value: str, *, display_name: bool = False) -> str:
    if not value or len(value) > 320 or not no_controls(value):
        raise ProbeError("mail_address_invalid")
    try:
        pairs = getaddresses([value]) if display_name else [("", value)]
        if len(pairs) != 1 or not pairs[0][1]:
            raise ValueError()
        parsed = Address(addr_spec=pairs[0][1])
        if not parsed.username or not parsed.domain or "." not in parsed.domain:
            raise ValueError()
        if not display_name and parsed.addr_spec != value:
            raise ValueError()
        return parsed.addr_spec
    except (ValueError, IndexError) as error:
        raise ProbeError("mail_address_invalid") from error


def port(value: str, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError as error:
        raise ProbeError("port_invalid") from error
    if not 1 <= parsed <= 65_535:
        raise ProbeError("port_invalid")
    return parsed


def smtp_configuration(values: dict[str, str]) -> dict:
    host = values.get("SMTP_HOST", "").strip()
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise ProbeError("smtp_host_missing_or_invalid")
    recipient = address(values.get("DELIVERY_TEST_RECIPIENT", "").strip())
    sender = values.get("SMTP_FROM", "").strip()
    address(sender, display_name=True)
    selected_port = port(values.get("SMTP_PORT", ""), 587)
    raw_tls = values.get("SMTP_USE_TLS", "true").strip().lower()
    if raw_tls not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ProbeError("smtp_tls_flag_invalid")
    use_tls = raw_tls in {"true", "1", "yes", "on"}
    if selected_port != 465 and not use_tls:
        raise ProbeError("plaintext_smtp_refused")
    username, password = values.get("SMTP_USERNAME", ""), values.get("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise ProbeError("smtp_authentication_incomplete")
    return {"smtp_host": host, "smtp_port": selected_port, "smtp_use_tls": use_tls,
            "smtp_username": username or None, "smtp_password": password or None,
            "smtp_from": sender, "recipient": recipient}


def imap_configuration(values: dict[str, str]) -> dict | None:
    required = ("DELIVERY_IMAP_HOST", "DELIVERY_IMAP_USERNAME", "DELIVERY_IMAP_PASSWORD")
    if not all(values.get(key) for key in required):
        return None
    host = values[required[0]].strip()
    if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise ProbeError("imap_host_invalid")
    return {"host": host, "port": port(values.get("DELIVERY_IMAP_PORT", ""), 993),
            "username": values[required[1]], "password": values[required[2]]}


def inspect_configuration(values: dict[str, str]) -> dict:
    result = {"mode": "inspect", "checked_at_utc": utc_now(), "network_attempted": False,
              "source_sha256": source_hash(), "present": {key: bool(values.get(key)) for key in sorted(ALLOWED_KEYS)},
              "smtp_accepted": False, "mailbox_received": False, "full_delivery_passed": False}
    recipient = values.get("DELIVERY_TEST_RECIPIENT", "").strip()
    if recipient:
        result["recipient_sha256"] = digest(recipient)
    try:
        smtp_configuration(values)
        result["smtp_inputs_ready"] = True
    except ProbeError as error:
        result.update(smtp_inputs_ready=False, smtp_gate=str(error))
    try:
        result["imap_inputs_ready"] = imap_configuration(values) is not None
    except ProbeError as error:
        result.update(imap_inputs_ready=False, imap_gate=str(error))
    return result


def make_message(config: dict, attempt: dict) -> EmailMessage:
    message = EmailMessage()
    message["From"], message["To"] = config["smtp_from"], config["recipient"]
    message["Subject"] = "Nerkhbaan delivery check " + attempt["run_id"][:12]
    message["Message-ID"], message["Date"] = attempt["message_id"], attempt["message_date"]
    message["X-Nerkhbaan-Delivery-Run"] = attempt["run_id"]
    message.set_content("Owned delivery check.\nRun: " + attempt["run_id"] + "\nNo reply is needed.\n")
    return message


def smtp_child(request: dict) -> dict:
    logging.disable(logging.CRITICAL)
    validate_attempt(request["attempt"])
    expected = request["attempt"]["source_sha256"]
    if source_hash() != expected:
        raise ProbeError("candidate_source_changed")
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from app.security import send_smtp_message

    if source_hash() != expected:
        raise ProbeError("candidate_source_changed")
    config = dict(request["smtp"])
    message = make_message(config, request["attempt"])
    config.pop("recipient")
    send_smtp_message(message, timeout=10, smtp_settings=SimpleNamespace(**config))
    return {"smtp_accepted": True, "source_sha256": expected}


def imap_child(request: dict) -> dict:
    config, attempt = request["imap"], request["attempt"]
    validate_attempt(attempt)
    deadline = time.monotonic() + request["deadline_seconds"]
    client = imaplib.IMAP4_SSL(config["host"], config["port"],
                             ssl_context=ssl.create_default_context(), timeout=8)
    try:
        client.login(config["username"], config["password"])
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise ProbeError("readonly_inbox_unavailable")
        while time.monotonic() < deadline:
            status, data = client.uid("search", None, "HEADER", "Message-ID", '"' + attempt["message_id"] + '"',
                                      "HEADER", "X-Nerkhbaan-Delivery-Run", '"' + attempt["run_id"] + '"')
            if status != "OK" or len(data) != 1 or not isinstance(data[0], bytes):
                raise ProbeError("owned_message_search_failed")
            uids = data[0].split()
            if len(uids) > 1 or any(not re.fullmatch(rb"[0-9]+", uid) for uid in uids):
                raise ProbeError("owned_message_search_ambiguous")
            if uids:
                status, rows = client.uid("fetch", uids[0],
                    "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE X-NERKHBAAN-DELIVERY-RUN)])")
                chunks = [row[1] for row in rows if isinstance(row, tuple) and isinstance(row[1], bytes)]
                if status != "OK" or len(chunks) != 1 or len(chunks[0]) > 8192:
                    raise ProbeError("owned_message_headers_invalid")
                headers = BytesParser(policy=policy.default).parsebytes(chunks[0])
                for key, expected in (("Message-ID", attempt["message_id"]),
                                      ("X-Nerkhbaan-Delivery-Run", attempt["run_id"])):
                    if headers.get_all(key) != [expected]:
                        raise ProbeError("owned_message_headers_mismatch")
                return {"mailbox_received": True, "received_at_utc": utc_now(),
                        "owned_header_sha256": digest(chunks[0]), "readonly_inbox": True,
                        "minimal_headers_only": True, "message_marked_read": False}
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        return {"mailbox_received": False, "mailbox_status": "pending", "readonly_inbox": True}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run_child(operation: str, request: dict, timeout: int) -> dict:
    code = ("import json,sys; sys.path.insert(0,sys.argv[1]); import notification_delivery_probe as p; "
            "p.child_entry(sys.argv[2])")
    child_env = {key: value for key, value in os.environ.items()
                 if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "SYSTEMDRIVE"}}
    child_env.update(JWT_SECRET_KEY=secrets.token_urlsafe(48), PYTHONDONTWRITEBYTECODE="1")
    try:
        with tempfile.TemporaryDirectory(prefix="nerkhbaan-mail-child-") as work:
            reply = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(Path(__file__).parent), operation],
                input=json.dumps(request), text=True, capture_output=True, timeout=timeout,
                cwd=work, env=child_env)
        if reply.returncode != 0:
            return {"operation_failed": True, "error_type": "ChildProcessError"}
        result = json.loads(reply.stdout)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except subprocess.TimeoutExpired:
        return {"operation_failed": True, "error_type": "TimeoutExpired", "outcome_unknown": operation == "smtp"}
    except (ValueError, OSError):
        return {"operation_failed": True, "error_type": "ChildProtocolError"}


def child_entry(operation: str) -> None:
    try:
        request = json.load(sys.stdin)
        result = smtp_child(request) if operation == "smtp" else imap_child(request)
    except Exception as error:
        result = {"operation_failed": True, "error_type": type(error).__name__}
    print(json.dumps(result))


def check_mailbox(values: dict[str, str], attempt: dict, destination: Path, deadline: int) -> dict:
    validate_attempt(attempt)
    try:
        config = imap_configuration(values)
        result = (run_child("imap", {"imap": config, "attempt": attempt, "deadline_seconds": deadline}, deadline + 12)
                  if config else {"mailbox_received": False, "mailbox_status": "pending_configuration"})
    except ProbeError:
        result = {"mailbox_received": False, "mailbox_status": "invalid_configuration"}
    result = {**result, **{key: attempt[key] for key in BINDING_FIELDS}, "checked_at_utc": utc_now()}
    result["mailbox_received"] = result.get("mailbox_received") is True
    write_exclusive(destination / (attempt["run_id"] + ".mailbox." + secrets.token_hex(8) + ".json"), result)
    return result


def send_owned(values: dict[str, str], *, run_id: str, destination: Path, confirmed: bool,
               expected_recipient_sha256: str, mailbox_deadline: int = 30) -> dict:
    if not confirmed or not RUN_PATTERN.fullmatch(run_id or ""):
        raise ProbeError("explicit_owned_recipient_and_run_required")
    if type(mailbox_deadline) is not int or not 1 <= mailbox_deadline <= 60:
        raise ProbeError("mailbox_deadline_invalid")
    config = smtp_configuration(values)
    if not re.fullmatch(r"[a-f0-9]{64}", expected_recipient_sha256 or "") or not secrets.compare_digest(
            digest(config["recipient"]), expected_recipient_sha256):
        raise ProbeError("confirmed_recipient_hash_required")
    attempt = {"schema": 1, "run_id": run_id, "reserved_at_utc": utc_now(),
               "recipient_sha256": expected_recipient_sha256, "source_sha256": source_hash(),
               "message_id": "<nerkhbaan-delivery-" + run_id + "@nerkhbaan.invalid>",
               "message_date": format_datetime(datetime.now(UTC)), "retry_forbidden": True,
               "scope": ATTEMPT_SCOPE}
    try:
        write_exclusive(destination / (run_id + ".attempt.json"), attempt)
    except FileExistsError as error:
        raise ProbeError("attempt_already_reserved_never_resend") from error
    try:
        outcome = run_child("smtp", {"smtp": config, "attempt": attempt}, 45)
        accepted = outcome.get("smtp_accepted") is True and outcome.get("source_sha256") == attempt["source_sha256"]
        result = {**attempt, "finished_at_utc": utc_now(), "smtp_accepted": accepted,
                  "mailbox_received": False, "full_delivery_passed": False,
                  "smtp_outcome": "accepted" if accepted else "failed_or_unknown"}
        if outcome.get("error_type"):
            result["error_type"] = outcome["error_type"]
    except Exception as error:
        result = {**attempt, "finished_at_utc": utc_now(), "smtp_accepted": False,
                  "mailbox_received": False, "full_delivery_passed": False,
                  "smtp_outcome": "unknown", "error_type": type(error).__name__}
    write_exclusive(destination / (run_id + ".smtp.json"), result)
    if result["smtp_accepted"]:
        try:
            mailbox = check_mailbox(values, attempt, destination, mailbox_deadline)
        except Exception as error:
            mailbox = {"mailbox_received": False, "error_type": type(error).__name__}
        result["mailbox_received"] = mailbox.get("mailbox_received") is True
        result["full_delivery_passed"] = result["mailbox_received"]
        result["mailbox"] = mailbox
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("inspect", "send", "mailbox"), default="inspect")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--receipt-dir", type=Path, default=ROOT / ".local-keys" / "notification-delivery-receipts")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--confirm-owned-recipient", action="store_true")
    parser.add_argument("--expected-recipient-sha256", default="")
    parser.add_argument("--mailbox-deadline", type=int, choices=range(1, 61), default=30, metavar="1..60")
    args = parser.parse_args(argv)
    try:
        values = load_private_settings(args.env_file)
        if args.mode == "inspect":
            result = inspect_configuration(values)
        elif args.mode == "send":
            result = send_owned(values, run_id=args.run_id, destination=args.receipt_dir,
                confirmed=args.confirm_owned_recipient, expected_recipient_sha256=args.expected_recipient_sha256,
                mailbox_deadline=args.mailbox_deadline)
        else:
            if not RUN_PATTERN.fullmatch(args.run_id):
                raise ProbeError("run_required")
            attempt = read_receipt(args.receipt_dir / (args.run_id + ".attempt.json"))
            smtp = read_receipt(args.receipt_dir / (args.run_id + ".smtp.json"))
            validate_smtp_receipt(attempt, smtp, args.run_id)
            recipient = smtp_configuration(values)["recipient"]
            if digest(recipient) != attempt.get("recipient_sha256"):
                raise ProbeError("owned_recipient_changed")
            result = {"smtp_accepted": True, **check_mailbox(values, attempt, args.receipt_dir, args.mailbox_deadline)}
            result["full_delivery_passed"] = result.get("mailbox_received") is True
        print(json.dumps(result, sort_keys=True))
        return 0 if args.mode == "inspect" or result.get("full_delivery_passed") is True else 2
    except Exception as error:
        output = {"mode": args.mode, "full_delivery_passed": False, "error_type": type(error).__name__}
        if isinstance(error, ProbeError):
            output["gate"] = str(error)
        print(json.dumps(output))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
