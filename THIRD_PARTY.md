# 第三方数据与授权

## ECDICT 英汉词典

来源：https://github.com/skywind3000/ECDICT

从官方仓库 `master/ecdict.csv` 转换为 SQLite，仅保留 word、phonetic、translation 三列；剔除空释义，按不区分大小写的单词去重。未改写原词典释义。

- 打包词条：770,238 条
- 构建日期：2026-11-19
- 原 CSV SHA-256：`d1ecbdf9ee2b920afb6f430ca6b6bb9f559588cf0dff86e04bd255f9390843cc`
- 授权：MIT，全文见 `ECDICT-LICENSE`，版权归原作者。

## Tesseract 英文模型

来源：https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0

模型文件：`tessdata/eng.traineddata`

SHA-256：`7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`

授权：Apache-2.0，全文见 `tessdata/LICENSE`。

程序通过系统 Tesseract、GTK3 和 X11 动态库运行；这些系统库没有复制进本包。

## 短语说明

`phrases.json` 是本工具附带的简短中文解释，不应视为在所有语境下成立的唯一含义。
