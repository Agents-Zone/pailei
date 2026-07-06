"""PDF -> MD 解析。

第一层 full.md: markitdown 转全文(核心产物, 实测茅台 143 页 → 41s/35 万字)。
第二层 sections/: 从 full.md 切审计报告/三大报表/附注等关键章节(轻量正则, 容错——
   切不准不强求, full.md 始终可用; meta 记录切成功的章节)。
"""
import os
import re
import time

from markitdown import MarkItDown

_md = None


def _get_md():
    global _md
    if _md is None:
        _md = MarkItDown()
    return _md


# 关键章节: (章节id, 标题正则, 简述)。匹配"第十节 财务报告"下的"X、标题"格式(带中文序号 + 行首),
# 避免命中目录/页眉里的裸词(裸"审计报告""财务报表"在多处出现)。
SECTION_PATTERNS = [
    ("01_audit", r"[一二三四五六七八九十]+、\s*审\s*计\s*报\s*告", "审计报告"),
    ("02_statements", r"[一二三四五六七八九十]+、\s*财\s*务\s*报\s*表", "三大报表"),
    ("07_notes", r"[一二三四五六七八九十]+、\s*合\s*并\s*财\s*务\s*报\s*表\s*项\s*目\s*注\s*释", "附注(合并报表项目注释)"),
]


def parse_to_md(pdf_path: str, out_dir: str) -> dict:
    """转 PDF → out_dir/full.md + 切 sections/, 返回 meta。同步函数, 后端 asyncio.to_thread 包。"""
    os.makedirs(out_dir, exist_ok=True)
    sections_dir = os.path.join(out_dir, "sections")
    os.makedirs(sections_dir, exist_ok=True)

    t0 = time.time()
    result = _get_md().convert(pdf_path)
    md = result.text_content or ""
    full_path = os.path.join(out_dir, "full.md")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(md)
    parse_secs = round(time.time() - t0, 1)

    sections_meta = _split_sections(md, sections_dir)

    # 估算页数: markitdown 保留 "N / 总页" 形式的页码
    page_matches = re.findall(r"/\s*(\d{1,4})\s*\n", md)
    page_count = int(page_matches[-1]) if page_matches else None

    return {
        "pdf_path": pdf_path,
        "full_md_path": full_path,
        "char_count": len(md),
        "page_count": page_count,
        "parse_seconds": parse_secs,
        "sections": sections_meta,
    }


def _split_sections(md: str, sections_dir: str) -> list:
    """从 full.md 切关键章节。切不准返回空(不影响 full.md)。"""
    lines = md.split("\n")

    # 找"第X节 财务报告" 起点(年报结构, 节次可能变: 茅台 2024 第十节, 2025 第八节)
    fin_start = None
    for i, ln in enumerate(lines):
        if re.search(r"第[一二三四五六七八九十百零]+节.*财\s*务\s*报\s*告", ln) and len(ln.strip()) < 40:
            fin_start = i
            break
    if fin_start is None:
        return []  # 找不到财务报告章节, 跳过切分(容错)

    # 在财务报告起点之后, 找各关键章节起点
    starts = []
    for sid, pattern, desc in SECTION_PATTERNS:
        start = None
        for i in range(fin_start, len(lines)):
            ln = lines[i].strip()
            # 章节标题行: 行首匹配序号+关键词, 且行较短(排除正文长段落)
            if re.match(pattern, ln) and len(ln) < 40:
                start = i
                break
        starts.append((sid, desc, start))

    # 各章节 end = 下一章节 start - 1, 或文末
    result = []
    for idx, (sid, desc, start) in enumerate(starts):
        if start is None:
            continue
        later = [s for _, _, s in starts[idx + 1:] if s is not None and s > start]
        end = (min(later) - 1) if later else (len(lines) - 1)
        chunk = "\n".join(lines[start:end + 1])
        with open(os.path.join(sections_dir, f"{sid}.md"), "w", encoding="utf-8") as f:
            f.write(chunk)
        result.append({
            "id": sid, "title": desc,
            "start_line": start, "end_line": end,
            "char_count": len(chunk),
        })
    return result
