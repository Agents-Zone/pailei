# PaiLei Agent 实现计划（基于 LLM wiki 排雷）

> 基于 `pailei_prd.md` 的阶段 3(初分) + 阶段 4(深分), 用 LLM wiki 已沉淀的章节 MD 做排雷。
> 数字层已决策: akshare + wiki 交叉; 附注层 5 规则; 输出标注在 wiki 上。

## 统一排雷架构（模式 A · 渐进式）

「开始排雷」做**统一入口**, 自动调度两层: akshare 秒级初分 → 末尾提示深度 → 用户点才跑 wiki Agent。

```
首页「开始排雷」
  ├─ 第 1 层 akshare 初分(秒级, 全公司)
  │    三大报表数字 → 6 条规则 → 综合分析 → Card 流
  │    末尾 yield 「📄 深度排雷」提示卡(读附注, 约 2 分钟)
  │
  └─ 第 2 层 wiki 深度(分钟级, 用户点触发)
       检查 wiki/{code}/{latest_year}
         有 → 命中缓存, 直接 Agent
         无 → prepare wiki(下载+解析, 步骤进度)
       Agent 读 wiki 章节:
         数字层: akshare + wiki statements 交叉
         附注层: notes 切片, 5 规则 LLM 深读
       深度 Card 追加到报告流 + findings 标注 wiki(点跳原文)
```

**要点**:
- akshare 秒级先出(体验好), 深度按需(用户决定等 2 分钟)
- wiki 命中缓存(已沉淀秒过)
- 统一报告流(初分 Card + 深度 Card 同一流)
- `PDF Wiki 页`保留为独立「沉淀/浏览原文」工具, 和深度排雷**共享 wiki/** 数据

**技术改动**:
- `app/main.py` `/api/analyze`(akshare) 末尾 yield `deep_hint` 卡(含该公司最新可披露年份)
- `static/app.js` 收 deep_hint → 渲染「📄 深度排雷」按钮卡 → 点按钮触发 prepare + agent
- 新 `GET /api/agent/analyze?code=&year=` (SSE): Agent 读 wiki 出深度 findings, 追加到同一报告流

---


## 设计决策（已和用户确认）

| 维度 | 决策 |
|---|---|
| 数字层 | **akshare + wiki statements 交叉验证**（akshare 提数字, wiki MD 交叉对比, 不一致标黄） |
| 附注规则 | **5 个全做**: 关联交易 / 会计政策变更 / 审计意见措辞 / 商誉业绩承诺 / 或有负债 |
| 输出形态 | **findings 标注在 wiki MD 上**（点 finding 跳原文高亮） |

## 核心矛盾：数字 vs 附注

- **数字层**：akshare 准（已有）；wiki statements MD 的表格 markitdown 转的可能乱 → 交叉验证兜底
- **附注层**：关联交易/会计政策变更/或有负债 **只在 wiki notes MD**（akshare 拿不到）→ 这是差异化

## 架构

```
输入: 已 prepare 的 wiki(章节 MD 已沉淀) + akshare 数字
  │
  ├─ 数字层(秒级, 复用 rules.py)
  │   akshare 三大报表数字 → rules.py 跑 6 条规则 → findings_数字
  │   wiki statements MD 提关键科目数字 → 与 akshare 交叉 → 不一致标黄
  │
  ├─ 附注层(分钟级, per-finding LLM)
  │   notes MD 按"X、科目名"切子科目片
  │   5 个附注规则各定位对应切片:
  │     关联交易    → 「关联方及关联交易」切片
  │     会计政策变更 → 「重要会计政策及会计估计」+ 附注"会计差错"措辞
  │     审计措辞    → audit 切片(意见类型 + 强调事项段)
  │     商誉承诺    → 「商誉」切片(业绩承诺达成)
  │     或有负债    → 「或有事项/对外担保」切片
  │   LLM 读切片 → 判定(异常/可解释/信息不足) + 原文引用 + 严重度
  │
  └─ 合并 → 每条 finding 锚定 {章节, 起止行} → 标注到 wiki MD(点跳原文高亮)
```

## 输出 finding 结构

```json
{
  "id": "related_party_2024",
  "rule": "关联交易/资金占用",
  "layer": "note",            // number | note
  "severity": "critical",
  "year": 2024,
  "headline": "控股股东非经营性占用 ...",
  "source": {"section": "09_related_party", "start_line": 123, "end_line": 145},
  "llm_judgment": "需关注: ...",
  "evidence": "原文片段..."
}
```

## 模块（新增）

| 文件 | 职责 |
|---|---|
| `app/extractor.py` | notes MD 按子科目切片 + statements MD 提关键数字(交叉用) |
| `app/agent.py` | 数字层(复用 rules.py + 交叉) + 附注层(per-finding LLM, AsyncOpenAI) |
| `app/main.py` | 加 `GET /api/wiki/{code}/{year}/analyze` (SSE 流式 findings) |
| `static/wiki.js` | 加「🔍 排雷」按钮 + findings 标注渲染(点跳原文高亮) |
| `static/wiki.html` | findings 标注样式 |

## 分阶段实现（5-7 天）

| M | 内容 | 估时 |
|---|---|---|
| **M1** 切片 + 数字层骨架 | extractor: notes 按子科目切片(容错); agent 数字层: akshare 规则 + wiki 交叉(关键几科目); 前端「排雷」按钮 + findings 卡片(先不标注) | 2 天 |
| **M2** 附注层 5 规则 | agent 附注层: 5 规则各定位切片 + LLM 判定 + 原文引用; 控制 ~10 次调用/公司 | 2-3 天 |
| **M3** 标注 wiki | findings 锚定章节行号 → wiki MD 渲染时标注 + 点跳高亮 | 1-2 天 |

## 关键风险

| 风险 | 防御 |
|---|---|
| statements MD 数字提取乱(markitdown 表格) | 先只提关键 5-6 科目; 失败则该规则纯走 akshare, 不强求交叉 |
| notes 子科目切片不准(标题正则) | 容错: 切不到标"未切", 该规则跳过; 不影响其他规则 |
| LLM 调用成本/限速(5 规则×切片) | 控制每公司 ≤10 次; 支持跳过附注层(纯数字层也能出报告) |
| finding 行号→DOM 映射 | 切片时记 MD 起止行; 标注时按行定位(不重算) |
| LLM 幻觉 | 强制要求引用原文片段(可核对); 数字层(akshare)做事实兜底 |

## 和现有 MVP 的关系

- **akshare MVP（Tier 1 初分, 已跑通）**：保留, 秒级全市场预筛
- **wiki 沉淀（本轮已完成）**：PDF→章节 MD, Agent 的输入
- **Agent（本计划）**：基于 wiki 深分, 只对 prepare 过的公司跑
- 三层共存：akshare 初筛 → wiki 沉淀 → Agent 深读
