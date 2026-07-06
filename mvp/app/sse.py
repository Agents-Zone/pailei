"""SSE 事件封装。

事件协议（前端 app.js 按此处理）:
  card_start    {cardId, title, layer}        新 Card 出现, 进入 fetching
  card_data     {cardId, payload}             数据到达, 渲染
  card_done     {cardId, summary, flag}       这一步结论 (flag: hit/miss/nodata)
  analysis_chunk {text}                       大模型流式输出片段
  analysis_done {}                            综合分析完成
  fatal         {message}                     致命错误, 中断
"""
import json
from typing import Any


def event(event: str, data: Any = None) -> str:
    """格式化一个 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False) if data is not None else ""
    return f"event: {event}\ndata: {payload}\n\n"
