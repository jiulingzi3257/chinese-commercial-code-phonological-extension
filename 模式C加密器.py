# -*- coding: utf-8 -*-
"""
模式 C 加密器（定稿版 v1）——《标准中文电码声学扩展协议》
三步法：① 拆数取大 → d1；② 声调驱动差分（四舍五入 + 对称分段）→ d2d3；③ 声调置位 → d4
用法：python 模式C加密器.py [S C T]      （不传参则运行内置 7 字自检）
示例：python 模式C加密器.py 24 6007 1    → 8531
"""
import sys


def d1_of(S: int) -> int:
    """步骤① 拆数取大：
    S<=9 取自身；3|S 取 S/3；否则取 (S/2) 的个位"""
    if S <= 9:
        return S
    if S % 3 == 0:
        return S // 3
    return (S // 2) % 10


def d23_of(C: int, T: int) -> int:
    """步骤② 声调驱动差分：
    对 C.T 作标准四舍五入（.5 及以上进），再 |前两位 − 后两位|"""
    c = int(C + T / 10 + 0.5)          # 四舍五入到整数
    hi, lo = divmod(c, 100)            # 对称栅栏分段
    return abs(hi - lo)


def encrypt(S: int, C: int, T: int) -> int:
    """7 位编码 → 4 位密文"""
    return d1_of(S) * 1000 + d23_of(C, T) * 10 + T


if __name__ == "__main__":
    if len(sys.argv) == 4:
        print(encrypt(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])))
    else:
        cases = [
            ("魂", 8, 7609, 2),
            ("西", 24, 6007, 1),
            ("军", 10, 6511, 1),
            ("点", 4, 7820, 3),
            ("领", 12, 7325, 3),
            ("校", 24, 2699, 4),
            ("导", 4, 1418, 3),
        ]
        for name, S, C, T in cases:
            print(f"{name} {S:02d}{C:04d}{T} -> {encrypt(S, C, T)}")
