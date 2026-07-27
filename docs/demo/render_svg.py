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

"""Turn the demo transcript into a terminal-styled SVG for the README.

Reads the ANSI output of ``run_demo.py`` on stdin and writes an SVG. Static by
design: no scripts, no animation, so it renders identically wherever GitHub
serves it.

    uv run python docs/demo/run_demo.py | uv run python docs/demo/render_svg.py \\
        > docs/demo.svg
"""

from __future__ import annotations

import re
import sys
from xml.sax.saxutils import escape

ANSI = re.compile(r"\033\[([0-9;]*)m")

# One palette, tuned to stay readable on a light or a dark page.
FG = "#c9d1d9"
BG = "#0d1117"
CHROME = "#161b22"
BORDER = "#30363d"
COLORS = {
    "31": "#ff7b72",
    "32": "#3fb950",
    "33": "#d29922",
    "34": "#58a6ff",
    "36": "#39c5cf",
}
DIM = "#8b949e"

CHAR_W = 8.4
LINE_H = 21
PAD_X = 22
PAD_TOP = 52
PAD_BOTTOM = 20


def parse(line: str) -> list[tuple[str, str, bool, bool]]:
    """Split one ANSI line into (text, color, bold, dim) runs."""
    runs: list[tuple[str, str, bool, bool]] = []
    color, bold, dim = FG, False, False
    pos = 0
    for match in ANSI.finditer(line):
        if match.start() > pos:
            runs.append((line[pos : match.start()], color, bold, dim))
        for code in (match.group(1) or "0").split(";"):
            if code in ("", "0"):
                color, bold, dim = FG, False, False
            elif code == "1":
                bold = True
            elif code == "2":
                dim = True
            elif code in COLORS:
                color = COLORS[code]
        pos = match.end()
    if pos < len(line):
        runs.append((line[pos:], color, bold, dim))
    return runs


def render(lines: list[str], title: str) -> str:
    width = max((len(ANSI.sub("", ln)) for ln in lines), default=80)
    w = int(PAD_X * 2 + width * CHAR_W)
    h = int(PAD_TOP + len(lines) * LINE_H + PAD_BOTTOM)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="ui-monospace, SFMono-Regular, '
        f'\'SF Mono\', Menlo, Consolas, monospace" font-size="13.5">',
        f'<rect width="{w}" height="{h}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
        f'<path d="M0 10a10 10 0 0 1 10-10h{w - 20}a10 10 0 0 1 10 10v22H0z" fill="{CHROME}"/>',
        f'<line x1="0" y1="32" x2="{w}" y2="32" stroke="{BORDER}"/>',
        '<circle cx="20" cy="16" r="5.5" fill="#ff5f57"/>',
        '<circle cx="38" cy="16" r="5.5" fill="#febc2e"/>',
        '<circle cx="56" cy="16" r="5.5" fill="#28c840"/>',
        f'<text x="{w / 2}" y="21" fill="{DIM}" font-size="12" '
        f'text-anchor="middle">{escape(title)}</text>',
    ]

    for row, line in enumerate(lines):
        y = PAD_TOP + row * LINE_H
        col = 0
        for text, color, bold, dim in parse(line):
            if text.strip():
                x = PAD_X + col * CHAR_W
                fill = DIM if dim else color
                weight = ' font-weight="600"' if bold else ""
                # textLength pins the advance width so the columns stay aligned
                # even where the viewer substitutes a different monospace font.
                out.append(
                    f'<text x="{x:.1f}" y="{y}" fill="{fill}"{weight} '
                    f'textLength="{len(text) * CHAR_W:.1f}" '
                    f'lengthAdjust="spacingAndGlyphs" '
                    f'xml:space="preserve">{escape(text)}</text>'
                )
            col += len(text)

    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    raw = sys.stdin.read().rstrip("\n").split("\n")
    title = sys.argv[1] if len(sys.argv) > 1 else "skywalking-zabbix-mcp — demo (synthetic data)"
    sys.stdout.write(render(raw, title) + "\n")
