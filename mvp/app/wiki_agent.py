"""基于 LLM wiki 的 Agent: 数字层(akshare 规则 + wiki statements 交叉) + 附注层(5 规则 LLM)。

数字层: 复用 rules.py(akshare 数字) + extractor(wiki statements 提数) 交叉验证。
附注层: notes 子科目切片 → 5 规则各定位切片 → LLM 判定 + 原文引用。
全部容错: 单规则/单 LLM 失败不影响其他。
"""
import asyncio
import json
import os
import re

from openai import AsyncOpenAI

from . import extractor, rules, sources


# =================== 数字层 ===================
async def number_layer(symbol: str, wiki_numbers: dict) -> dict:
    """akshare 拉数据 + 跑规则 + wiki 交叉。返回 {info, rule_results, hit_summary, cross_diffs}。"""
    bal, profit, cashflow = await asyncio.gather(
        asyncio.to_thread(sources.fetch_balance, symbol),
        asyncio.to_thread(sources.fetch_profit, symbol),
        asyncio.to_thread(sources.fetch_cashflow, symbol),
    )
    rule_results = rules.run_all(bal["rows"], profit, cashflow)
    return {
        "info": bal["info"],
        "rule_results": rule_results,
        "hit_summary": rules.hit_summary(rule_results),
        "cross_diffs": _cross_check(bal["rows"], wiki_numbers),
        "wiki_numbers": wiki_numbers,
    }


def _cross_check(bal_rows: list, wiki_numbers: dict) -> list:
    """wiki statements 提的期末数 vs akshare 最新年, 差异 >5% 标黄。akshare 已是亿元。"""
    if not wiki_numbers or not bal_rows:
        return []
    latest = bal_rows[-1]
    pairs = [
        ("货币资金", latest.get("monetary_funds"), wiki_numbers.get("货币资金")),
        ("应收账款", latest.get("accounts_rece"), wiki_numbers.get("应收账款")),
        ("商誉", latest.get("goodwill"), wiki_numbers.get("商誉")),
        ("净资产", latest.get("total_equity"), wiki_numbers.get("净资产")),
    ]
    diffs = []
    for name, ak_yi, wiki_yuan in pairs:
        if ak_yi is None or wiki_yuan is None:
            continue
        wiki_yi = wiki_yuan / 1e8
        if abs(ak_yi) < 0.01:
            continue
        rate = abs(ak_yi - wiki_yi) / abs(ak_yi)
        if rate > 0.05:
            diffs.append({"科目": name, "akshare_亿": round(ak_yi, 2),
                          "wiki_亿": round(wiki_yi, 2), "差异率": f"{rate * 100:.0f}%"})
    return diffs


# =================== 附注层(5 规则 LLM) ===================
NOTE_RULES = [
    {"id": "related_party", "title": "关联交易 / 资金占用",
     "keywords": ["关联方及关联交易", "关联交易", "关联方往来", "资金占用"]},
    {"id": "accounting_policy", "title": "会计政策 / 估计变更",
     "keywords": ["会计政策", "会计估计", "会计差错", "前期差错"]},
    {"id": "goodwill", "title": "商誉 / 业绩承诺",
     "keywords": ["商誉", "业绩承诺"]},
    {"id": "contingent", "title": "或有负债 / 担保 / 诉讼",
     "keywords": ["或有事项", "担保", "诉讼", "未决"]},
    {"id": "audit_wording", "title": "审计意见措辞",
     "keywords": [], "use_audit": True},
]


async def note_layer(notes_sections: list, audit_md: str, code: str, year: int,
                     on_progress=None) -> list:
    """5 规则各定位附注切片 → LLM 读 → finding。on_progress(rule_idx, msg) 报进度。"""
    base = os.getenv("PAILEI_API_BASE", "").strip()
    key = os.getenv("PAILEI_API_KEY", "").strip()
    model = os.getenv("PAILEI_MODEL", "").strip()
    has_llm = bool(base and key and model)

    findings = []
    for i, r in enumerate(NOTE_RULES):
        if on_progress:
            await on_progress(i, f"[{i+1}/5] {r['title']}…")
        section_content, section_ref = _locate(r, notes_sections, audit_md)
        if not section_content:
            findings.append(_no_section_finding(r, section_ref))
            continue
        if not has_llm:
            findings.append(_no_llm_finding(r, section_ref, section_content))
            continue
        finding = await _llm_judge(base, key, model, r, section_content, section_ref, code, year)
        findings.append(finding)
    return findings


def _locate(rule, notes_sections, audit_md):
    if rule.get("use_audit"):
        return (audit_md[:8000] if audit_md else None), "审计报告"
    s = extractor.find_note_section(notes_sections, rule["keywords"])
    if s:
        return s["content"][:8000], f"附注 {s['num']}、{s['title']}"
    return None, ""


def _no_section_finding(rule, ref):
    return {"id": rule["id"], "title": rule["title"], "severity": "info", "hit": None,
            "summary": f"未找到对应附注({', '.join(rule['keywords']) or '审计报告'}), 跳过",
            "evidence": "", "section_ref": ref or "未定位"}


def _no_llm_finding(rule, ref, content):
    return {"id": rule["id"], "title": rule["title"], "severity": "info", "hit": None,
            "summary": f"附注切片就绪({ref}, {len(content)} 字), 未配 LLM key, 跳过深读",
            "evidence": content[:200], "section_ref": ref}


async def _llm_judge(base, key, model, rule, content, ref, code, year):
    prompt = (
        f"你是财报排雷分析师。基于以下 A 股上市公司年报附注切片, 判断是否存在「{rule['title']}」相关的风险信号。\n\n"
        f"公司: {code} {year} 年报\n附注章节: {ref}\n\n附注切片(原文):\n{content}\n\n"
        f"要求: 1) 判断有无风险信号(是/否/信息不足) 2) 如有, 描述 + 引用原文片段(可核验) "
        f"3) 严重度 critical/warning/info 4) 不下'造假'结论, 只说'需关注信号' "
        f"5) 仅输出 JSON: {{\"hit\": true|false|\"unknown\", \"severity\": \"...\", \"summary\": \"...\", \"evidence\": \"原文片段...\"}}"
    )
    try:
        client = AsyncOpenAI(base_url=base, api_key=key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"enable_thinking": False},
        )
        txt = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return _err_finding(rule, ref, "LLM 返回非 JSON")
        data = json.loads(m.group(0))
        hit = data.get("hit")
        if hit == "true":
            hit = True
        elif hit == "false":
            hit = False
        return {"id": rule["id"], "title": rule["title"],
                "severity": data.get("severity", "info"), "hit": hit,
                "summary": data.get("summary", ""), "evidence": data.get("evidence", ""),
                "section_ref": ref}
    except Exception as e:
        return _err_finding(rule, ref, f"{type(e).__name__}: {e}")


def _err_finding(rule, ref, msg):
    return {"id": rule["id"], "title": rule["title"], "severity": "info", "hit": None,
            "summary": f"LLM 判定失败: {msg}", "evidence": "", "section_ref": ref}
