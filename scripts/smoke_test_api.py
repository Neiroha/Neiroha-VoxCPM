from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test a running Neiroha VoxCPM API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--synthesize", action="store_true", help="Run a real default synthesis request.")
    parser.add_argument("--output", type=Path, default=Path("runtime/outputs/smoke_test.wav"))
    return parser.parse_args()


def request_json(base_url: str, method: str, path: str, payload: dict[str, object] | None = None, *, api_key: str = ""):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def request_audio(base_url: str, payload: dict[str, object], *, api_key: str = "") -> tuple[bytes, dict[str, str]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def assert_error_code(base_url: str, *, api_key: str) -> None:
    try:
        request_audio(
            base_url,
            {"model": "default", "input": "smoke", "voice": "voxcpm2-design", "response_format": "mp3"},
            api_key=api_key,
        )
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        code = payload.get("error", {}).get("code")
        if exc.code == 400 and code == "unsupported_format":
            return
        raise RuntimeError(f"Unexpected unsupported-format response: HTTP {exc.code} {payload}") from exc
    raise RuntimeError("Unsupported response_format unexpectedly succeeded.")


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    health = request_json(base_url, "GET", "/health", api_key=args.api_key)
    models = request_json(base_url, "GET", "/v1/models", api_key=args.api_key)
    voices = request_json(base_url, "GET", "/v1/audio/voices", api_key=args.api_key)
    native = request_json(base_url, "GET", "/api/voxcpm/capabilities", api_key=args.api_key)
    assert_error_code(base_url, api_key=args.api_key)

    print(f"health.status={health.get('status')}")
    print(f"models={len(models.get('data', []))}")
    print(f"voices={len(voices.get('data', []))}")
    print(f"native.engine={native.get('engine')}")
    print("unsupported_format=ok")

    if args.synthesize:
        audio, headers = request_audio(
            base_url,
            {"model": "default", "input": "Neiroha VoxCPM smoke test.", "voice": "voxcpm2-design"},
            api_key=args.api_key,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(audio)
        print(f"synthesis.output={args.output}")
        print(f"synthesis.backend={headers.get('x-neiroha-backend', '')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
