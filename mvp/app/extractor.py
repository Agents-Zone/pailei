"""从 LLM wiki 章节提取结构化信息: notes 子科目切片 + statements 关键数字。

markitdown 转的表格/文本格式不统一, 提取脆弱, 全部容错(失败返回 None/空), 不抛异常。
"""
import re


# ============ notes 子科目切片 ============
def split_notes(notes_md: str) -> list:
    """按行首 '数字、名称' 切子科目。返回 [{id,num,title,start_line,end_line,char_count,content}]。"""
    if not notes_md:
        return []
    lines = notes_md.split("\n")
    pat = re.compile(r"^(\d+)\s*、\s*(.+?)\s*$")
    cuts = []
    for i, ln in enumerate(lines):
        m = pat.match(ln.strip())
        if not m:
            continue
        title = m.group(2).strip()
        if len(title) > 30:
            continue
        # 排除标题里含阿拉伯数字的(通常是子表数据行如"1、基本养老保险 231,702.09")
        if re.search(r"\d", title):
            continue
        cuts.append((i, m.group(1), title))
    if len(cuts) < 2:
        return []
    result = []
    for idx, (start, num, title) in enumerate(cuts):
        end = cuts[idx + 1][0] if idx + 1 < len(cuts) else len(lines)
        content = "\n".join(lines[start:end])
        result.append({
            "id": f"note_{num}", "num": num, "title": title,
            "start_line": start, "end_line": end - 1,
            "char_count": len(content), "content": content,
        })
    return result


def find_note_section(notes_sections: list, keywords: list):
    """按标题关键词找切片; 标题没找到则在内容前 500 字找。"""
    for s in notes_sections:
        if any(k in s["title"] for k in keywords):
            return s
    for s in notes_sections:
        if any(k in s["content"][:500] for k in keywords):
            return s
    return None


# ============ statements 提数字 ============
NUM_NAMES = {
    "货币资金": ["货币资金"],
    "短期借款": ["短期借款"],
    "应收账款": ["应收账款"],
    "商誉": ["商誉"],
    "净资产": ["归属于母公司所有者权益合计", "所有者权益合计", "股东权益合计", "所有者权益"],
    "营业总收入": ["营业总收入", "营业收入"],
    "净利润": ["归属于母公司所有者的净利润", "净利润"],
}


def extract_numbers(statements_md: str) -> dict:
    """从 statements MD 提关键科目期末数字(单位:元)。脆弱, 失败 None。"""
    out = {}
    for key, names in NUM_NAMES.items():
        val = None
        for name in names:
            val = _find_num(statements_md, name)
            if val is not None:
                break
        out[key] = val
    return out


def _find_num(md: str, name: str):
    """找 name 后 120 字符内第一个至少 4 位的数字(元, 可含逗号/小数)。"""
    idx = md.find(name)
    if idx < 0:
        return None
    window = md[idx: idx + 120]
    m = re.search(r"(\d[\d,]{3,}(?:\.\d+)?)", window)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None
