"""FastAPI 应用: /api/analyze SSE 流式编排 + 静态前端。

流程: 公司概览 → 资产负债表 → 利润表 → 现金流量表 → 6 条规则 → 规则汇总 → Agent 综合分析。
每个数据源/规则一张 Card, 边获取边推送。akshare 同步调用全部走 asyncio.to_thread。
"""
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()  # 加载 .env (PAILEI_API_BASE/KEY/MODEL)

from . import sources, rules, analyzer, wiki, wiki_agent, extractor
from .sse import event

app = FastAPI(title="PaiLei 排雷 MVP")
STATIC = Path(__file__).resolve().parent.parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/analyze")
def analyze(code: str = Query(..., description="A 股股票代码, 如 600518")):
    async def gen():
        # 1. 校验代码
        try:
            symbol = sources.to_symbol(code)
        except ValueError as e:
            yield event("fatal", {"message": str(e)})
            return

        # 2. 资产负债表(同时提取公司概览)
        try:
            yield event("card_start", {"cardId": "overview", "title": "公司概览", "layer": "data"})
            bal = await asyncio.to_thread(sources.fetch_balance, symbol)
            yield event("card_data", {"cardId": "overview", "payload": bal["info"]})
            yield event("card_done", {"cardId": "overview",
                        "summary": f"{bal['info']['name']} · {len(bal['rows'])} 年年报 · 最新 {bal['info']['latest_report']}",
                        "flag": None})
        except Exception as e:
            yield event("fatal", {"message": f"获取数据失败: {type(e).__name__}: {e}"})
            return

        yield event("card_start", {"cardId": "balance", "title": "资产负债表", "layer": "data"})
        yield event("card_data", {"cardId": "balance", "payload": bal["rows"]})
        yield event("card_done", {"cardId": "balance",
                    "summary": "货币资金 / 短期借款 / 应收账款 / 商誉 / 净资产 / 审计意见(逐年)", "flag": None})

        # 3. 利润表
        yield event("card_start", {"cardId": "profit", "title": "利润表", "layer": "data"})
        profit = await asyncio.to_thread(sources.fetch_profit, symbol)
        yield event("card_data", {"cardId": "profit", "payload": profit})
        yield event("card_done", {"cardId": "profit", "summary": "营业收入 / 归母净利润(逐年)", "flag": None})

        # 4. 现金流量表
        yield event("card_start", {"cardId": "cashflow", "title": "现金流量表", "layer": "data"})
        cashflow = await asyncio.to_thread(sources.fetch_cashflow, symbol)
        yield event("card_data", {"cardId": "cashflow", "payload": cashflow})
        yield event("card_done", {"cardId": "cashflow", "summary": "经营活动现金流净额(逐年)", "flag": None})

        # 5. 规则引擎(6 条)
        rule_results = rules.run_all(bal["rows"], profit, cashflow)
        for r in rule_results:
            cid = r["id"]
            yield event("card_start", {"cardId": cid, "title": r["title"], "layer": "rule"})
            yield event("card_data", {"cardId": cid, "payload": r})
            flag = "hit" if r["hit"] is True else ("nodata" if r["hit"] is None else "miss")
            yield event("card_done", {"cardId": cid, "summary": r["summary"], "flag": flag})

        # 6. 规则汇总
        hs = rules.hit_summary(rule_results)
        yield event("card_start", {"cardId": "summary", "title": "规则汇总", "layer": "summary"})
        yield event("card_data", {"cardId": "summary", "payload": hs})
        yield event("card_done", {"cardId": "summary",
                    "summary": f"{hs['hit']} 命中 / {hs['miss']} 未命中 / {hs['nodata']} 数据不可得",
                    "flag": "hit" if hs["hit"] > 0 else "miss"})

        # 7. Agent 综合分析(流式)
        yield event("card_start", {"cardId": "analysis", "title": "Agent 综合分析", "layer": "analysis"})
        try:
            async for chunk in analyzer.analyze_stream(
                    bal["info"], bal["rows"], profit, cashflow, rule_results):
                yield event("analysis_chunk", {"cardId": "analysis", "text": chunk})
        except Exception as e:
            yield event("analysis_chunk", {"cardId": "analysis",
                        "text": f"⚠️ 分析失败: {type(e).__name__}: {e}"})
        yield event("analysis_done", {"cardId": "analysis"})

        # 8. 深度排雷提示(渐进式: 初分后引导读年报附注)
        try:
            latest_year = int((bal["info"].get("latest_report") or "")[:4])
        except (ValueError, TypeError):
            latest_year = None
        if latest_year:
            yield event("deep_hint", {"code": code, "year": latest_year,
                                      "name": bal["info"].get("name"),
                                      "has_wiki": wiki.exists(code, latest_year)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ===== 深度排雷 Agent（渐进式: 初分后用户点触发, 读 wiki 附注）=====
@app.get("/api/agent/analyze")
def agent_analyze(code: str, year: int):
    """SSE: 确认/沉淀 wiki → Agent 读 wiki 章节(S1 占位, S2-S3 接真 Agent)。"""
    async def gen():
        try:
            sources.to_symbol(code)
        except ValueError as e:
            yield event("fatal", {"message": str(e)})
            return

        # 1. 确认 wiki 已沉淀(没有则自动 prepare, 推送进度)
        cid = "deep_prepare"
        if not wiki.exists(code, year):
            yield event("card_start", {"cardId": cid, "title": "深度排雷 · 沉淀年报 PDF", "layer": "deep"})
            async for stage, msg, meta in wiki.prepare(code, year):
                yield event("deep_progress", {"cardId": cid, "stage": stage, "message": msg, "meta": meta})
                if stage == "error":
                    yield event("card_done", {"cardId": cid, "summary": msg, "flag": "error"})
                    return
            yield event("card_done", {"cardId": cid, "summary": "wiki 沉淀完成", "flag": "done"})
        else:
            yield event("card_start", {"cardId": cid, "title": "深度排雷 · wiki 已就绪", "layer": "deep"})
            yield event("card_done", {"cardId": cid, "summary": "命中缓存, 直接深度分析", "flag": "done"})

        # 2. 数字层: akshare 规则(复用) + wiki statements 交叉验证
        yield event("card_start", {"cardId": "deep_number", "title": "深度 · 数字层（akshare 规则 + wiki 交叉）", "layer": "deep"})
        try:
            statements_md = wiki.get_section(code, year, "02_statements") or ""
            wiki_numbers = extractor.extract_numbers(statements_md) if statements_md else {}
            num = await wiki_agent.number_layer(sources.to_symbol(code), wiki_numbers)
            yield event("card_data", {"cardId": "deep_number", "payload": num})
            yield event("card_done", {"cardId": "deep_number",
                        "summary": f"规则 {num['hit_summary']['hit']} 命中 / wiki-akshare 交叉差异 {len(num['cross_diffs'])} 项",
                        "flag": "hit" if num['hit_summary']['hit'] else "done"})
        except Exception as e:
            yield event("card_done", {"cardId": "deep_number",
                        "summary": f"数字层失败: {type(e).__name__}: {e}", "flag": "error"})

        # 3. 附注层: notes 切片 + 5 规则 LLM 深读
        yield event("card_start", {"cardId": "deep_notes", "title": "深度 · 附注层（5 规则 LLM 深读）", "layer": "deep"})
        notes_md = wiki.get_section(code, year, "07_notes") or ""
        audit_md = wiki.get_section(code, year, "01_audit") or ""
        secs = extractor.split_notes(notes_md) if notes_md else []
        findings = await wiki_agent.note_layer(secs, audit_md, code, year)
        yield event("card_data", {"cardId": "deep_notes", "payload": {"findings": findings}})
        hit = sum(1 for f in findings if f.get("hit") is True)
        nodata = sum(1 for f in findings if f.get("hit") is None)
        yield event("card_done", {"cardId": "deep_notes",
                    "summary": f"5 规则: {hit} 命中 / {nodata} 跳过", "flag": "hit" if hit else "done"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ===== PDF Wiki 路由（Tier 2: PDF → MD wiki）=====
@app.get("/wiki")
def wiki_page():
    return FileResponse(STATIC / "wiki.html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/wiki/index")
def wiki_index():
    return wiki.index()


@app.get("/api/wiki/prepare")
def wiki_prepare(code: str, year: int):
    async def gen():
        try:
            async for stage, msg, meta in wiki.prepare(code, year):
                yield event("progress", {"stage": stage, "message": msg, "meta": meta})
        except Exception as e:
            yield event("fatal", {"message": f"{type(e).__name__}: {e}"})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/wiki/{code}/{year}/meta")
def wiki_meta(code: str, year: int):
    meta = wiki.get_meta(code, year)
    if not meta:
        raise HTTPException(404, detail="未找到该 wiki, 请先 prepare")
    return meta


@app.get("/api/wiki/{code}/{year}/md")
def wiki_md(code: str, year: int):
    md = wiki.get_md(code, year)
    if md is None:
        raise HTTPException(404, detail="未找到 full.md")
    return PlainTextResponse(md)


@app.get("/api/wiki/{code}/{year}/section/{sid}")
def wiki_section(code: str, year: int, sid: str):
    s = wiki.get_section(code, year, sid)
    if s is None:
        raise HTTPException(404, detail=f"未找到章节 {sid}(可能解析时未切出)")
    return PlainTextResponse(s)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
