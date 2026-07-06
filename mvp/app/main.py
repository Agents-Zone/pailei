"""FastAPI 应用: /api/analyze SSE 流式编排 + 静态前端。

流程: 公司概览 → 资产负债表 → 利润表 → 现金流量表 → 6 条规则 → 规则汇总 → Agent 综合分析。
每个数据源/规则一张 Card, 边获取边推送。akshare 同步调用全部走 asyncio.to_thread。
"""
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()  # 加载 .env (PAILEI_API_BASE/KEY/MODEL)

from . import sources, rules, analyzer
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

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
