"""Word versions of the two client ROI reports, built from the same content as the PDFs.

Usage (from the repo root): python -m evals.roi.client_docx
Reads phases.json (like client_report.py), turns each report's HTML into a block list, renders every chart to a
PNG with Chromium, and calls client_docx.js (the `docx` npm package) to write
  evals/roi/UseCase1_ROI.docx and evals/roi/UseCase2_ROI.docx
"""
import json, os, re, subprocess, tempfile
from html.parser import HTMLParser
from pathlib import Path

from playwright.sync_api import sync_playwright

from evals.roi.client_report import OUT, load, phase1, usecase1

VOID = {"br", "img", "meta", "circle", "line", "rect", "polyline", "path"}


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def classes(self) -> set:
        return set(self.attrs.get("class", "").split())


class Tree(HTMLParser):
    """Minimal DOM: enough to walk the report's own markup. SVGs are kept as raw source for rendering."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source, self.root = source, Node("root", [])
        self.cur, self.svg_depth, self.svgs = self.root, 0, []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if self.svg_depth or tag == "svg":
            if tag == "svg":
                if not self.svg_depth:
                    node = Node("svg", attrs, self.cur); node.index = len(self.svgs); self.svgs.append(node)
                    self.cur.children.append(node)
                self.svg_depth += 1
            return
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        if self.svg_depth:
            if tag == "svg":
                self.svg_depth -= 1
            return
        if tag not in VOID and self.cur.parent is not None:
            self.cur = self.cur.parent

    def handle_data(self, data):
        if not self.svg_depth:
            self.cur.children.append(data)


def svgs_of(source: str) -> list[str]:
    out, start = [], 0
    while (i := source.find("<svg", start)) != -1:
        j = source.find("</svg>", i) + len("</svg>")
        out.append(source[i:j]); start = j
    return out


def runs(node: Node) -> list[dict]:
    """Inline text with bold spans, whitespace collapsed the way a browser would."""
    raw = []

    def walk(n, bold):
        for c in n.children:
            if isinstance(c, str):
                raw.append((c, bold))
            else:
                walk(c, bold or c.tag in ("b", "strong"))
    walk(node, False)
    out = []
    for text, bold in raw:
        text = re.sub(r"\s+", " ", text)
        if out and out[-1]["text"].endswith(" ") and text.startswith(" "):
            text = text[1:]
        if not out and text.startswith(" "):
            text = text[1:]
        if text:
            out.append({"text": text, "bold": bold})
    if out:
        out[-1]["text"] = out[-1]["text"].rstrip()
    return [r for r in out if r["text"]]


def blocks_of(source: str, images: list[str]) -> list[dict]:
    tree = Tree(source)
    blocks = []

    def table(node):
        rows = []
        for tr in [n for n in walk_all(node) if n.tag == "tr"]:
            cells = [c for c in tr.children if not isinstance(c, str) and c.tag in ("th", "td")]
            rows.append({"total": "total" in tr.classes(),
                         "cells": [{"text": " ".join(c.text().split()), "header": c.tag == "th",
                                    "num": "num" in c.classes(), "hl": "hl" in c.classes()} for c in cells]})
        return {"type": "table", "rows": rows}

    def visit(node):
        for c in node.children:
            if isinstance(c, str):
                continue
            cls = c.classes()
            if c.tag == "h1":
                blocks.append({"type": "h1", "text": " ".join(c.text().split())})
            elif c.tag == "h2":
                blocks.append({"type": "h2", "text": " ".join(c.text().split())})
            elif c.tag == "p":
                blocks.append({"type": "dek" if "dek" in cls else "hook" if "hook" in cls else "p", "note": "note" in cls, "runs": runs(c)})
            elif c.tag == "ul":
                blocks.append({"type": "bullets", "note": "note" in cls,
                               "items": [runs(li) for li in c.children if not isinstance(li, str) and li.tag == "li"]})
            elif c.tag == "table":
                blocks.append(table(c))
            elif c.tag == "div" and "figures" in cls:
                items = []
                for d in [x for x in c.children if not isinstance(x, str) and x.tag == "div"]:
                    b = next(x for x in d.children if not isinstance(x, str) and x.tag == "b")
                    s = next(x for x in d.children if not isinstance(x, str) and x.tag == "span")
                    items.append({"value": " ".join(b.text().split()), "label": " ".join(s.text().split())})
                blocks.append({"type": "keyfigs", "items": items})
            elif c.tag == "figure":
                head = next((x for x in c.children if not isinstance(x, str) and "fighead" in x.classes()), None)
                svg = next(x for x in walk_all(c) if x.tag == "svg")
                cap = next((x for x in c.children if not isinstance(x, str) and x.tag == "figcaption"), None)
                blocks.append({"type": "figure", "head": " ".join(head.text().split()) if head else "",
                               "image": images[svg.index], "width": float(svg.attrs.get("width", 620)),
                               "height": float(svg.attrs.get("height", 200)), "caption": runs(cap) if cap else []})
            else:
                visit(c)  # div.keep and other wrappers
    visit(tree.root)
    return blocks


def walk_all(node):
    for c in node.children:
        if not isinstance(c, str):
            yield c
            yield from walk_all(c)


def render_svgs(svgs: list[str], folder: Path, prefix: str, browser) -> list[str]:
    page = browser.new_page(device_scale_factor=3)
    paths = []
    for i, svg in enumerate(svgs):
        page.set_content(f'<html><body style="margin:0;background:#fff">{svg}</body></html>')
        path = folder / f"{prefix}-fig{i + 1}.png"
        page.locator("svg").first.screenshot(path=str(path))
        paths.append(str(path))
    page.close()
    return paths


def main() -> None:
    d = load()
    reports = [("Use Case 1 – Wire Instruction Extraction", usecase1(d), OUT / "UseCase1_ROI.docx"),
               ("Use Case 2 – Treasury Loan Diligence Automation", phase1(d), OUT / "UseCase2_ROI.docx")]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        bundled = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")  # pre-installed in cloud sessions
        browser = pw.chromium.launch(executable_path=str(bundled) if bundled.exists() else None)
        for n, (title, body, target) in enumerate(reports):
            images = render_svgs(svgs_of(body), Path(tmp), f"r{n}", browser)
            spec = {"title": title, "out": str(target), "blocks": blocks_of(body, images)}
            spec_path = Path(tmp) / f"r{n}.json"
            spec_path.write_text(json.dumps(spec))
            env = {**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", "") + ":" +
                   subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()}
            subprocess.run(["node", str(Path(__file__).with_name("client_docx.js")), str(spec_path)], check=True, env=env)
            print("wrote", target)


if __name__ == "__main__":
    main()
