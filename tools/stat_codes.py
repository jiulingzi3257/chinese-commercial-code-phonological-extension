import os, re, io
# 以本文件所在目录为基准定位码本，跨平台可用（Windows/Linux/macOS）
_codebook = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dianma_ben.html')
html = io.open(_codebook, encoding='utf-8').read()
pairs = re.findall(r'(\d{4})<br/>\s*<span[^>]*>([^<]+)</span>', html)

def is_cjk(ch):
    # 多字符组合（如 ——、……）不是单个汉字，直接判否
    if len(ch) != 1:
        return False
    cp = ord(ch)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF

hanzi = [(c,ch) for c,ch in pairs if is_cjk(ch)]
special = [(c,ch) for c,ch in pairs if not is_cjk(ch)]
print('总条数:', len(pairs))
print('CJK汉字:', len(hanzi))
print('非汉字(特殊字符):', len(special))
print()
print('=== 特殊字符清单（按码排序）===')
for c, ch in sorted(special):
    cps = ' '.join(f'U+{ord(x):04X}' for x in ch)
    print(f'{c}: {ch} ({cps})')
print()
print('=== 9900-9999 段全部内容 ===')
for c, ch in sorted(pairs):
    if c >= '9900':
        print(f'{c}: {ch} (CJK={is_cjk(ch)})')
