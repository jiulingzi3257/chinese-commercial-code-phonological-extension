#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标准中文电码全量校勘工具 v1.2
==============================
基于《标准电码本（修订本）》1983年第3版，对电子化码本进行严格校勘。

检查项：
  1. 数据完整性（解析条数/唯一码/重复码）
  2. 字符分类（CJK基本区/扩展A~H/非汉字）
  3. 汉字层自检（零重复/码位分布/空码位分析）
  4. 特殊字符层自检（U+3000占位符/重复码/分类统计）
  5. 已知示例回归（56字必须全部匹配）
  6. 多源仲裁（ArbitrationEngine，支持ChaseDream/语保/审音等任意CodeSource）

输出：
  - 校勘报告.md
  - 勘误表.csv
  - 清洗后码表.csv
"""

import re
import io
import os
import sys
import csv
import time
import random
from abc import ABC, abstractmethod
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIANMA_HTML = os.path.join(BASE_DIR, "dianma_ben.html")
REPORT_MD = os.path.join(BASE_DIR, "校勘报告.md")
ERRATA_CSV = os.path.join(BASE_DIR, "勘误表.csv")
CLEANED_CSV = os.path.join(BASE_DIR, "清洗后码表.csv")

# 已知示例回归测试（字 -> 期望电码）
# 来源：《观刈麦》36字 + 《关雎》15字 + 加密示例7字 = 58字
REGRESSION = {
    # 《观刈麦》节选
    "观": "6034", "刈": "0435", "麦": "7796", "白": "4101",
    "居": "1446", "易": "2496", "田": "3944", "家": "1367",
    "少": "1421", "闲": "7033", "月": "2588", "五": "0063",
    "人": "0086", "倍": "0223", "忙": "1811", "夜": "1123",
    "来": "0171", "南": "0589", "风": "7364", "起": "6386",
    "小": "1420", "覆": "6010", "陇": "7150", "黄": "7806",
    "妇": "1244", "姑": "1196", "荷": "5440", "箪": "4673",
    "食": "7380", "童": "4547", "稚": "4460", "携": "2377",
    "壶": "1106", "浆": "3364",
    # 《关雎》节选
    "关": "7070", "雎": "7168", "鸠": "7682", "在": "0961",
    "河": "3109", "之": "0037", "洲": "3166", "窈": "4507",
    "窕": "4511", "淑": "3219", "女": "1166", "君": "0689",
    "子": "1311", "好": "1170", "逑": "6633",
    # 加密示例
    "西": "6007", "点": "7820", "军": "6511", "校": "2699",
    "领": "7325", "导": "1418", "魂": "7609",
}

# ChaseDream 仲裁抽样数
CD_SAMPLE_SIZE = 100
CD_TIMEOUT = 15


# ============================================================
# 扩展接口层（第三方数据源接入点）
# ============================================================
# 未来接入语保工程、审音字库等第三方电码/读音数据源时，
# 只需继承 CodeSource 实现 query()，再注册到 ArbitrationEngine 即可。
#
# 接入示例（伪代码）：
#
#   class YuBaoSource(CodeSource):
#       """中国语言资源保护工程（语保）数据源"""
#       @property
#       def name(self): return "语保工程"
#       @property
#       def version(self): return "v1.0"
#       def __init__(self, api_key):
#           self.api_key = api_key
#       def query(self, char):
#           # 调用语保 API，返回该字的标准电码（或 None 表示未收录）
#           ...
#
#   engine = ArbitrationEngine(strategy="unanimous", sample_size=100)
#   engine.register(ChaseDreamSource())
#   engine.register(YuBaoSource(api_key="xxx"))
#   auditor = DianmaAuditor(pairs, arbitration_engine=engine)
#
# 仲裁策略：
#   - "unanimous"：所有源一致才通过，任一不一致即标记勘误（默认，最严格）
#   - "majority"：多数源一致即通过，少数派差异记录为参考
#   - "priority"：按注册顺序优先级，高优先级源为准，低优先级仅作参考


@dataclass
class ArbitrationResult:
    """单字多源仲裁结果"""
    char: str
    local_code: str
    source_results: Dict[str, Optional[str]] = field(default_factory=dict)
    status: str = "pending"  # pass / mismatch / not_found / error
    detail: str = ""

    @property
    def is_consistent(self) -> bool:
        """所有已收录且无错误的源是否与本地码一致。
        与 available_sources 保持同一过滤口径：排除 None 和 ERROR 前缀。"""
        codes = [c for c in self.source_results.values()
                 if c is not None and not str(c).startswith("ERROR")]
        return all(c == self.local_code for c in codes)

    @property
    def available_sources(self) -> int:
        """返回有效结果的源数量（排除未收录和错误）"""
        return sum(1 for c in self.source_results.values()
                   if c is not None and not str(c).startswith("ERROR"))


class CodeSource(ABC):
    """
    电码数据源抽象基类。

    所有第三方数据源（ChaseDream、语保工程、审音字库等）均需继承此类，
    实现 query() 方法。ArbitrationEngine 通过统一接口调度多源仲裁。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称，用于报告和勘误表标识，如 'ChaseDream'、'语保工程'"""
        ...

    @property
    def version(self) -> str:
        """数据源版本信息，默认 'unknown'。建议覆写。"""
        return "unknown"

    @abstractmethod
    def query(self, char: str) -> Optional[str]:
        """
        查询单个汉字的标准电码。

        Args:
            char: 单个汉字字符

        Returns:
            四位电码字符串（如 "6034"）；未收录返回 None；
            查询出错可返回 "ERROR:描述" 前缀字符串，仲裁引擎会自动归类。
        """
        ...

    def batch_query(self, chars: List[str]) -> Dict[str, Optional[str]]:
        """批量查询。默认逐字调用 query()，支持批量 API 的源建议覆写。"""
        return {ch: self.query(ch) for ch in chars}

    def health_check(self) -> bool:
        """数据源可用性检测。默认返回 True，建议覆写为实际探活。"""
        return True


class ArbitrationEngine:
    """
    多源仲裁引擎。

    注册多个 CodeSource 后，对本地码本的抽样字进行多源互证。
    支持三种仲裁策略：unanimous（全一致，默认）、majority（多数表决）、priority（优先级）。
    """

    VALID_STRATEGIES = ("unanimous", "majority", "priority")

    def __init__(self, strategy: str = "unanimous", sample_size: int = 100,
                 request_interval: float = 0.3):
        if strategy not in self.VALID_STRATEGIES:
            raise ValueError(f"不支持的仲裁策略: {strategy}，可选: {self.VALID_STRATEGIES}")
        self.strategy = strategy
        self.sample_size = sample_size
        self.request_interval = request_interval
        self.sources: List[CodeSource] = []

    def register(self, source: CodeSource) -> None:
        """注册一个仲裁数据源。按注册顺序决定 priority 策略下的优先级。"""
        if not isinstance(source, CodeSource):
            raise TypeError(f"注册源必须是 CodeSource 子类，实际: {type(source)}")
        self.sources.append(source)

    def arbitrate(self, char: str, local_code: str) -> ArbitrationResult:
        """对单个字进行多源仲裁，返回 ArbitrationResult。

        状态语义（v1.2 修正）：
          - pass       有效结果按策略判定与本地码一致
          - mismatch   有效结果按策略判定与本地码不一致
          - not_found  所有源均未收录该字（无 ERROR、无命中）
          - error      存在源查询出错，且无任何有效结果可供仲裁
        """
        result = ArbitrationResult(char=char, local_code=local_code)

        if not self.sources:
            result.status = "error"
            result.detail = "未注册任何仲裁数据源"
            return result

        for src in self.sources:
            try:
                code = src.query(char)
            except Exception as e:
                code = f"ERROR:{type(e).__name__}:{e}"
            result.source_results[src.name] = code
            if self.request_interval > 0:
                time.sleep(self.request_interval)

        # 分类：有效结果 / 错误结果 / 未收录(None)
        valid = {name: code for name, code in result.source_results.items()
                 if code is not None and not str(code).startswith("ERROR")}
        errors = {name: code for name, code in result.source_results.items()
                  if code is not None and str(code).startswith("ERROR")}
        n_valid = len(valid)
        n_error = len(errors)
        n_total = len(self.sources)
        error_note = f"；{n_error} 个源查询出错" if n_error else ""

        if n_valid == 0:
            if n_error > 0:
                result.status = "error"
                result.detail = f"无有效结果，{n_error}/{n_total} 个源查询出错: {errors}"
            else:
                result.status = "not_found"
                result.detail = f"所有 {n_total} 个源均未收录该字"
            return result

        # 按策略判定（v1.2：三策略全部实现）
        if self.strategy == "unanimous":
            consistent = all(code == local_code for code in valid.values())
        elif self.strategy == "majority":
            n_same = sum(1 for code in valid.values() if code == local_code)
            consistent = n_same > n_valid / 2
        else:  # priority：按注册顺序第一个有效结果为准
            first_valid = None
            for src in self.sources:
                code = result.source_results.get(src.name)
                if code is not None and not str(code).startswith("ERROR"):
                    first_valid = code
                    break
            consistent = (first_valid == local_code)

        if consistent:
            result.status = "pass"
            result.detail = f"{n_valid}/{n_total} 个源与本地码一致（策略:{self.strategy}）{error_note}"
        else:
            result.status = "mismatch"
            diffs = {name: code for name, code in valid.items() if code != local_code}
            result.detail = f"差异源: {diffs}{error_note}"

        return result

    def arbitrate_sample(self, hanzi_pairs: List[Tuple[str, str]],
                          seed: int = 42) -> List[ArbitrationResult]:
        """对随机抽样的汉字进行批量仲裁（固定种子，可复现）。"""
        basic_hanzi = [(c, ch) for c, ch in hanzi_pairs
                        if char_category(ch) == "CJK基本区"]
        random.seed(seed)
        sample = random.sample(basic_hanzi, min(self.sample_size, len(basic_hanzi)))
        return [self.arbitrate(ch, code) for code, ch in sample]


# ============================================================
# 内置数据源实现
# ============================================================

class ChaseDreamSource(CodeSource):
    """
    ChaseDream 在线中文电码查询数据源。
    基于 1983 第3版 2008 第18次印刷，收录 7077 简体汉字 + 146 特殊字符。
    """

    BASE_URL = "https://apps.chasedream.com/chinese-commercial-code/"

    @property
    def name(self) -> str:
        return "ChaseDream"

    @property
    def version(self) -> str:
        return "1983第3版/2008第18次印刷"

    def __init__(self, timeout: int = CD_TIMEOUT):
        self.timeout = timeout
        self._opener = None

    def _get_opener(self):
        """懒加载 HTTP opener（带 Cookie 管理）"""
        if self._opener is None:
            import urllib.request
            import http.cookiejar
            cj = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
        return self._opener

    def query(self, char: str) -> Optional[str]:
        """查询单个汉字的电码。ASP.NET WebForms POST，需 __VIEWSTATE 三件套。"""
        import urllib.request
        import urllib.parse

        opener = self._get_opener()
        try:
            resp = opener.open(self.BASE_URL, timeout=self.timeout)
            html = resp.read().decode("utf-8", errors="replace")
            vs = re.search(r'name="__VIEWSTATE"[^>]*value="([^"]*)"', html)
            vsg = re.search(r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"', html)
            ev = re.search(r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"', html)
            if not (vs and vsg and ev):
                return None
            data = urllib.parse.urlencode({
                "__VIEWSTATE": vs.group(1),
                "__VIEWSTATEGENERATOR": vsg.group(1),
                "__EVENTVALIDATION": ev.group(1),
                "txtInput": char,
                "btnSearch": "查询",
            }).encode("utf-8")
            resp = opener.open(self.BASE_URL, data=data, timeout=self.timeout)
            html = resp.read().decode("utf-8", errors="replace")
            m = re.search(r'(?s)<table[^>]*id="grvDict".*?</table>', html)
            if not m:
                return None
            rows = re.findall(
                r'(?s)<tr[^>]*>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>',
                m.group(0))
            if not rows:
                return None
            for r_ch, r_code in rows:
                if r_ch == char:
                    return r_code
            return None  # 未命中目标字：不回退首行，避免把无关字电码误配给查询字
        except Exception as e:
            return f"ERROR:{type(e).__name__}:{e}"

    def health_check(self) -> bool:
        """探活：查询'汉'字是否返回 3352"""
        try:
            return self.query("汉") == "3352"
        except Exception:
            return False


# ============================================================
# 字符分类工具
# ============================================================
def char_category(ch):
    """返回字符分类标签"""
    if len(ch) > 1:
        return "多字符组合(标点/符号)"
    cp = ord(ch)
    if 0x4E00 <= cp <= 0x9FFF:
        return "CJK基本区"
    if 0x3400 <= cp <= 0x4DBF:
        return "CJK扩展A"
    if 0x20000 <= cp <= 0x2A6DF:
        return "CJK扩展B"
    if 0x2A700 <= cp <= 0x2B73F:
        return "CJK扩展C"
    if 0x2B740 <= cp <= 0x2B81F:
        return "CJK扩展D"
    if 0x2B820 <= cp <= 0x2CEAF:
        return "CJK扩展E"
    if 0x2CEB0 <= cp <= 0x2EBEF:
        return "CJK扩展F"
    if 0x30000 <= cp <= 0x3134F:
        return "CJK扩展G"
    if 0x31350 <= cp <= 0x323AF:
        return "CJK扩展H"
    if cp == 0x3000:
        return "全角空格(U+3000)"
    if 0x3001 <= cp <= 0x303F:
        return "CJK标点符号"
    if 0xFF00 <= cp <= 0xFFEF:
        return "全角字符"
    if 0x0410 <= cp <= 0x044F:
        return "西里尔字母"
    if 0x3105 <= cp <= 0x312F:
        return "注音符号"
    if 0x3200 <= cp <= 0x32FF:
        return "带圈/括号字符"
    if 0x3300 <= cp <= 0x33FF:
        return "单位/月份符号"
    if 0x2150 <= cp <= 0x218F:
        return "数字形式(罗马/分数)"
    if 0x2018 <= cp <= 0x201F:
        return "引号"
    if 0x2010 <= cp <= 0x2027:
        return "破折/省略"
    if 0x00B7 == cp or 0x00D7 == cp or 0x00F7 == cp or 0x03A9 == cp:
        return "数学/特殊符号"
    return f"其他(U+{cp:04X})"


def is_cjk_han(ch):
    """是否为CJK汉字（含扩展区）。区间与 char_category 保持一致。"""
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or        # CJK基本区
            0x3400 <= cp <= 0x4DBF or         # CJK扩展A
            0x20000 <= cp <= 0x2A6DF or       # CJK扩展B
            0x2A700 <= cp <= 0x2B73F or       # CJK扩展C
            0x2B740 <= cp <= 0x2B81F or       # CJK扩展D
            0x2B820 <= cp <= 0x2CEAF or       # CJK扩展E
            0x2CEB0 <= cp <= 0x2EBEF or       # CJK扩展F
            0x30000 <= cp <= 0x3134F or       # CJK扩展G
            0x31350 <= cp <= 0x323AF)         # CJK扩展H


# ============================================================
# 数据加载
# ============================================================
def load_dianma(path):
    """解析本地电码本HTML，返回 [(code, char), ...]"""
    with io.open(path, encoding="utf-8") as f:
        html = f.read()
    pairs = re.findall(r'(\d{4})<br/>\s*<span[^>]*>([^<]+)</span>', html)
    return pairs


# ============================================================
# 校勘引擎
# ============================================================
class DianmaAuditor:
    def __init__(self, pairs, arbitration_engine=None):
        """
        Args:
            pairs: [(code, char), ...] 码字对列表
            arbitration_engine: ArbitrationEngine 实例，用于多源仲裁。
                                为 None 时跳过仲裁检查。可注册 ChaseDreamSource、
                                语保工程 Source、审音字库 Source 等任意 CodeSource 实现。
        """
        self.pairs = pairs  # [(code, char), ...]
        self.arbitration_engine = arbitration_engine
        self.code_to_chars = defaultdict(list)  # code -> [chars]
        self.char_to_codes = defaultdict(list)  # char -> [codes]
        for code, ch in pairs:
            self.code_to_chars[code].append(ch)
            self.char_to_codes[ch].append(code)

        self.errata = []  # 勘误条目
        self.stats = {}   # 统计数据

    def add_erratum(self, code, char, err_type, severity, description, suggestion):
        """添加一条勘误"""
        self.errata.append({
            "码位": code,
            "字符": char,
            "问题类型": err_type,
            "严重度": severity,  # 高/中/低
            "问题描述": description,
            "建议处置": suggestion,
        })

    # ---- 检查1：数据完整性 ----
    def check_integrity(self):
        total = len(self.pairs)
        unique_codes = len(self.code_to_chars)
        duplicate_codes = {c: cs for c, cs in self.code_to_chars.items() if len(cs) > 1}
        duplicate_chars = {ch: cs for ch, cs in self.char_to_codes.items() if len(cs) > 1}

        self.stats["总条数"] = total
        self.stats["唯一码位数"] = unique_codes
        self.stats["重复码位数"] = len(duplicate_codes)
        self.stats["重复字符数"] = len(duplicate_chars)

        if duplicate_codes:
            for code, chars in duplicate_codes.items():
                self.add_erratum(
                    code, "/".join(chars), "重复码",
                    "高" if any(is_cjk_han(c) for c in chars) else "中",
                    f"码位 {code} 对应多个字符：{chars}",
                    "核查原书，判定是否为同码多字或电子化错误"
                )

        if duplicate_chars:
            for ch, codes in duplicate_chars.items():
                if ch == '\u3000':
                    continue  # 全角空格占位符由 check_special_layer 统一标注，避免重复勘误
                self.add_erratum(
                    "/".join(codes), ch, "一字多码",
                    "高" if is_cjk_han(ch) else "中",
                    f"字符 '{ch}' 对应多个码位：{codes}",
                    "核查原书，判定是否为同字多码或电子化重复"
                )

    # ---- 检查2：字符分类 ----
    def check_classification(self):
        categories = Counter()
        hanzi_pairs = []
        special_pairs = []
        for code, ch in self.pairs:
            cat = char_category(ch)
            categories[cat] += 1
            if is_cjk_han(ch):
                hanzi_pairs.append((code, ch))
            else:
                special_pairs.append((code, ch))

        self.stats["汉字数(CJK含扩展)"] = len(hanzi_pairs)
        self.stats["特殊字符数"] = len(special_pairs)
        self.stats["字符分类"] = dict(categories.most_common())
        self.hanzi_pairs = hanzi_pairs
        self.special_pairs = special_pairs

        # 扩展区汉字应标注（非基本区，需确认原书是否收录）
        for code, ch in hanzi_pairs:
            cat = char_category(ch)
            if cat != "CJK基本区":
                self.add_erratum(
                    code, ch, "扩展区汉字",
                    "中",
                    f"字符 '{ch}'({cat}) 不在CJK基本区，原书是否收录需确认",
                    "核查原书，确认是否为原书收录或电子化增补"
                )

    # ---- 检查3：汉字层自检 ----
    def check_hanzi_layer(self):
        hanzi_codes = [c for c, ch in self.hanzi_pairs]

        # 汉字层零重复（Counter 单次遍历，避免 O(n²) list.count）
        hanzi_code_counter = Counter(hanzi_codes)
        hanzi_duplicates = [c for c, n in hanzi_code_counter.items() if n > 1]
        self.stats["汉字层重复码"] = len(hanzi_duplicates)

        # 码位分布（按千位分段）
        segments = Counter()
        for code in hanzi_codes:
            seg = code[0] + "xxx"
            segments[seg] += 1
        self.stats["汉字码位分布"] = dict(sorted(segments.items()))

        # 空码位分析（0001-9999）
        all_codes = set(f"{i:04d}" for i in range(1, 10000))
        used_codes = set(self.code_to_chars.keys())
        empty_codes = sorted(all_codes - used_codes)
        self.stats["空码位数"] = len(empty_codes)
        self.stats["码位占用率"] = f"{len(used_codes)/9999*100:.1f}%"

        # 空码段（连续空码>=10）
        empty_segments = []
        start = None
        prev = None
        for code in empty_codes:
            n = int(code)
            if start is None:
                start = n
                prev = n
            elif n == prev + 1:
                prev = n
            else:
                if prev - start + 1 >= 10:
                    empty_segments.append((f"{start:04d}", f"{prev:04d}", prev - start + 1))
                start = n
                prev = n
        if start is not None and prev - start + 1 >= 10:
            empty_segments.append((f"{start:04d}", f"{prev:04d}", prev - start + 1))
        self.stats["连续空码段(>=10)"] = empty_segments

    # ---- 检查4：特殊字符层自检 ----
    def check_special_layer(self):
        # U+3000 全角空格占位符
        u3000_list = [(c, ch) for c, ch in self.special_pairs if ch == '\u3000']
        self.stats["U+3000占位符数"] = len(u3000_list)
        for code, ch in u3000_list:
            self.add_erratum(
                code, "U+3000", "全角空格占位符",
                "中",
                f"码位 {code} 为全角空格(U+3000)，疑似原书空码位或电子化填充",
                "标记为占位符，不计入有效字符；核查原书确认是否为预留位"
            )

        # 特殊字符层重复码
        special_code_count = Counter(c for c, ch in self.special_pairs)
        special_duplicates = {c: n for c, n in special_code_count.items() if n > 1}
        self.stats["特殊字符层重复码"] = len(special_duplicates)
        for code, count in special_duplicates.items():
            chars = [ch for c, ch in self.special_pairs if c == code]
            self.add_erratum(
                code, "/".join(chars), "特殊字符重复码",
                "中",
                f"码位 {code} 在特殊字符层重复 {count} 次：{chars}",
                "核查原书，判定是否为原书同码或电子化重复"
            )

        # 特殊字符分类统计
        special_cats = Counter()
        for code, ch in self.special_pairs:
            special_cats[char_category(ch)] += 1
        self.stats["特殊字符分类"] = dict(special_cats.most_common())

    # ---- 检查5：已知示例回归 ----
    def check_regression(self):
        passed = 0
        failed = []
        for ch, expected in REGRESSION.items():
            actual = self.char_to_codes.get(ch, [])
            if expected in actual:
                passed += 1
            else:
                failed.append((ch, expected, actual))

        self.stats["回归测试通过"] = passed
        self.stats["回归测试失败"] = len(failed)
        self.stats["回归测试总数"] = len(REGRESSION)

        for ch, expected, actual in failed:
            self.add_erratum(
                expected, ch, "回归测试失败",
                "高",
                f"已知示例字 '{ch}' 期望电码 {expected}，实际为 {actual}",
                "核查该字电码，修正示例或码本"
            )

    # ---- 检查6：多源仲裁（通过 ArbitrationEngine，支持 ChaseDream/语保/审音等多源） ----
    def check_multi_source_arbitration(self):
        """通过仲裁引擎对抽样汉字进行多源互证。若未注册仲裁源则跳过。"""
        engine = self.arbitration_engine
        if engine is None or not engine.sources:
            self.stats["多源仲裁"] = "跳过（未注册仲裁数据源）"
            return

        source_names = [s.name for s in engine.sources]
        self.stats["仲裁数据源"] = source_names
        self.stats["仲裁策略"] = engine.strategy
        self.stats["仲裁抽样数"] = engine.sample_size

        results = engine.arbitrate_sample(self.hanzi_pairs)

        pass_count = sum(1 for r in results if r.status == "pass")
        mismatch_count = sum(1 for r in results if r.status == "mismatch")
        notfound_count = sum(1 for r in results if r.status == "not_found")
        error_count = sum(1 for r in results if r.status == "error")

        self.stats["仲裁一致"] = pass_count
        self.stats["仲裁不一致"] = mismatch_count
        self.stats["仲裁未收录"] = notfound_count
        self.stats["仲裁错误"] = error_count

        # 不一致的字标记为勘误（高严重度）
        for r in results:
            if r.status == "mismatch":
                diff_desc = "; ".join(
                    f"{name}={code}" for name, code in r.source_results.items()
                    if code is not None and not str(code).startswith("ERROR")
                    and code != r.local_code
                )
                self.add_erratum(
                    r.local_code, r.char, "多源仲裁不一致",
                    "高",
                    f"本地码={r.local_code}，差异源：{diff_desc}",
                    "核查原书，以原书为准修正；标注差异来源"
                )

    # 向后兼容：旧方法名映射到新方法
    def check_chasedream_arbitration(self, sample_size=CD_SAMPLE_SIZE):
        """[已弃用] 请使用 check_multi_source_arbitration()。保留此方法仅为向后兼容。"""
        self.check_multi_source_arbitration()

    # ---- 运行全部检查 ----
    def run_all(self, cd_arbitration=True):
        print("[1/6] 数据完整性检查...")
        self.check_integrity()
        print("[2/6] 字符分类...")
        self.check_classification()
        print("[3/6] 汉字层自检...")
        self.check_hanzi_layer()
        print("[4/6] 特殊字符层自检...")
        self.check_special_layer()
        print("[5/6] 已知示例回归...")
        self.check_regression()
        if cd_arbitration and self.arbitration_engine and self.arbitration_engine.sources:
            src_names = ", ".join(s.name for s in self.arbitration_engine.sources)
            print(f"[6/6] 多源仲裁（{src_names}，抽样{self.arbitration_engine.sample_size}字）...")
            self.check_multi_source_arbitration()
        else:
            reason = "未注册仲裁源" if not (self.arbitration_engine and self.arbitration_engine.sources) else "用户跳过"
            print(f"[6/6] 多源仲裁（跳过：{reason}）")
            self.stats["多源仲裁"] = f"跳过（{reason}）"

    # ---- 输出报告 ----
    def write_report(self):
        lines = []
        lines.append("# 标准中文电码全量校勘报告")
        lines.append("")
        lines.append(f"> 校勘时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> 数据来源：《标准电码本（修订本）》1983年第3版 电子化校勘版")
        if self.arbitration_engine and self.arbitration_engine.sources:
            src_desc = "、".join(f"{s.name}({s.version})" for s in self.arbitration_engine.sources)
            lines.append(f"> 多源仲裁：{src_desc}")
        else:
            lines.append("> 多源仲裁：未启用")
        lines.append("")

        # 一、总体结论
        lines.append("## 一、总体结论")
        lines.append("")
        total = self.stats.get("总条数", 0)
        hanzi = self.stats.get("汉字数(CJK含扩展)", 0)
        special = self.stats.get("特殊字符数", 0)
        err_count = len(self.errata)
        high_err = sum(1 for e in self.errata if e["严重度"] == "高")
        reg_pass = self.stats.get("回归测试通过", 0)
        reg_total = self.stats.get("回归测试总数", 0)

        lines.append(f"- 收录总条数：**{total}**（汉字 {hanzi} + 特殊字符 {special}）")
        lines.append(f"- 码位唯一：**{self.stats.get('唯一码位数', 0)}** 个唯一码位，重复码位 **{self.stats.get('重复码位数', 0)}** 个")
        lines.append(f"- 码位占用率：**{self.stats.get('码位占用率', 'N/A')}**（空码位 {self.stats.get('空码位数', 0)} 个）")
        lines.append(f"- 已知示例回归：**{reg_pass}/{reg_total}** 通过")
        lines.append(f"- 勘误条目：**{err_count}** 条（高严重度 {high_err} 条）")
        lines.append("")

        # 二、字符分类
        lines.append("## 二、字符分类统计")
        lines.append("")
        lines.append("| 分类 | 数量 |")
        lines.append("|---|---|")
        for cat, count in self.stats.get("字符分类", {}).items():
            lines.append(f"| {cat} | {count} |")
        lines.append("")

        # 三、汉字层
        lines.append("## 三、汉字层自检")
        lines.append("")
        lines.append(f"- 汉字层重复码：**{self.stats.get('汉字层重复码', 0)}** 个")
        lines.append(f"- 汉字码位分布：")
        for seg, count in self.stats.get("汉字码位分布", {}).items():
            lines.append(f"  - {seg}：{count} 字")
        lines.append(f"- 连续空码段（≥10）：**{len(self.stats.get('连续空码段(>=10)', []))}** 段")
        for start, end, length in self.stats.get("连续空码段(>=10)", [])[:10]:
            lines.append(f"  - {start}–{end}（{length} 个）")
        lines.append("")

        # 四、特殊字符层
        lines.append("## 四、特殊字符层自检")
        lines.append("")
        lines.append(f"- U+3000 全角空格占位符：**{self.stats.get('U+3000占位符数', 0)}** 个")
        lines.append(f"- 特殊字符层重复码：**{self.stats.get('特殊字符层重复码', 0)}** 个")
        lines.append(f"- 特殊字符分类：")
        for cat, count in self.stats.get("特殊字符分类", {}).items():
            lines.append(f"  - {cat}：{count} 个")
        lines.append("")

        # 五、勘误表
        lines.append("## 五、勘误条目汇总")
        lines.append("")
        if self.errata:
            lines.append("| 序号 | 码位 | 字符 | 问题类型 | 严重度 | 问题描述 | 建议处置 |")
            lines.append("|---|---|---|---|---|---|---|")
            for i, e in enumerate(self.errata, 1):
                lines.append(f"| {i} | {e['码位']} | {e['字符']} | {e['问题类型']} | {e['严重度']} | {e['问题描述']} | {e['建议处置']} |")
        else:
            lines.append("无勘误条目。")
        lines.append("")

        # 六、多源仲裁
        if "仲裁抽样数" in self.stats:
            lines.append("## 六、多源仲裁")
            lines.append("")
            lines.append(f"- 仲裁数据源：{', '.join(self.stats.get('仲裁数据源', []))}")
            lines.append(f"- 仲裁策略：{self.stats.get('仲裁策略', 'N/A')}")
            lines.append(f"- 抽样数：{self.stats['仲裁抽样数']}")
            lines.append(f"- 一致：{self.stats['仲裁一致']}")
            lines.append(f"- 不一致：{self.stats['仲裁不一致']}")
            lines.append(f"- 未收录：{self.stats['仲裁未收录']}")
            lines.append(f"- 查询错误：{self.stats['仲裁错误']}")
            lines.append("")
        elif "多源仲裁" in self.stats:
            lines.append("## 六、多源仲裁")
            lines.append("")
            lines.append(f"- 状态：{self.stats['多源仲裁']}")
            lines.append("")

        with io.open(REPORT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"报告已写入：{REPORT_MD}")

    def write_errata_csv(self):
        with io.open(ERRATA_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["码位", "字符", "问题类型", "严重度", "问题描述", "建议处置"])
            writer.writeheader()
            for e in self.errata:
                writer.writerow(e)
        print(f"勘误表已写入：{ERRATA_CSV}（{len(self.errata)} 条）")

    def write_cleaned_csv(self):
        """输出清洗后码表（排除U+3000占位符，标记问题项）"""
        with io.open(CLEANED_CSV, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["电码", "字符", "字符分类", "是否汉字", "校勘标记"])
            # 收集所有需标记的码位：一字多码的码位字段为 "0001/0002" 形式，需拆分
            errata_codes = set()
            for e in self.errata:
                if e["问题类型"] == "回归测试失败":
                    continue
                for c in str(e["码位"]).split("/"):
                    errata_codes.add(c)
            for code, ch in sorted(self.pairs):
                cat = char_category(ch)
                is_han = "是" if is_cjk_han(ch) else "否"
                flag = ""
                if ch == '\u3000':
                    continue  # 不写入清洗后码表
                if code in errata_codes:
                    flag = "待核查"
                writer.writerow([code, ch, cat, is_han, flag])
        print(f"清洗后码表已写入：{CLEANED_CSV}")


# ============================================================
# 主入口
# ============================================================
def main():
    print("=" * 60)
    print("标准中文电码全量校勘工具 v1.2")
    print("=" * 60)
    print()

    if not os.path.exists(DIANMA_HTML):
        print(f"错误：找不到码本文件 {DIANMA_HTML}")
        sys.exit(1)

    # 加载数据
    print(f"加载码本：{DIANMA_HTML}")
    pairs = load_dianma(DIANMA_HTML)
    print(f"解析到 {len(pairs)} 条码字对")
    if len(pairs) == 0:
        print("错误：码本解析结果为 0 条，请检查 dianma_ben.html 格式是否正确")
        sys.exit(1)
    print()

    # 构建仲裁引擎（默认注册 ChaseDream 作为第一验证源）
    # 未来接入语保工程、审音字库等时，只需在此处 register 对应的 CodeSource 实现
    cd_arbitration = "--no-cd" not in sys.argv
    arbitration_engine = None
    if cd_arbitration:
        arbitration_engine = ArbitrationEngine(
            strategy="unanimous",
            sample_size=CD_SAMPLE_SIZE,
            request_interval=0.3
        )
        arbitration_engine.register(ChaseDreamSource(timeout=CD_TIMEOUT))
        # 示例：接入语保工程（需自行实现 YuBaoSource 并提供 API Key）
        # arbitration_engine.register(YuBaoSource(api_key=os.getenv("YUBAO_API_KEY")))
        # 示例：接入审音字库
        # arbitration_engine.register(ShenYinSource(api_key=os.getenv("SHENYIN_API_KEY")))

    # 运行校勘
    auditor = DianmaAuditor(pairs, arbitration_engine=arbitration_engine)
    auditor.run_all(cd_arbitration=cd_arbitration)
    print()

    # 输出
    print("=" * 60)
    print("校勘完成，输出文件：")
    auditor.write_report()
    auditor.write_errata_csv()
    auditor.write_cleaned_csv()
    print()
    print(f"  勘误条目：{len(auditor.errata)} 条")
    print(f"  回归测试：{auditor.stats.get('回归测试通过', 0)}/{auditor.stats.get('回归测试总数', 0)} 通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
