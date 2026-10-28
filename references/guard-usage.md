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


## 两阶段请求与交付工具的边界

review_request.py提供prepare、compare、recheck、verify及从记录派生的handoff，均需显式路径。要求、来源原件、成品、回复及可选旧稿参照在ROOT内（source不可位于WORK过程区），仅按显式路径只读；记录及临时写入只在WORK内，目录必须已经存在；显式--register-stop另仅更新已初始化项目门控的自有状态。成品可位于另一个获准输出目录，无需扩大WORK。不递归扫描，不读取原生会话日志、设置或个人记忆；不安装、不修改资料/成果、不自调模型。拒绝路径越界、符号链接、文件间硬链接别名、未知记录和覆盖已有记录。临时写入仅在所选记录目录；锁冲突或文件变动就失败，保留现场，不盲删锁。记录是普通本地文件，不是防篡改凭据，不能抵御另一个进程恶意同时改写。

来源/旧稿参照每类最多40份，最终交付含可选回复共最多12份、单文件20MiB；记录128KiB、请求12KiB；超限拒绝而不截断清单，拟回复须UTF-8且不超过8KiB。未知格式仍可记录存在与SHA，reader_status=unverified_format不表示已读取；实际Agent须用已有适用工具读取，失败记具体缺口。已知扩展名同样不证明完整提取、视觉/Office重算或理解。prepare的--required-artifact仅声明路径，不证明对原任务理解完整；compare自动读取全量声明。后续只允许一次recheck增补必交并修复内容，handoff严格核对同集合及SHA，缺失/不一致不登记。不扫描目录补清单，也不接受handoff另传artifact或SHA。没有任意作者prompt参数，首次ID只是调用者从真实返回中取得的值，工具不认证身份；其后绑定ID和来源版本。可选--review-input仅在第二阶段引入原始旧稿/旧模板，后续SHA必须不变，不进入交付SHA，不能兼作source或artifact。真实调用、实际读文件及复核结论由原生工具返回与独立验收分别核对。

content_check.py handoff仅核对显式文件存在、SHA与支持格式的有限语法/容器。普通回执单文件20MiB、完整输出12KiB；自定义回复8KiB、单行1000字节。超限/不适用时保留内容并说明该项未验证，不截断、不删必答凑通过。未传--expect-sha256只证明调用时保存版本，不证明复核后没变。SOURCE与reply-root的业务身份仍须调用者按授权选择，工具不会自动识别原件/成品或用户授权。

完整回复只规范CRLF和外层空白行，内部空白、语气字、业务文字均不放宽。中性链接回执允许无语义空白、以及安全路径有无尖括号的等价写法；含空格/括号路径仍需尖括号，文字、目标、数量与次序不变，代码围栏/隐藏注释/额外断言不等价。

可选项目门控仅在macOS/POSIX验证，普通技能不自动安装它。初始化只给合并配置片段，保留原Hook/信任/权限，其他平台可用普通技能。--register-stop返回gate.status=armed才是本回合已登记；gate.state_file可查matched/partial，不把状态文件纳入成果哈希。Stop最多纠正一次，不反复登记清零；宿主未保证显示partial提示，任务停下不等于通过。流式显示可能先于Stop，不能保证错误文字从未显示。登记失败保留成果并说明，不能扩大全局权限绕过。
