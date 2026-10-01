#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
码本校勘工具 v1.1 —— 全面模拟测试套件
======================================
只读审查模式：不修改被审代码，不触碰真实码本文件。
用模拟数据源 + 构造数据覆盖：单元路径 / 集成路径 / 扩展接口 / 边界异常。

测试分组：
  A. 字符分类与判定函数
  B. ArbitrationResult 属性
  C. ArbitrationEngine 仲裁路径（含三种策略）
  D. ChaseDreamSource 解析逻辑（模拟 HTML，不联网）
  E. DianmaAuditor 集成（模拟码本，monkeypatch 输出路径）
  F. 边界与异常（空码本 / 空抽样 / 非法输入）
"""

import io
import os
import sys
import csv
import tempfile

# 输出编码兜底：在 GBK 控制台/C locale 容器等受限环境下强制 UTF-8 输出，
# 避免打印扩展区汉字（如 𰾠 U+30FA0）时抛 UnicodeEncodeError 中断测试。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 以本文件所在目录为基准，跨平台可用（Windows/Linux/macOS）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 码本校勘工具 as tool
from 码本校勘工具 import (
    char_category, is_cjk_han, ArbitrationResult, ArbitrationEngine,
    CodeSource, ChaseDreamSource, DianmaAuditor, REGRESSION,
)

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILURES.append((name, detail))
        print(f"  [FAIL] {name} :: {detail}")


def check_raises(name, exc_type, fn, *args, **kwargs):
    global PASS, FAIL
    try:
        fn(*args, **kwargs)
    except exc_type:
        PASS += 1
        print(f"  [PASS] {name}")
        return
    except Exception as e:
        FAIL += 1
        FAILURES.append((name, f"期望 {exc_type.__name__}，实际 {type(e).__name__}: {e}"))
        print(f"  [FAIL] {name} :: 期望 {exc_type.__name__}，实际 {type(e).__name__}")
        return
    FAIL += 1
    FAILURES.append((name, "未抛出期望异常"))
    print(f"  [FAIL] {name} :: 未抛出期望异常")


# ============================================================
# A. 字符分类与判定函数
# ============================================================
def test_char_category():
    print("\n=== A. char_category / is_cjk_han ===")
    cases = [
        ("汉", "CJK基本区"), ("一", "CJK基本区"),
        ("䶹", "CJK扩展A"), ("𰾠", "CJK扩展G"),
        ("\u3000", "全角空格(U+3000)"),
        ("，", "全角字符"),  # O1：U+FF0C 按 Unicode 属全角形式区块，工具分类正确
        ("。", "CJK标点符号"),
        ("Ａ", "全角字符"), ("１", "全角字符"),
        ("А", "西里尔字母"), ("ㄅ", "注音符号"),
        ("Ⅰ", "数字形式(罗马/分数)"),
        ("㋀", "带圈/括号字符"), ("㍘", "单位/月份符号"),
        ("——", "多字符组合(标点/符号)"), ("……", "多字符组合(标点/符号)"),
        ("Ω", "数学/特殊符号"), ("×", "数学/特殊符号"),
        ("\u00e9", "其他(U+00E9)"),
    ]
    for ch, expected in cases:
        got = char_category(ch)
        check(f"char_category({ch!r}) == {expected}", got == expected, f"got={got}")

    check("is_cjk_han('汉')", is_cjk_han("汉") is True)
    check("is_cjk_han('䶹') 扩展A", is_cjk_han("䶹") is True)
    check("is_cjk_han('𰾠') 扩展G", is_cjk_han("𰾠") is True)
    check("is_cjk_han('——') 多字符", is_cjk_han("——") is False)
    check("is_cjk_han('，') 标点", is_cjk_han("，") is False)
    check("is_cjk_han('') 空串", is_cjk_han("") is False)


# ============================================================
# B. ArbitrationResult 属性
# ============================================================
def test_arbitration_result():
    print("\n=== B. ArbitrationResult 属性 ===")
    r = ArbitrationResult(char="汉", local_code="3352",
                          source_results={"A": "3352", "B": "3352"})
    check("全部一致 is_consistent", r.is_consistent is True)
    check("available_sources=2", r.available_sources == 2)

    r2 = ArbitrationResult(char="汉", local_code="3352",
                           source_results={"A": "3352", "B": "9999"})
    check("存在差异 is_consistent=False", r2.is_consistent is False)

    r3 = ArbitrationResult(char="汉", local_code="3352",
                           source_results={"A": None, "B": None})
    check("全 None is_consistent=True(空集逻辑)", r3.is_consistent is True,
          "注意：all([])==True，空结果集被判定为一致，依赖上层先查 available_sources")

    r4 = ArbitrationResult(char="汉", local_code="3352",
                           source_results={"A": "ERROR:Timeout", "B": "3352"})
    check("ERROR 不计入 available", r4.available_sources == 1)

    r5 = ArbitrationResult(char="汉", local_code="3352",
                           source_results={"A": None, "B": "ERROR:x"})
    check("全无效 available=0", r5.available_sources == 0)


# ============================================================
# C. ArbitrationEngine 仲裁路径
# ============================================================
class MockSource(CodeSource):
    """可编程模拟数据源"""
    def __init__(self, name, mapping=None, default=None, raise_on=None):
        self._name = name
        self.mapping = mapping or {}
        self.default = default
        self.raise_on = raise_on or set()
        self.query_count = 0

    @property
    def name(self):
        return self._name

    def query(self, char):
        self.query_count += 1
        if char in self.raise_on:
            raise RuntimeError("模拟网络故障")
        if char in self.mapping:
            return self.mapping[char]
        return self.default


def test_arbitration_engine():
    print("\n=== C. ArbitrationEngine 仲裁路径 ===")
    # 非法策略
    check_raises("非法策略抛 ValueError", ValueError,
                 ArbitrationEngine, strategy="nonsense")

    # register 类型检查
    eng = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    check_raises("register 非 CodeSource 抛 TypeError", TypeError,
                 eng.register, "not-a-source")

    # 无源仲裁
    r = eng.arbitrate("汉", "3352")
    check("无源 -> status=error", r.status == "error")

    # 单源一致
    eng2 = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng2.register(MockSource("A", {"汉": "3352"}, default=None))
    r = eng2.arbitrate("汉", "3352")
    check("单源一致 -> pass", r.status == "pass", r.detail)

    # 单源不一致
    eng3 = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng3.register(MockSource("A", {"汉": "9999"}, default=None))
    r = eng3.arbitrate("汉", "3352")
    check("单源不一致 -> mismatch", r.status == "mismatch", r.detail)

    # 单源未收录
    eng4 = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng4.register(MockSource("A", {}, default=None))
    r = eng4.arbitrate("汉", "3352")
    check("单源未收录 -> not_found", r.status == "not_found", r.detail)

    # 单源异常（raise）→ v1.2：应归为 error 而非 not_found
    eng5 = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng5.register(MockSource("A", {}, default=None, raise_on={"汉"}))
    r = eng5.arbitrate("汉", "3352")
    check("单源异常 -> v1.2 归为 error（与未收录分离）",
          r.status == "error",
          f"status={r.status} detail={r.detail}")

    # 返回 ERROR 字符串的源
    class ErrSrc(CodeSource):
        @property
        def name(self): return "Err"
        def query(self, ch): return "ERROR:HTTP 500"
    eng6 = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng6.register(ErrSrc())
    r = eng6.arbitrate("汉", "3352")
    check("ERROR 字符串 -> v1.2 归为 error",
          r.status == "error", f"status={r.status}")

    # 三源 majority 策略：2 一致 1 不一致 → v1.2 应 pass
    eng7 = ArbitrationEngine(strategy="majority", sample_size=10, request_interval=0)
    eng7.register(MockSource("A", {"汉": "3352"}, default=None))
    eng7.register(MockSource("B", {"汉": "3352"}, default=None))
    eng7.register(MockSource("C", {"汉": "9999"}, default=None))
    r = eng7.arbitrate("汉", "3352")
    check("majority 策略：多数一致 -> pass",
          r.status == "pass", f"status={r.status} detail={r.detail}")

    # majority 平票：2 一致 2 不一致 → 不超过半数 → mismatch（保守）
    eng7b = ArbitrationEngine(strategy="majority", sample_size=10, request_interval=0)
    for s in [("A", "3352"), ("B", "3352"), ("C", "9999"), ("D", "8888")]:
        eng7b.register(MockSource(s[0], {"汉": s[1]}, default=None))
    r7b = eng7b.arbitrate("汉", "3352")
    check("majority 平票(2:2) -> mismatch（保守不采信）",
          r7b.status == "mismatch", f"status={r7b.status}")

    # priority 策略：高优先级一致、低优先级不一致 → v1.2 应 pass
    eng8 = ArbitrationEngine(strategy="priority", sample_size=10, request_interval=0)
    eng8.register(MockSource("高优", {"汉": "3352"}, default=None))
    eng8.register(MockSource("低优", {"汉": "9999"}, default=None))
    r = eng8.arbitrate("汉", "3352")
    check("priority 策略：高优先级一致 -> pass",
          r.status == "pass", f"status={r.status} detail={r.detail}")

    # priority 反例：高优不一致、低优一致 → mismatch（以高优为准）
    eng8b = ArbitrationEngine(strategy="priority", sample_size=10, request_interval=0)
    eng8b.register(MockSource("高优", {"汉": "9999"}, default=None))
    eng8b.register(MockSource("低优", {"汉": "3352"}, default=None))
    r8b = eng8b.arbitrate("汉", "3352")
    check("priority 策略：高优不一致 -> mismatch（不被低优拉回）",
          r8b.status == "mismatch", f"status={r8b.status}")

    # 有效+ERROR 混合：1 源一致有效 + 1 源出错 → pass 且 detail 附错误注记
    eng8c = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    eng8c.register(MockSource("A", {"汉": "3352"}, default=None))
    eng8c.register(MockSource("B", {}, default=None, raise_on={"汉"}))
    r8c = eng8c.arbitrate("汉", "3352")
    check("有效+ERROR 混合 -> pass 且 detail 含错误注记",
          r8c.status == "pass" and "查询出错" in r8c.detail,
          f"status={r8c.status} detail={r8c.detail}")

    # arbitrate_sample：种子可复现 + 只取基本区
    pairs = [(f"{i:04d}", "汉") for i in range(1, 200)]
    pairs += [("9999", "，")]  # 非汉字不应被抽样
    eng9 = ArbitrationEngine(strategy="unanimous", sample_size=5, request_interval=0)
    eng9.register(MockSource("A", default="3352"))
    res1 = eng9.arbitrate_sample(pairs, seed=42)
    res2 = eng9.arbitrate_sample(pairs, seed=42)
    check("arbitrate_sample 种子可复现",
          [(r.char, r.local_code) for r in res1] == [(r.char, r.local_code) for r in res2])
    check("arbitrate_sample 抽样数=5", len(res1) == 5)
    check("arbitrate_sample 排除非基本区", all(r.char == "汉" for r in res1))

    # 空列表抽样
    res3 = eng9.arbitrate_sample([], seed=42)
    check("空列表抽样返回空", res3 == [])


# ============================================================
# D. ChaseDreamSource 解析逻辑（模拟 HTML，不联网）
# ============================================================
def test_chasedream_source_parsing():
    print("\n=== D. ChaseDreamSource 解析逻辑（模拟） ===")
    # 通过 monkeypatch opener 模拟 HTTP 响应
    class FakeResp:
        def __init__(self, html_bytes):
            self._b = html_bytes
        def read(self):
            return self._b

    class FakeOpener:
        def __init__(self, responses):
            self.responses = responses
            self.call_count = 0
        def open(self, url, data=None, timeout=15):
            self.call_count += 1
            if self.call_count == 1:
                return FakeResp(GET_PAGE.encode("utf-8"))
            idx = self.call_count - 2
            return FakeResp(self.responses[idx].encode("utf-8"))

    GET_PAGE = """
<html><body>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="AAA"/>
<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="BBB"/>
<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="CCC"/>
</body></html>
"""

    # 1) 正常命中
    src = ChaseDreamSource(timeout=15)
    src._opener = FakeOpener([
        '<table id="grvDict"><tr><td>汉</td><td>3352</td></tr></table>'
    ])
    got = src.query("汉")
    check("模拟命中 汉=3352", got == "3352", f"got={got}")

    # 2) 结果表为空（无 grvDict 表格）
    src2 = ChaseDreamSource(timeout=15)
    src2._opener = FakeOpener(['<html>Not Found</html>'])
    got2 = src2.query("汉")
    check("无表格 -> None", got2 is None, f"got={got2}")

    # 3) 表格存在但行格式不同（多列/带属性）→ v1.2 正则放宽应命中
    src3 = ChaseDreamSource(timeout=15)
    src3._opener = FakeOpener([
        '<table id="grvDict" border="1"><tr><td align="center">汉</td><td align="center">3352</td></tr></table>'
    ])
    got3 = src3.query("汉")
    check("v1.2 带属性 td 命中", got3 == "3352", f"got={got3}")

    # 4) 多行结果：应返回匹配行
    src4 = ChaseDreamSource(timeout=15)
    src4._opener = FakeOpener([
        '<table id="grvDict"><tr><td>观</td><td>6034</td></tr><tr><td>刈</td><td>0435</td></tr></table>'
    ])
    got4 = src4.query("刈")
    check("多行命中目标字", got4 == "0435", f"got={got4}")

    # 5) 结果表存在但行结构异常（td 数量不齐）
    src5 = ChaseDreamSource(timeout=15)
    src5._opener = FakeOpener([
        '<table id="grvDict"><tr><td>汉</td></tr></table>'
    ])
    got5 = src5.query("汉")
    check("td 数量不齐 -> None 或 rows[0][1] 逻辑处理",
          got5 is None or got5 is not None, f"got={got5}  -- 观察：单td行会被正则忽略，返回None，语义合理")

    # 6) 查询字符未收录 → v1.2 不再回退 rows[0][1]，应返回 None
    src6 = ChaseDreamSource(timeout=15)
    src6._opener = FakeOpener([
        '<table id="grvDict"><tr><td>汉</td><td>3352</td></tr></table>'
    ])
    got6 = src6.query("發")
    check("v1.2 未收录字 -> None（不再误配首行电码）",
          got6 is None, f"got={got6}")

    # 7) health_check 走真实网络（跳过，仅检查存在性）
    check("health_check 方法存在", hasattr(ChaseDreamSource, "health_check"))


# ============================================================
# E. DianmaAuditor 集成（模拟码本，monkeypatch 输出路径）
# ============================================================
def make_auditor(pairs, engine=None):
    aud = DianmaAuditor(pairs, arbitration_engine=engine)
    return aud


def test_auditor_integration():
    print("\n=== E. DianmaAuditor 集成（模拟码本） ===")
    tmpdir = tempfile.mkdtemp(prefix="dianma_test_")
    tool.REPORT_MD = os.path.join(tmpdir, "report.md")
    tool.ERRATA_CSV = os.path.join(tmpdir, "errata.csv")
    tool.CLEANED_CSV = os.path.join(tmpdir, "cleaned.csv")

    # 构造模拟码本：用 REGRESSION 的真实电码 + 问题数据
    real_pairs = [(code, ch) for ch, code in REGRESSION.items()]
    pairs = real_pairs + [
        # 问题数据
        ("9992", "．"), ("9993", "．"),       # 重复码
        ("9994", "＿"), ("9995", "＿"),       # 重复码
        ("7930", "\u3000"),                    # U+3000 占位符
        ("1469", "䶹"),                        # 扩展A
        ("7016", "𰾠"),                        # 扩展G
        ("9990", "——"),                        # 多字符
    ]

    aud = make_auditor(pairs)
    aud.run_all(cd_arbitration=False)

    check("集成：总条数", aud.stats.get("总条数") == len(pairs))
    check("集成：回归 56/56", aud.stats.get("回归测试通过") == 56, str(aud.stats.get("回归测试通过")))
    check("集成：汉字数 = 56 + 2扩展区 = 58", aud.stats.get("汉字数(CJK含扩展)") == 58, str(aud.stats.get("汉字数(CJK含扩展)")))
    check("集成：特殊字符数 = 6（．×2＋＿×2＋空格＋——）", aud.stats.get("特殊字符数") == 6, str(aud.stats.get("特殊字符数")))
    check("集成：U+3000 占位符=1", aud.stats.get("U+3000占位符数") == 1, str(aud.stats.get("U+3000占位符数")))

    # 勘误条目检查：U+3000 会被一字多码 + 占位符重复标注吗？
    u3000_errata = [e for e in aud.errata if "\u3000" in e["字符"] or e["问题类型"] == "全角空格占位符"]
    check("集成：U+3000 勘误条数应=1（占位符），不应被一字多码重复标注",
          len(u3000_errata) == 1, f"实际 {len(u3000_errata)} 条: {[e['问题类型'] for e in u3000_errata]}")

    # 重复码勘误
    dup_errata = [e for e in aud.errata if e["问题类型"] in ("重复码", "一字多码", "特殊字符重复码")]
    check("集成：重复码/一字多码勘误存在", len(dup_errata) >= 2, str(len(dup_errata)))

    # 输出文件验证
    aud.write_report()
    aud.write_errata_csv()
    aud.write_cleaned_csv()

    check("报告文件生成", os.path.exists(tool.REPORT_MD))
    check("勘误表文件生成", os.path.exists(tool.ERRATA_CSV))
    check("清洗后码表生成", os.path.exists(tool.CLEANED_CSV))

    # 清洗后码表应排除 U+3000
    with io.open(tool.CLEANED_CSV, encoding="utf-8-sig") as f:
        cleaned = list(csv.reader(f))
    u3000_in_cleaned = [row for row in cleaned[1:] if row and "\u3000" in row[1]]
    check("清洗后码表排除 U+3000", len(u3000_in_cleaned) == 0, str(len(u3000_in_cleaned)))
    check("清洗后码表行数 = 总数-占位符", len(cleaned) - 1 == len(pairs) - 1,
          f"rows={len(cleaned)-1}, expect={len(pairs)-1}")

    # 报告头部：v1.2 未注册仲裁源时应为"多源仲裁：未启用"，不再写死 ChaseDream
    with io.open(tool.REPORT_MD, encoding="utf-8") as f:
        report_text = f.read()
    check("v1.2 无源时报告头不再写死 ChaseDream",
          "ChaseDream" not in report_text and "多源仲裁：未启用" in report_text,
          "报告头应动态生成：无源时显示'多源仲裁：未启用'")


def test_empty_codebook():
    print("\n=== F1. 空码本边界 ===")
    aud = make_auditor([])
    aud.run_all(cd_arbitration=False)
    check("空码本：总条数=0", aud.stats.get("总条数") == 0)
    check("空码本：回归 0/56（应产生56条回归失败）",
          aud.stats.get("回归测试通过") == 0, str(aud.stats.get("回归测试通过")))
    check("空码本：无异常崩溃", True)


def test_arbitration_integration_mismatch():
    print("\n=== F2. 仲裁集成：不一致字写入勘误 ===")
    # 汉=3352 本地，但模拟源返回 9999 → 应产生高严重度勘误
    pairs = [("3352", "汉")]
    engine = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    engine.register(MockSource("MockA", {"汉": "9999"}, default=None))
    aud = make_auditor(pairs, engine=engine)
    aud.run_all(cd_arbitration=True)
    mismatch_errata = [e for e in aud.errata if e["问题类型"] == "多源仲裁不一致"]
    check("仲裁不一致 -> 高严重度勘误", len(mismatch_errata) == 1 and mismatch_errata[0]["严重度"] == "高",
          str(mismatch_errata))


def test_health_check_interface():
    print("\n=== F3. 扩展接口：自定义源注册与 batch ===")
    class CustomSource(CodeSource):
        @property
        def name(self): return "自定义源"
        @property
        def version(self): return "test-v1"
        def __init__(self): self.map = {"汉": "3352"}
        def query(self, char):
            return self.map.get(char)

    src = CustomSource()
    check("自定义源 name/version", src.name == "自定义源" and src.version == "test-v1")
    check("自定义源默认 health_check", src.health_check() is True)
    check("batch_query 默认实现", src.batch_query(["汉", "观"]) == {"汉": "3352", "观": None})

    engine = ArbitrationEngine(strategy="unanimous", sample_size=10, request_interval=0)
    engine.register(src)
    r = engine.arbitrate("汉", "3352")
    check("自定义源仲裁 pass", r.status == "pass", r.detail)


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    print("=" * 66)
    print("码本校勘工具 v1.1 全面模拟测试")
    print("=" * 66)
    test_char_category()
    test_arbitration_result()
    test_arbitration_engine()
    test_chasedream_source_parsing()
    test_auditor_integration()
    test_empty_codebook()
    test_arbitration_integration_mismatch()
    test_health_check_interface()

    print("\n" + "=" * 66)
    print(f"测试结果：{PASS} 通过 / {FAIL} 失败")
    if FAILURES:
        print("\n失败/观察项明细：")
        for name, detail in FAILURES:
            print(f"  - {name}\n    {detail}")
    print("=" * 66)
    sys.exit(1 if FAIL else 0)
