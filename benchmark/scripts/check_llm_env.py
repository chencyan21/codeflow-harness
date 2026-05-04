from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _mask_secret(value: str) -> str:
    return "loaded" if value else "missing"


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _validate_env(env_file: Path) -> tuple[str, str, str]:
    values = dotenv_values(env_file)
    missing = [key for key in ("model_id", "api_key", "base_url") if not values.get(key)]
    if missing:
        raise RuntimeError(f"Missing required .env key(s): {', '.join(missing)}")

    model_id = str(values["model_id"]).strip()
    api_key = str(values["api_key"]).strip()
    base_url = str(values["base_url"]).strip()

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid base_url: {base_url}")

    return model_id, api_key, base_url


def _configure_proxy(proxy: str | None) -> None:
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["ALL_PROXY"] = proxy


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate .env and run a minimal LLM call.")
    parser.add_argument("--env-file", default=".env", help="Path to CodeFlow .env file")
    parser.add_argument("--proxy", help="Proxy URL, for example http://127.0.0.1:10087")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--message", default="Reply with exactly: ok", help="Test prompt")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if not env_file.exists():
        print(f"ERROR env file not found: {env_file}", file=sys.stderr)
        return 2

    try:
        model_id, api_key, base_url = _validate_env(env_file)
    except RuntimeError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    _configure_proxy(args.proxy)
    url = _chat_completions_url(base_url)
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": args.message}],
        "temperature": 0,
        "max_tokens": 8,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print(f"env_file={env_file}")
    print(f"model_id={model_id}")
    print(f"api_key={_mask_secret(api_key)} len={len(api_key)}")
    print(f"base_url={base_url}")
    print(f"endpoint={url}")
    print(f"proxy={args.proxy or '(disabled)'}")

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR http_status={exc.code}", file=sys.stderr)
        print(text[:1000], file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR request_failed={exc}", file=sys.stderr)
        return 1

    elapsed = time.perf_counter() - start
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    print(f"ok response={content!r} elapsed={elapsed:.2f}s usage={usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
