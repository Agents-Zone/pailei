"""巨潮资讯网 PDF 下载。

沪深京统一查询(column=szse), 无 WAF, PDF 直链 static.cninfo.com.cn/{adjunctUrl}。
实测: 茅台/比亚迪均能查到年报并下载真实 PDF。
"""
import asyncio
import hashlib
import os
from functools import lru_cache

import httpx
import requests

ORG_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_HOST = "http://static.cninfo.com.cn/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


@lru_cache(maxsize=1)
def _org_map() -> dict:
    """code -> orgId 字典(沪深京全市场, 调一次缓存)。"""
    r = requests.get(ORG_URL, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    return {s["code"]: s["orgId"] for s in r.json()["stockList"]}


def _query_announcements(code: str, year: int) -> list:
    """查某公司指定年份年报公告(沪深京都走 column=szse)。"""
    org = _org_map()
    if code not in org:
        raise ValueError(f"巨潮找不到股票代码 {code}(非沪深京 A 股?)")
    # 年报通常在次年 1-4 月披露, 查 [year-01, year+1-12] 覆盖所有可能披露窗口
    payload = {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
        "stock": f"{code},{org[code]}", "category": "category_ndbg_szsh",
        "seDate": f"{int(year) - 1}-01-01~{int(year) + 1}-12-31", "isHLtitle": "true",
    }
    r = requests.post(QUERY_URL, data=payload, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json().get("announcements") or []


# 标题里出现这些词的版本要排除(只要原始年报)
_SKIP_KW = ("摘要", "英文", "修订", "更正", "更新", "已取消", "取消", "H股", "disclosure")


def _pick_year_report(ann: list, year: int) -> dict:
    """从公告列表挑出指定年份的原始年报标题。"""
    target = f"{year}年年度报告"
    exact, fallback = None, None
    for a in ann:
        title = a.get("announcementTitle", "")
        if target not in title or any(k in title for k in _SKIP_KW):
            continue
        idx = title.find(target)
        after = title[idx + len(target):].strip()
        if after == "" and exact is None:
            exact = a  # 标题恰好以 target 结尾 = 原始年报
        elif fallback is None:
            fallback = a
    return exact or fallback


def fetch_pdf(code: str, year: int, out_dir: str) -> dict:
    """下载年报 PDF 到 out_dir/original.pdf, 返回 meta。同步函数, 后端用 asyncio.to_thread 包。"""
    ann = _query_announcements(code, year)
    picked = _pick_year_report(ann, year)
    if not picked:
        raise ValueError(
            f"未找到 {code} 的 {year} 年年度报告(巨潮返回 {len(ann)} 条相关公告)。"
            f"可能该年尚未披露, 或代码/年份错误。")

    adjunct = picked.get("adjunctUrl", "").strip()
    if not adjunct:
        raise ValueError("公告无 PDF 链接(adjunctUrl 为空)")

    url = PDF_HOST + adjunct
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, "original.pdf")

    r = requests.get(url, timeout=180, headers={"User-Agent": UA}, stream=True)
    r.raise_for_status()
    with open(pdf_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    with open(pdf_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    size = os.path.getsize(pdf_path)

    ann_time = picked.get("announcementTime")
    # 巨潮 announcementTime 是毫秒时间戳
    pub_date = None
    if ann_time:
        try:
            import datetime
            pub_date = datetime.date.fromtimestamp(int(ann_time) / 1000).isoformat()
        except Exception:
            pass

    return {
        "code": code, "year": int(year),
        "title": picked.get("announcementTitle"),
        "source_url": url,
        "pdf_path": pdf_path,
        "sha256": sha, "size_bytes": size,
        "publish_date": pub_date,
        "candidates_count": len(ann),
    }


async def fetch_pdf_stream(code: str, year: int, out_dir: str):
    """异步流式下载年报 PDF。async generator:
    yield ("progress", downloaded_bytes, total_bytes)  多次(实时进度)
    yield ("done", meta_dict)                          最后
    yield ("error", message)                           失败
    """
    try:
        ann = await asyncio.to_thread(_query_announcements, code, year)
    except Exception as e:
        yield ("error", f"查询巨潮失败: {type(e).__name__}: {e}"); return
    picked = _pick_year_report(ann, year)
    if not picked:
        yield ("error", f"未找到 {code} 的 {year} 年年度报告(巨潮返回 {len(ann)} 条相关公告)"); return
    adjunct = (picked.get("adjunctUrl") or "").strip()
    if not adjunct:
        yield ("error", "公告无 PDF 链接(adjunctUrl 为空)"); return

    url = PDF_HOST + adjunct
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, "original.pdf")
    try:
        async with httpx.AsyncClient(timeout=180.0, headers={"User-Agent": UA}, follow_redirects=True) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                with open(pdf_path, "wb") as f:
                    async for chunk in r.aiter_bytes(65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        yield ("progress", downloaded, total)
    except Exception as e:
        yield ("error", f"下载失败: {type(e).__name__}: {e}"); return

    with open(pdf_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    size = os.path.getsize(pdf_path)
    ann_time = picked.get("announcementTime")
    pub_date = None
    if ann_time:
        try:
            import datetime
            pub_date = datetime.date.fromtimestamp(int(ann_time) / 1000).isoformat()
        except Exception:
            pass
    yield ("done", {
        "code": code, "year": int(year),
        "title": picked.get("announcementTitle"),
        "source_url": url, "pdf_path": pdf_path,
        "sha256": sha, "size_bytes": size,
        "publish_date": pub_date, "candidates_count": len(ann),
    })
