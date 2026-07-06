"""大模型综合分析层。OpenAI 兼容端点, 流式输出(async)。

未配置 PAILEI_API_BASE/KEY/MODEL 时降级: 返回提示文本, 不阻塞流程。
"""
import os
from openai import AsyncOpenAI

SYSTEM = """你是财报排雷分析师。基于提供的上市公司公开财报数据(已结构化)和规则引擎结果, 给出一份简明的综合风险分析。

要求:
1. 先 2-3 句给整体判断(这家公司财报是否值得警惕)
2. 逐条点评命中的红旗(引用具体年份数据)
3. 指出哪些信号最值得重点关注
4. 诚实说明: 本分析只覆盖三大报表结构化科目, 附注层面的雷(会计政策变更/或有负债/关联方等)需读年报原文, 这里看不到
5. 不下"造假"结论, 只说"需关注信号"; 不荐股, 不构成投资建议

语气: 专业、克制、有数据。中文。不超过 400 字。用 Markdown, 但不要用 Markdown 表格, 改用列表和短段落。"""


def _build_prompt(info, balance, profit, cashflow, rule_results):
    L = []
    L.append(f"公司: {info['name']}({info['code']})  最新报告期: {info['latest_report']}\n")
    L.append("## 资产负债表(亿元)\n| 年份 | 货币资金 | 短期借款 | 应收账款 | 商誉 | 净资产 | 总资产 | 审计意见 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in balance:
        L.append(f"| {r['year']} | {r['monetary_funds']} | {r['short_loan']} | {r['accounts_rece']} | {r['goodwill']} | {r['total_equity']} | {r['total_assets']} | {r['opinion']} |")
    L.append("\n## 利润表(亿元)\n| 年份 | 营业收入 | 归母净利润 |\n|---|---|---|")
    for r in profit:
        L.append(f"| {r['year']} | {r['operate_income']} | {r['parent_netprofit']} |")
    L.append("\n## 现金流量表(亿元)\n| 年份 | 经营现金流净额 |\n|---|---|")
    for r in cashflow:
        L.append(f"| {r['year']} | {r['netcash_operate']} |")
    L.append("\n## 规则引擎结果")
    for r in rule_results:
        status = "🔴命中" if r["hit"] is True else ("⚪未命中" if r["hit"] is False else "⚫数据不可得")
        L.append(f"- {r['title']}: {status} — {r['summary']}")
    return "\n".join(L)


async def analyze_stream(info, balance, profit, cashflow, rule_results):
    """异步流式生成综合分析。yield 文本 chunk。未配 key 时降级。"""
    base = os.getenv("PAILEI_API_BASE", "").strip()
    key = os.getenv("PAILEI_API_KEY", "").strip()
    model = os.getenv("PAILEI_MODEL", "").strip()
    if not (base and key and model):
        yield ("⚠️ **未配置大模型 API key, 跳过 Agent 综合分析。**\n\n"
               "规则引擎结果(基于公开财报结构化数据)见上方各红旗卡片。"
               "在 `.env` 配置 `PAILEI_API_BASE` / `PAILEI_API_KEY` / `PAILEI_MODEL` 后重启服务即可启用。")
        return
    prompt = _build_prompt(info, balance, profit, cashflow, rule_results)
    client = AsyncOpenAI(base_url=base, api_key=key)
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": prompt}],
            stream=True,
            extra_body={"enable_thinking": False},  # 关 Qwen3 思维链(SiliconFlow); 其他 OpenAI 兼容端点会忽略未知字段
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n\n⚠️ 大模型调用失败: {type(e).__name__}: {e}"
