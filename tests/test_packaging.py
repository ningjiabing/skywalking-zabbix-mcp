# Copyright 2026 ningjiabing
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Guards on repository metadata that is easy to update in one place and forget
in another: the version is declared in ``__init__.py`` but repeated in
``server.json`` and ``CHANGELOG.md``, and no published file may carry a real
address or hostname.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import skywalking_zabbix_mcp

ROOT = Path(__file__).resolve().parents[1]
VERSION = skywalking_zabbix_mcp.__version__


def test_server_json_versions_match_the_package():
    manifest = json.loads((ROOT / "server.json").read_text())

    assert manifest["version"] == VERSION
    for package in manifest["packages"]:
        assert package["version"] == VERSION, package["identifier"]


def test_changelog_documents_the_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text()

    assert f"## [{VERSION}]" in changelog, f"CHANGELOG.md has no section for {VERSION}"


def test_py_typed_marker_ships_with_the_package():
    assert (ROOT / "src" / "skywalking_zabbix_mcp" / "py.typed").exists()


# Published files must not name a real host. Documentation addresses are the
# RFC 5737 ranges plus loopback; everything else is a leak.
_ALLOWED_IPS = {"127.0.0.1", "0.0.0.0", "::1"}
_DOC_RANGES = ("192.0.2.", "198.51.100.", "203.0.113.")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_PUBLISHED = [
    p
    for pattern in ("*.md", "*.py", "*.toml", "*.json", "*.yml", "*.yaml", "*.svg")
    for p in ROOT.rglob(pattern)
    if not any(
        part in {".venv", ".git", "dist", "build", "__pycache__", ".mypy_cache", ".ruff_cache"}
        for part in p.parts
    )
    and p.name != "uv.lock"
]


@pytest.mark.parametrize("path", _PUBLISHED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_real_ip_addresses_in_published_files(path: Path):
    found = {
        ip
        for ip in _IP.findall(path.read_text(errors="ignore"))
        if ip not in _ALLOWED_IPS and not ip.startswith(_DOC_RANGES)
    }
    # Version-like strings ("9.7.0") never match; four octets are required.
    assert not found, f"{path.relative_to(ROOT)} contains non-documentation IPs: {sorted(found)}"
