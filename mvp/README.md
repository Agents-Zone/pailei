# PaiLei 排雷 · 真 Agent MVP

输入一个 A 股股票代码 → Agent 用 **akshare** 实时拉财报 → 前端按 Card 顺序流式渲染 → 跑 6 条红旗规则 → 大模型综合分析。

## 本地启动（3 步）

```bash
cd campaigns/opensource-fin-agent/mvp

# 1. 装依赖（venv 已建好；换机器则先 python3 -m venv .venv）
.venv/bin/pip install -r requirements.txt

# 2. 配大模型 key（仓库私有，.env.example 已预置硅基流动共享测试 key，直接复制即可）
cp .env.example .env
#   默认 SiliconFlow Qwen3-32B（同事无需自己申请 key）。换自己的 key 再编辑 .env。
#   不配也能跑，只是最后「Agent 综合分析」卡显示降级提示。

# 3. 起服务
.venv/bin/uvicorn app.main:app --port 8001
```

浏览器打开 **http://localhost:8001**。

> 改了代码（app/ 或 static/）直接刷新浏览器即可，不用重启。改了 .env 要重启服务。

## 用法

- 默认 `600518`（康美药业），点「开始排雷」
- Card 一张张流式出现：概览 → 资产负债表 → 利润表 → 现金流量表 → 6 条规则 → 汇总 → Agent 综合分析
- 规则命中标红 / 未命中标绿 / 数据不可得标灰
- 试试 `600519`（茅台，干净）、`000651`（格力）

**完整跑一次约 50-60 秒**：akshare 串行拉 3 个接口 ~30 秒 + 大模型生成 ~20-30 秒。Agent 分析卡会显示「🤔 大模型分析中」占位，耐心等。

## 数据源（akshare，免费）

| 接口 | 拿什么 |
|---|---|
| `stock_balance_sheet_by_report_em(symbol="SH600518")` | 货币资金、短期借款、应收账款、商誉、净资产、总资产、**审计意见 OPINION_TYPE** |
| `stock_profit_sheet_by_yearly_em` | 营业收入、归母净利润 |
| `stock_cash_flow_sheet_by_report_em` | 经营活动现金流净额 |

- **symbol 必须带市场前缀**：`SH`（6/9 开头）、`SZ`（0/2/3 开头）、`BJ`（8/4 开头）。`sources.to_symbol()` 自动转。
- 字段是英文大写（`MONETARYFUNDS` / `SHORT_LOAN` / `TOTAL_EQUITY` / `OPINION_TYPE` …）。
- 取最近 **10 年年报**（覆盖历史暴雷期，如康美 2016-2018）。金额转成亿元。

## 规则引擎（6 条）

| 规则 | 判定 |
|---|---|
| 存贷双高 | 货币资金与有息负债同时占总资产 >10% |
| 应收/收入背离 | 应收增速超营收增速 20pp |
| 现金流/净利背离 | 净利为正但经营现金流为负，或现金流/净利 < 0.5 |
| 商誉占净资产 | 商誉/净资产 > 30% |
| 审计意见变化 | 标准无保留 → 非标（保留/无法表示/强调） |
| 关联交易占比 | ⚠️ akshare 无现成接口，标「数据不可得」（需 Tier 2 读年报附注） |

## 大模型配置（OpenAI 兼容，任选一家）

| 厂商 | PAILEI_API_BASE | PAILEI_MODEL |
|---|---|---|
| 硅基流动 SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-32B` / `Qwen/Qwen3-8B` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| Qwen 通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Kimi 月之暗面 | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| GLM 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |

代码里已对 Qwen3 关闭思维链（`enable_thinking=False`），避免 `<think>` 标签污染输出。

## 架构

```
浏览器(前端 Card 流式, EventSource 接 SSE)
  ↑ SSE (text/event-stream)
FastAPI 后端
  ├─ akshare 拉三大报表(同步 → asyncio.to_thread, 不阻塞事件循环)
  ├─ 6 条规则引擎(数字交给规则)
  └─ 大模型综合分析(AsyncOpenAI 流式, 文字交给大模型)
```

```
mvp/
├── app/{main,sources,rules,analyzer,sse}.py   后端
├── static/{index.html,style.css,app.js}        前端 Card 流式
├── requirements.txt / .env.example / README.md
└── .venv/                                      本地虚拟环境(不入库)
```

## 边界（这个版本不做）

- ❌ **不含 PDF 附注解读**（Tier 2，下一步）：关联交易、会计政策变更、或有负债只在年报附注里，akshare 拿不到。规则 6 的缺口就是为引出这一层。
- ❌ 不做并发/缓存/增量更新（生产级，后续）
- ❌ 不荐股、不预测、不对未判决公司下结论
- 跑一次 50-60 秒（akshare 串行），生产级要加缓存

## 已知行为

- akshare 是东财**差错更正后口径**（康美 2017 货币资金显示 42 亿，是更正后的；原始披露 341 亿是虚增的）。反而更真实。
- akshare 偶发限频/网络抖动 → 单个 Card 可能 error，不中断整体。
- 默认取最近 10 年；改 `sources.py` 顶部 `YEARS` 调整窗口。

## 路线图

- **Tier 1（已完成）**：akshare 结构化初分 + 6 规则 + 综合分析，秒级
- **Tier 2（已完成）**：年报 PDF → LLM wiki 沉淀（巨潮 + markitdown + 章节切分）+ Agent 深度排雷（数字层交叉 + 附注层 5 规则 LLM 深读）
- **下一步**：findings 标注到 wiki 原文（点跳章节高亮）、更多暴雷案例回测、规则可插拔扩展

欢迎 issue / PR 补充红旗规则，规则集在 `app/rules.py` + `app/wiki_agent.py`。
