# 标准中文电码声学与音韵学扩展协议
**Acoustic and Phonological Extension to the Standard Chinese Commercial Code**

> 项目定位：在不改动国标四位电码（Chinese Commercial Code, CCC）本体的前提下，为其增加声母（shengmu / syllable-initial consonant）与声调平仄（level/oblique tone）两层音韵学信息，形成 7 位扩展编码（声母 2 位 + 电码 4 位 + 声调 1 位），面向 TTS 多音字消歧、古籍 NLP 与数字人文研究。
>
> This project extends the standard 4-digit Chinese Commercial Code (CCC) with two phonological layers—initial consonant and tone—without modifying the CCC codebook itself, yielding a 7-digit encoding for TTS polyphone disambiguation, ancient-Chinese NLP, and digital humanities research.

## 语言说明 / Language Note

本仓库文档主体为简体中文，便于国内文史、语言学与古籍数字化同行阅读；项目定位、核心术语与 License 声明提供中英对照。
The documentation in this repository is primarily in Simplified Chinese for accessibility to domestic researchers; project framing, key terminology, and license statements are provided bilingually.

## 为什么要做这件事

四位标准中文电码只记录汉字形体，不携带读音信息。面对古籍海量多音字、通假异读字、破读字，单一字形编码无法区分"箪食"（sì）与"食马者"（sì）、"郦食其"（yì）这类语境异读。本扩展把音韵学维度叠回电码，使编码同时承载形、声、调三层信息：

- **TTS 合成**：多音字按位注册（声母+电码+声调），可直接定位正确读音；
- **古籍 OCR/NLP**：扩展编码为古汉语大模型提供音形义融合的 token 锚点；
- **跨学科对齐**：文史考据（因声求义）与计算机编码（格式规整）在同一编码结构上对话。

> ⚠️ 本项目是语言学元数据扩展与校勘工具，**不是现代密码系统**。标准中文电码本身是 1983 年公开出版物；本仓库只公开规范文本与码本校勘工具，加解密层（如模式 C 加密器）不在公开范围内。

## 编码结构

```
7 位扩展码 = 声母 2 位 + 标准电码 4 位 + 声调 1 位
```

| 段 | 位数 | 含义 | 示例（"汉"） |
|---|---|---|---|
| 声母位 | 2 | 拼音首字母在字母表顺位（零声母按首字母 a→01, e→05, o→15） | `08`（H） |
| 电码位 | 4 | 国标标准电码本四位码 | `3352` |
| 声调位 | 1 | 1=阴平 2=阳平 3=上 4=去（平仄二分：平=1/2，仄=3/4） | `4`（去声） |

完整编码示例：

```
汉 → 08 3352 4 → 0833524
食（箪食，sì）→ 19 7380 4 → 1973804
食（食品，shí）→ 19 7380 2 → 1973802
郦食其（yì）→ 25 7380 4 → 2573804
```

10 位全息码在 7 位基础上再加韵母 3 位，用于需要完整音节锚定的研究场景，规范见 [`docs/`](docs/)。

## 配套工具

`tools/码本校勘工具.py` 是全量码本校勘脚本：

```bash
python tools/码本校勘工具.py            # 本地全量校勘（联网仲裁需配置源）
python tools/码本校勘工具.py --no-cd    # 跳过联网，纯本地校验
python test_audit_suite.py              # 76 项断言回归
```

v1.2 实证：7317 条码字对解析、回归 56/56 通过、勘误 29 条。支持通过 `CodeSource` 抽象基类接入外部码本源（语保工程、审音字库等），多源仲裁策略 unanimous / majority / priority 可选。

## 数据文件

| 文件 | 说明 |
|---|---|
| `data/dianma_ben.html` | 《标准电码本（修订本）》1983 年第 3 版电子化校勘版（7317 条） |
| `data/清洗后码表.csv` | 经本工具清洗后的码表 |
| `data/勘误表.csv` | 校勘发现的 29 条勘误 |
| `data/声学扩展规则的字母表.xlsx` | 声母/韵母编码字母表（数据科学用） |

## 相关资源 / Related Resources

本项目与以下古汉语 NLP 资源库互补，本仓库不打包其数据（各库有独立许可证）：

- [古汉语通假字资源库](https://github.com/frederick-wang/tongjiazi-resources) — 王兆基, 张诗睿, 胡韧奋, 张学涛. 古汉语通假字资源库的构建及应用研究[J]. 中文信息学报, 2024, 38(03).
- [古汉语典故资源库](https://github.com/KaijieMo-kj/Ancient-Chinese-Allusion-Resource-Database) — 莫凯洁, 丘子靓, 胡韧奋, 王予沛. 古汉语典故资源库的构建及应用研究[J]. 中文信息学报, 2024, 38(11).
- [古汉语词义标注语料库](https://github.com/iris2hu/ancient_chinese_sense_annotation) — 舒蕾, 郭懿鸾, 王慧萍, 张学涛, 胡韧奋. 古汉语词义标注语料库的构建及应用研究[J]. 中文信息学报, 2022, 36(05).

## 引用 / Citation

规范草案与校勘方法见 `docs/`。学术引用建议：

> 林俊森. 标准中文电码的声学与音韵学扩展协议 v2.1[S/OL]. GitHub: jiulingzi3257/chinese-commercial-code-phonological-extension, 2026.

## 国内主仓库 / Gitee Mirror

国内高校、学界访问稳定主仓库（CC0）：
<https://gitee.com/intellectualdisability-of-jun-sen/jiyuHANYUYANWENXUEYUYANXUEtezhengdechasedreamkuozhantioxi>

欢迎通过 GitHub Issues 提出建议、批评或合作；长文本训诂讨论欢迎附文献出处。
International peers are welcome to open issues and GitHub Discussion for suggestions, critiques, or collaboration. I will reply in both Chinese and English in a brief manner.

## 许可证 / License

- **代码**（`tools/` 下脚本）：[MIT License](LICENSE)
- **规范文本与文档**（`docs/`、本 README）：[CC BY 4.0](docs/LICENSE) — 署名即可，不限衍生用途

> Gitee 主仓库沿用 CC0-1.0；GitHub 主仓库采用上述组合许可证，以保留署名权并便于学术引用。
