#!/usr/bin/env python3
"""Push the plain-english/*.md docs into Notion as subpages of a parent page.

Usage:
    # parent page must have the `adil_claude` integration connected (•••  > Connections)
    python3 notion/push_to_notion.py <PARENT_PAGE_ID_or_URL>

Reads NOTION_TOKEN / NOTION_VERSION from notion/.env.
Converts a pragmatic subset of Markdown -> Notion blocks: headings, bullet &
numbered lists, blockquotes, code fences, tables, and paragraphs with inline
**bold** / `code` / *italic*.
"""
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS_DIR = os.path.join(ROOT, "plain-english")

# Order matters: README (index) first, then the read, then the rails, then football.
DOC_ORDER = [
    "README.md",
    "colony-in-plain-english.md",
    "worldcoin-in-plain-english.md",
    "clickhouse-in-plain-english.md",
    "football-in-plain-english.md",
]


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV["NOTION_TOKEN"]
VERSION = ENV.get("NOTION_VERSION", "2022-06-28")


def api(method, path, body=None):
    url = "https://api.notion.com/v1" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Notion-Version", VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.stderr.write("HTTP %s on %s %s\n%s\n" % (e.code, method, path, e.read().decode()))
        raise


# ---------- inline markdown -> rich_text ----------
TOKEN_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*]+\*)")


def rich_text(s):
    out = []
    for part in TOKEN_RE.split(s):
        if not part:
            continue
        ann = {}
        text = part
        if part.startswith("**") and part.endswith("**"):
            ann = {"bold": True}
            text = part[2:-2]
        elif part.startswith("`") and part.endswith("`"):
            ann = {"code": True}
            text = part[1:-1]
        elif part.startswith("*") and part.endswith("*"):
            ann = {"italic": True}
            text = part[1:-1]
        # Notion hard limit 2000 chars per rich_text item
        out.append({"type": "text", "text": {"content": text[:2000]},
                    "annotations": ann} if ann else
                   {"type": "text", "text": {"content": text[:2000]}})
    return out or [{"type": "text", "text": {"content": ""}}]


def para(s):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(s)}}


def heading(level, s):
    key = "heading_%d" % min(level, 3)
    return {"object": "block", "type": key, key: {"rich_text": rich_text(s)}}


def bullet(s):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rich_text(s)}}


def numbered(s):
    return {"object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": rich_text(s)}}


def quote(s):
    return {"object": "block", "type": "quote", "quote": {"rich_text": rich_text(s)}}


def code_block(s, lang="plain text"):
    return {"object": "block", "type": "code",
            "code": {"rich_text": [{"type": "text", "text": {"content": s[:2000]}}],
                     "language": lang}}


def table_block(rows, has_header=True):
    width = max(len(r) for r in rows)
    children = []
    for r in rows:
        cells = [rich_text(c) for c in r] + [[{"type": "text", "text": {"content": ""}}]] * (width - len(r))
        children.append({"object": "block", "type": "table_row",
                         "table_row": {"cells": cells}})
    return {"object": "block", "type": "table",
            "table": {"table_width": width, "has_column_header": has_header,
                      "has_row_header": False, "children": children}}


def split_table_row(line):
    line = line.strip().strip("|")
    return [c.strip() for c in line.split("|")]


def is_table_divider(line):
    return bool(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", line)) and "-" in line


def md_to_blocks(md):
    lines = md.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # code fence
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip() or "plain text"
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            blocks.append(code_block("\n".join(buf), lang if lang in (
                "bash", "python", "json", "javascript", "typescript", "sql",
                "markdown", "yaml", "shell", "plain text") else "plain text"))
            i += 1
            continue
        # table: a line with | followed by a divider line
        if "|" in line and i + 1 < len(lines) and is_table_divider(lines[i + 1]):
            rows = [split_table_row(line)]
            i += 2  # skip header + divider
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(split_table_row(lines[i]))
                i += 1
            blocks.append(table_block(rows, has_header=True))
            continue
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            blocks.append(heading(len(m.group(1)), m.group(2)))
        elif stripped.startswith(">"):
            blocks.append(quote(stripped.lstrip(">").strip()))
        elif re.match(r"^[-*]\s+", stripped):
            blocks.append(bullet(re.sub(r"^[-*]\s+", "", stripped)))
        elif re.match(r"^\d+\.\s+", stripped):
            blocks.append(numbered(re.sub(r"^\d+\.\s+", "", stripped)))
        elif set(stripped) <= set("-=") and len(stripped) >= 3:
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append(para(stripped))
        i += 1
    return blocks


def page_title(md, fallback):
    for line in md.split("\n"):
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return m.group(1)
    return fallback


def normalize_id(s):
    # accept a raw id or a full notion URL
    s = s.strip()
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    if m:
        h = m.group(1)
        return "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])
    return s


def append_in_chunks(page_id, blocks):
    for j in range(0, len(blocks), 90):
        api("PATCH", "/blocks/%s/children" % page_id, {"children": blocks[j:j + 90]})


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: push_to_notion.py <PARENT_PAGE_ID_or_URL> [DOCS_DIR]")
    parent = normalize_id(sys.argv[1])
    # Optional second arg: a docs directory. When given, push every *.md in it
    # (sorted) instead of the default plain-english/ DOC_ORDER set.
    if len(sys.argv) >= 3:
        docs_dir = os.path.abspath(sys.argv[2])
        order = sorted(f for f in os.listdir(docs_dir) if f.endswith(".md"))
    else:
        docs_dir = DOCS_DIR
        order = DOC_ORDER
    for fname in order:
        path = os.path.join(docs_dir, fname)
        if not os.path.exists(path):
            print("skip (missing):", fname)
            continue
        with open(path) as f:
            md = f.read()
        title = page_title(md, fname)
        blocks = md_to_blocks(md)
        page = api("POST", "/pages", {
            "parent": {"page_id": parent},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
            "children": blocks[:90],
        })
        if len(blocks) > 90:
            append_in_chunks(page["id"], blocks[90:])
        print("created:", title, "->", page.get("url", page["id"]))


if __name__ == "__main__":
    main()
