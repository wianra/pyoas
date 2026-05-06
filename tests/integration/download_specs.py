#!/usr/bin/env python3
"""Download real-world OpenAPI specs for integration tests.

Specs are written to tests/integration/specs/ which is gitignored.
Already-existing files are skipped (pass --force to re-download).

Usage::

    python tests/integration/download_specs.py
    python tests/integration/download_specs.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

SPECS_DIR = Path(__file__).parent / "specs"

SPECS: dict[str, str] = {
    "github.json": (
        "https://raw.githubusercontent.com/github/rest-api-description/main/"
        "descriptions/api.github.com/api.github.com.json"
    ),
    "stripe.yaml": (
        "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.yaml"
    ),
    "openai.yaml": (
        "https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml"
    ),
    "kubernetes.json": (
        "https://raw.githubusercontent.com/kubernetes/kubernetes/master/"
        "api/openapi-spec/swagger.json"
    ),
}


def download_all(*, force: bool = False) -> None:
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for filename, url in SPECS.items():
        dest = SPECS_DIR / filename
        if dest.exists() and not force:
            size_mb = dest.stat().st_size / 1_048_576
            print(f"  [skip]  {filename} ({size_mb:.1f} MB, already exists)")
            continue
        print(f"  [fetch] {filename}")
        print(f"          {url}")
        try:
            with httpx.Client(follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                dest.write_bytes(response.content)
        except Exception as exc:
            print(f"  [fail]  {filename}: {exc}", file=sys.stderr)
            ok = False
            continue
        size_mb = dest.stat().st_size / 1_048_576
        print(f"  [done]  {filename} ({size_mb:.1f} MB)")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the file already exists.",
    )
    args = parser.parse_args()
    download_all(force=args.force)
