from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import re
import tempfile

from telethon import TelegramClient
from telethon.sessions import StringSession


def read_environment(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        if path.stat().st_size > 65536:
            raise ValueError("Private environment exceeds its size limit")
        for line in path.read_text(encoding="utf8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"TELEGRAM_[A-Z_]+", name.strip()):
                raise ValueError("Unexpected private environment entry")
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def save_environment(path: Path, values: dict[str, str]) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
        raise ValueError("An existing private directory and absolute file path are required")
    if any('\n' in value or '\r' in value for value in values.values()):
        raise ValueError("Multiline environment values are not accepted")
    descriptor, temporary = tempfile.mkstemp(prefix=".telegram-env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf8') as stream:
            stream.write('# Private Telegram collector access. Never commit or share.\n')
            for name, value in values.items():
                stream.write(name+'='+value+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def main() -> None:
    arguments = argparse.ArgumentParser(description='Owner-operated private Telegram login; no session output.')
    arguments.add_argument('--env-file', type=Path, required=True)
    path = arguments.parse_args().env_file
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("An absolute private environment file is required")
    values = read_environment(path)
    api_id = int(values.get('TELEGRAM_API_ID', '0'))
    api_hash = values.get('TELEGRAM_API_HASH', '')
    if api_id <= 0 or not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash):
        raise ValueError("Fill API ID and hash in the private file first")

    async with TelegramClient(StringSession(values.get('TELEGRAM_SESSION_STRING', '')), api_id, api_hash) as client:
        account = await client.get_me()
        if account.bot:
            raise ValueError("A reading account is required")
        values['TELEGRAM_SESSION_STRING'] = client.session.save()
        save_environment(path, values)
    print('Private session saved. No session value was printed.')


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print('Private login failed: '+type(exc).__name__)
        raise SystemExit(1) from None
