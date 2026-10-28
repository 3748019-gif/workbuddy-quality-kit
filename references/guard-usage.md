# 只读检查器

需要 Python 3.9 或更新版本，仅用标准库。先发现当前 WorkBuddy 管理的解释器，不硬编码原电脑路径。下面的 python、技能路径、任务根目录和文件名都要替换成当前环境实际值。不要把示例业务修改当成本次用户授权。

1. 修改前保存所需输入的 SHA-256：

`python 技能目录/scripts/office_guard.py snapshot --root 任务目录 --out 任务目录/source-hashes.json input/原件.docx input/原件.xlsx`

清单只存相对路径和哈希，不复制内容；已有同名清单时先读并使用，不能覆盖原始基线。为新任务使用独立目录。

2. 保存交付物后检查原件：

`python 技能目录/scripts/office_guard.py check --root 任务目录 --manifest 任务目录/source-hashes.json --out 任务目录/source-check.json`

3. 旧模板窄范围修改时创建 allow.json，仅写用户明确授权的变更。例如：

```json
{
  "xml_text": [
    {"part":"word/document.xml","xpath":".//w:body/w:p[2]/w:r[1]/w:t","before":"原文字","after":"新文字"}
  ],
  "xlsx_cells": [],
  "formula_cache_may_change": false
}
```

先读实际 XML 取得唯一定位，不能猜序号。DOCX 原句可能跨多个 run，需要分别给出对应文字节点，不重建整段。只支持 ElementTree XPath 子集，前缀 w 和 s 已内置。XLSX 示例：

```json
{"xlsx_cells":[{"sheet":"登记","cell":"C2","before":10.25,"after":12.35}],"formula_cache_may_change":true}
```

标量规则不支持修改公式；需要修改公式、增加行列、修订标记、图表或复杂对象时，这个窄范围检查器不能替代专项验收。不得为了让它通过而删除用户所需内容。

`python 技能目录/scripts/office_guard.py diff input/原件.docx output/成品.docx --allow allow.json --out scope-check.json`

XLSX 同理，替换文件扩展名并使用单元格规则。检查器验证必要改动是否真实发生，并比较其他 XML/ZIP 部件；解析共享字符串后比较，允许在公式本体不变时忽略公式缓存变化。仍会严格检查样式、验证、批注等结构。

返回码0且报告 ok=true 才表示本次检查通过；1表示未通过或无法判断。缺少输出文件、无效规则、文件损坏均不能记通过。报告必须为.json，不覆盖原件。用实际最终文件重新运行，不采用早先中间稿的结果。

限制：正常的内部序列化改写可能被判为差异，需人工或专项检查解释；本工具没有完整 Office 语义引擎，也不证明视觉分页、业务结论、原生公式重算或宏安全。超过100MB解压大小的包拒绝处理。

清单须含非空文件映射及有效SHA-256。允许范围只接受已列明字段，formula_cache_may_change必须是JSON布尔值true/false，不能写成字符串。字段拼错、空基线或类型错误会失败，不能当作通过；发生错误以本次返回码和输出为准，不复用遗留的成功报告。

只含空白的修订删除文字、域代码和单元格缓存值也纳入比较；XML容器的排版缩进仍可忽略。此检查不代替原生Office显示核验。
