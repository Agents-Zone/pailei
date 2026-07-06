"""akshare 数据源层。

每个 fetch 函数拉一个数据源, 过滤年报(12-31), 取最近 N 年, 返回标准化 dict 列表。
金额统一转成"亿元"(除以 1e8, 保留 2 位), 便于前端展示和规则计算。

字段映射(实测 akshare 1.18.64 东财接口):
  资产负债表 stock_balance_sheet_by_report_em(symbol="SH600518")
    MONETARYFUNDS 货币资金 / SHORT_LOAN 短期借款 / LONG_LOAN 长期借款
    ACCOUNTS_RECE 应收账款 / GOODWILL 商誉
    TOTAL_EQUITY 净资产 / TOTAL_ASSETS 总资产 / OPINION_TYPE 审计意见
    SECURITY_NAME_ABBR 公司简称
  利润表 stock_profit_sheet_by_yearly_em  OPERATE_INCOME 营收 / PARENT_NETPROFIT 归母净利
  现金流量表 stock_cash_flow_sheet_by_report_em  NETCASH_OPERATE 经营现金流
注意: symbol 必须带市场前缀 SH/SZ/BJ。
"""
import akshare as ak
import pandas as pd

YEARS = 10  # 取最近 10 年年报(覆盖大多数公司的历史暴雷期, 如康美 2016-2018)


def to_symbol(code: str) -> str:
    """6 位代码 -> 带市场前缀的 symbol。已带前缀则原样返回。"""
    code = code.strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        return code
    if not (code.isdigit() and len(code) == 6):
        raise ValueError(f"无效的股票代码: {code}")
    head = code[0]
    if head in ("6", "9"):
        return "SH" + code
    if head in ("0", "2", "3"):
        return "SZ" + code
    if head in ("8", "4"):
        return "BJ" + code
    raise ValueError(f"无法识别的股票代码: {code}")


def _yi(v):
    """元 -> 亿元(float), None/NaN -> None。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return round(f / 1e8, 2)


def _filter_yearly(df, years=YEARS):
    """过滤年报(报告期含 12-31), 取最近 N 年, 按年升序。"""
    if df is None or df.empty:
        return pd.DataFrame()
    rd = df["REPORT_DATE"].astype(str)
    df = df[rd.str.contains("12-31", na=False)].copy()
    df["year"] = rd.str[:4].astype(int)
    df = df.sort_values("year").tail(years)
    return df


def _opinion(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def fetch_balance(symbol: str, years=YEARS) -> dict:
    """资产负债表(年报)。返回 {info, rows}。info 供"公司概览"Card 用。"""
    df = _filter_yearly(ak.stock_balance_sheet_by_report_em(symbol=symbol), years)
    if df.empty:
        raise RuntimeError("资产负债表为空, 请检查股票代码或换一家公司")
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "year": int(r["year"]),
            "monetary_funds": _yi(r.get("MONETARYFUNDS")),
            "short_loan": _yi(r.get("SHORT_LOAN")),
            "long_loan": _yi(r.get("LONG_LOAN")),
            "accounts_rece": _yi(r.get("ACCOUNTS_RECE")),
            "goodwill": _yi(r.get("GOODWILL")),
            "total_equity": _yi(r.get("TOTAL_EQUITY")),
            "total_assets": _yi(r.get("TOTAL_ASSETS")),
            "opinion": _opinion(r.get("OPINION_TYPE")),
        })
    latest = df.iloc[-1]
    info = {
        "name": str(df.iloc[-1].get("SECURITY_NAME_ABBR", "") or symbol),
        "code": symbol,
        "latest_report": str(latest.get("REPORT_DATE", ""))[:10],
        "total_assets": _yi(latest.get("TOTAL_ASSETS")),
        "total_equity": _yi(latest.get("TOTAL_EQUITY")),
        "report_count": len(rows),
    }
    return {"info": info, "rows": rows}


def fetch_profit(symbol: str, years=YEARS) -> list:
    """利润表(年报)。"""
    df = _filter_yearly(ak.stock_profit_sheet_by_yearly_em(symbol=symbol), years)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "year": int(r["year"]),
            "operate_income": _yi(r.get("OPERATE_INCOME")),
            "parent_netprofit": _yi(r.get("PARENT_NETPROFIT")),
            "netprofit": _yi(r.get("NETPROFIT")),
            "opinion": _opinion(r.get("OPINION_TYPE")),
        })
    return rows


def fetch_cashflow(symbol: str, years=YEARS) -> list:
    """现金流量表(年报)。"""
    df = _filter_yearly(ak.stock_cash_flow_sheet_by_report_em(symbol=symbol), years)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "year": int(r["year"]),
            "netcash_operate": _yi(r.get("NETCASH_OPERATE")),
        })
    return rows
