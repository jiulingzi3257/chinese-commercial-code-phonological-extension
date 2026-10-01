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
    S<=9 取自身；3|S 取 S/3；否则取 (S/2) 的个位。
    注意：S>=30 且 3|S 时 S/3 >= 10，密文将超 4 位，属协议定义域之外。"""
    if S <= 9:
        return S
    if S % 3 == 0:
        d = S // 3
        if d > 9:
            raise ValueError(
                f"S={S} 拆数取大得 {d}（两位数），密文格式将被破坏；"
                f"协议定义域内 S 应满足 S<30 或 3∤S")
        return d
    return (S // 2) % 10


def d23_of(C: int, T: int) -> int:
    """步骤② 声调驱动差分：
    对 C.T 作标准四舍五入（.5 及以上进），再 |前两位 − 后两位|"""
    if not 0 <= C <= 9999:
        raise ValueError(f"电码 C 超出 0000-9999 范围: {C}")
    if not 0 <= T <= 9:
        raise ValueError(f"声调码 T 须为 1 位数字(0-9): {T}")
    c = int(C + T / 10 + 0.5)          # 四舍五入到整数
    hi, lo = divmod(c, 100)            # 对称栅栏分段
    return abs(hi - lo)


def encrypt(S: int, C: int, T: int) -> int:
    """7 位编码 → 4 位密文"""
    return d1_of(S) * 1000 + d23_of(C, T) * 10 + T


if __name__ == "__main__":
    if len(sys.argv) == 4:
        try:
            print(encrypt(int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])))
        except ValueError as e:
            sys.exit(f"错误：{e}\n用法：python 模式C加密器.py [S C T]    示例：24 6007 1")
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
