"""6 条红旗规则引擎。输入为 sources 返回的逐年数据(按 year 升序, 金额单位亿元)。

每条规则返回:
  {id, title, severity, what, hit(True/False/None), summary, yearly:[...]}
hit=None 表示数据不可得(nodata)。
"""
from typing import Optional

NON_STD_KEYWORDS = ("保留", "无法表示", "强调", "否定")


def _yoy(curr, prev):
    """同比增长率(%)。"""
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def _is_nonstd(opinion: str) -> bool:
    """是否非标审计意见(保留/无法表示/带强调/否定)。"""
    if not opinion:
        return False
    if "标准无保留" in opinion and "带强调" not in opinion:
        return False
    return any(k in opinion for k in NON_STD_KEYWORDS)


def rule_cash_debt(balance):
    """存贷双高: 货币资金与有息负债同时占总资产较高。"""
    yearly = []
    any_hit = False
    for r in balance:
        mf, ta = r["monetary_funds"], r["total_assets"]
        debt = (r["short_loan"] or 0) + (r["long_loan"] or 0)
        debt = round(debt, 2) if debt else None
        hit = False
        if mf and ta and debt and ta > 0:
            if mf / ta > 0.10 and debt / ta > 0.10:
                hit = True
                any_hit = True
        yearly.append({"year": r["year"], "monetary_funds": mf,
                       "interest_debt": debt, "total_assets": ta, "hit": hit})
    return {
        "id": "cash-debt", "title": "存贷双高", "severity": "critical",
        "what": "账上大量现金, 同时大量有息负债",
        "hit": any_hit,
        "summary": "货币资金与有息负债同时高企, 典型'存贷双高'信号" if any_hit else "未发现明显存贷双高",
        "yearly": yearly,
    }


def rule_receivable_revenue(balance, profit):
    """应收增速 vs 营收增速 背离。"""
    pmap = {p["year"]: p for p in profit}
    bmap = {b["year"]: b for b in balance}
    years = sorted(set(pmap) & set(bmap))
    yearly = []
    any_hit = False
    prev_inc = prev_rec = None
    max_gap = 0
    for y in years:
        inc = pmap[y]["operate_income"]
        rec = bmap[y]["accounts_rece"]
        inc_yoy = _yoy(inc, prev_inc)
        rec_yoy = _yoy(rec, prev_rec)
        gap = None
        hit = False
        if inc_yoy is not None and rec_yoy is not None:
            gap = round(rec_yoy - inc_yoy, 1)
            if gap > 20:
                hit = True
                any_hit = True
                max_gap = max(max_gap, gap)
        yearly.append({"year": y, "income_yoy": inc_yoy,
                       "receivable_yoy": rec_yoy, "gap_pp": gap, "hit": hit})
        prev_inc, prev_rec = inc, rec
    return {
        "id": "receivable-revenue", "title": "应收 / 收入背离", "severity": "warning",
        "what": "应收账款增速远超营收增速",
        "hit": any_hit,
        "summary": (f"应收增速持续高于营收增速(最大背离 {max_gap:.0f}pp)" if any_hit
                    else "应收与营收增速基本匹配"),
        "yearly": yearly,
    }


def rule_cashflow_profit(profit, cashflow):
    """现金流 / 净利背离。"""
    pmap = {p["year"]: p for p in profit}
    cmap = {c["year"]: c for c in cashflow}
    years = sorted(set(pmap) & set(cmap))
    yearly = []
    any_hit = False
    for y in years:
        np_ = pmap[y]["parent_netprofit"]
        ncf = cmap[y]["netcash_operate"]
        gap = None
        hit = False
        if np_ is not None and ncf is not None:
            gap = round(ncf - np_, 2)
            if (np_ > 0 and ncf < 0) or (np_ > 0 and ncf / np_ < 0.5):
                hit = True
                any_hit = True
        yearly.append({"year": y, "netprofit": np_, "netcash_operate": ncf,
                       "gap": gap, "hit": hit})
    return {
        "id": "cashflow-profit", "title": "现金流 / 净利背离", "severity": "critical",
        "what": "经营现金流持续跟不上净利润",
        "hit": any_hit,
        "summary": ("净利润为正但经营现金流为负或远低于净利, 利润质量存疑" if any_hit
                    else "现金流与净利润基本匹配"),
        "yearly": yearly,
    }


def rule_goodwill(balance):
    """商誉占净资产比。"""
    yearly = []
    any_hit = False
    max_ratio = 0
    for r in balance:
        gw, eq = r["goodwill"], r["total_equity"]
        ratio = None
        hit = False
        if gw and eq and eq > 0:
            ratio = round(gw / eq * 100, 1)
            if ratio > 30:
                hit = True
                any_hit = True
                max_ratio = max(max_ratio, ratio)
        yearly.append({"year": r["year"], "goodwill": gw,
                       "total_equity": eq, "ratio_pct": ratio, "hit": hit})
    return {
        "id": "goodwill", "title": "商誉 / 净资产", "severity": "warning",
        "what": "商誉占净资产比例过高",
        "hit": any_hit,
        "summary": (f"商誉占净资产比超 30%(峰值 {max_ratio:.0f}%)" if any_hit
                    else "商誉占比正常"),
        "yearly": yearly,
    }


def rule_audit(balance):
    """审计意见变化(滞后确认型)。"""
    yearly = []
    any_hit = False
    prev_op = None
    for r in balance:
        op = r["opinion"]
        changed = bool(prev_op and op and op != prev_op)
        turn_nonstd = changed and _is_nonstd(op) and not _is_nonstd(prev_op)
        if turn_nonstd:
            any_hit = True
        yearly.append({"year": r["year"], "opinion": op,
                       "changed": changed, "turn_nonstd": turn_nonstd})
        prev_op = op
    if any_hit:
        summary = "审计意见由标准无保留转为非标, 严重滞后确认信号"
    elif any(x["changed"] for x in yearly):
        summary = "审计意见有变化但未转非标"
    else:
        summary = "审计意见连续为标准无保留"
    return {
        "id": "audit-opinion", "title": "审计意见变化", "severity": "warning",
        "what": "意见类型逐年对比(滞后确认型, 不能当早期信号)",
        "hit": any_hit,
        "summary": summary,
        "yearly": yearly,
    }


def rule_related_party():
    """关联交易: akshare 无现成接口, 数据不可得。"""
    return {
        "id": "related-party", "title": "关联交易 / 资金占用", "severity": "info",
        "what": "关联交易占比及非经营性资金占用",
        "hit": None,
        "summary": "数据不可得: akshare 无关联交易结构化接口, 需读年报附注(Tier 2, PDF)",
        "yearly": [],
    }


def run_all(balance, profit, cashflow):
    """跑全部 6 条规则。"""
    return [
        rule_cash_debt(balance),
        rule_receivable_revenue(balance, profit),
        rule_cashflow_profit(profit, cashflow),
        rule_goodwill(balance),
        rule_audit(balance),
        rule_related_party(),
    ]


def hit_summary(rules):
    """汇总命中数。"""
    hit = sum(1 for r in rules if r["hit"] is True)
    miss = sum(1 for r in rules if r["hit"] is False)
    nodata = sum(1 for r in rules if r["hit"] is None)
    return {"hit": hit, "miss": miss, "nodata": nodata, "total": len(rules)}
