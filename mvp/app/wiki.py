"""LLM wiki 编排: 按 企业/年份 隔离沉淀。

prepare() 是 async generator, yield (stage, message, meta) 三元组, 供后端 SSE 流式推送进度。
内部用 asyncio.to_thread 包同步的 fetcher/parser。
命中缓存(full.md 已存在)直接返回, 不重复下载解析。
"""
import asyncio
import json
import os
import time
from pathlib import Path

from . import fetcher, parser

WIKI_ROOT = Path(__file__).resolve().parent.parent / "wiki"


def _company_dir(code: str, year) -> Path:
    return WIKI_ROOT / code.strip().upper() / str(year)


def _meta_path(code, year) -> Path:
    return _company_dir(code, year) / "meta.json"


def exists(code, year) -> bool:
    return (_company_dir(code, year) / "full.md").exists()


async def prepare(code, year):
    """编排: 下载 PDF → markitdown 转 MD → 切章节 → 写 meta。yield (stage, msg, meta)。"""
    code = code.strip().upper()
    cdir = _company_dir(code, year)

    if (cdir / "full.md").exists():
        meta = _read_meta(code, year) or {}
        yield ("cache", f"命中缓存: {code} {year} 年报 wiki 已沉淀", meta)
        return

    cdir.mkdir(parents=True, exist_ok=True)

    # Step 1: 流式下载(带百分比进度)
    yield ("step", "下载 PDF", {"step": "download", "status": "active"})
    fetch_meta = None
    async for ev in fetcher.fetch_pdf_stream(code, year, str(cdir)):
        if ev[0] == "progress":
            d, t = ev[1], ev[2]
            pct = round(d / t * 100, 1) if t else 0
            yield ("download_progress", f"{d//1024} KB / {t//1024} KB ({pct}%)",
                   {"downloaded": d, "total": t, "pct": pct})
        elif ev[0] == "done":
            fetch_meta = ev[1]
        elif ev[0] == "error":
            yield ("error", ev[1], None)
            return
    kb = fetch_meta["size_bytes"] // 1024
    yield ("step", f"下载完成 · {kb} KB · 披露 {fetch_meta.get('publish_date') or '?'}",
           {"step": "download", "status": "done"})

    # Step 2: markitdown 解析(整块, 约 30-60 秒, 无分进度)
    yield ("step", "markitdown 解析 PDF → MD", {"step": "parse", "status": "active"})
    try:
        parse_meta = await asyncio.to_thread(parser.parse_to_md, fetch_meta["pdf_path"], str(cdir))
    except Exception as e:
        yield ("error", f"解析失败: {type(e).__name__}: {e}", None)
        return
    yield ("step", f"解析完成 · {parse_meta['char_count']} 字",
           {"step": "parse", "status": "done"})

    # Step 3: 章节切分(在 parse_to_md 内完成)
    yield ("step", f"切出 {len(parse_meta['sections'])} 个章节",
           {"step": "section", "status": "done"})

    meta = {
        "code": code, "year": int(year),
        "company": fetch_meta["title"],
        "publish_date": fetch_meta.get("publish_date"),
        "source_url": fetch_meta["source_url"],
        "sha256": fetch_meta["sha256"],
        "pdf_size_bytes": fetch_meta["size_bytes"],
        "page_count": parse_meta["page_count"],
        "char_count": parse_meta["char_count"],
        "parse_seconds": parse_meta["parse_seconds"],
        "sections": parse_meta["sections"],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_meta(code, year, meta)

    secs = len(meta["sections"])
    yield ("done", f"wiki 沉淀完成: {meta['char_count']} 字 / {meta['page_count'] or '?'} 页 / 切出 {secs} 个章节", meta)


def _write_meta(code, year, meta):
    os.makedirs(_company_dir(code, year), exist_ok=True)
    with open(_meta_path(code, year), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _read_meta(code, year):
    p = _meta_path(code, year)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def get_meta(code, year):
    return _read_meta(code, year)


def get_md(code, year):
    p = _company_dir(code, year) / "full.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def get_section(code, year, sid):
    p = _company_dir(code, year) / "sections" / f"{sid}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def index():
    """扫 wiki/, 列出已沉淀的公司+年份。"""
    if not WIKI_ROOT.exists():
        return []
    result = []
    for code_dir in sorted(WIKI_ROOT.iterdir()):
        if not code_dir.is_dir():
            continue
        for year_dir in sorted(code_dir.iterdir()):
            if not year_dir.is_dir():
                continue
            try:
                yr = int(year_dir.name)
            except ValueError:
                continue
            meta = _read_meta(code_dir.name, yr) or {}
            result.append({
                "code": code_dir.name, "year": yr,
                "company": meta.get("company"),
                "char_count": meta.get("char_count"),
                "page_count": meta.get("page_count"),
            })
    return result
