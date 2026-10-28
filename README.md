# WorkBuddy Quality Kit 5.0

帮助WorkBuddy更完整地读取本地材料、检查任务漏项、核对数据与交付文件，并保留原件、人工修改及中断恢复信息。

当前版本5.0，作为后续开发基线，承接4.5离线候选r3。完整内容验收仍有两处说明矛盾，已公开记录在[验证说明](docs/VERIFICATION.md)。版本发布不表示已解决全部内容检查问题。历史稳定版[4.4](https://github.com/3748019-gif/workbuddy-quality-kit/releases/tag/v4.4)保留。

仓库只有一个技能：`workbuddy-quality-kit`。适合多文件处理、表格核对、Word/Excel/PPT修改、可复用脚本、故障恢复和长任务续接；简单问答保持轻量。

## 5.0增加了什么

- 分段读取本地文本、JSON、CSV及限定范围的DOCX/XLSX，提供来源定位、文件SHA和后续读取位置，减少长内容截断后直接下结论。
- 检查应有ID与结果ID是否一一对应，发现漏项、重复和多余项。
- 使用精确小数汇总核对明细与结果，帮助发现对账错误。
- 按任务读取材料与内容复核参考，检查例外、空值、范围和交付要求。

工具只能覆盖明确可核验的部分。最终文字仍可能把部分写成全部、把可行数量写成总数。它不保证检索找全、复杂判断零错误或达到某个统一能力分数。本版没有加入在线搜索增强。

## 下载与安装

1. [专用GUI技能包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-v5.0.zip)：15份文件，上传到WorkBuddy技能入口。
2. [完整自配置包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-setup-v5.0.zip)：可直接交给WorkBuddy，内含Word/TXT自配置手册、安装提示词和自检。
3. [源码包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-source-v5.0.zip)：供维护或审查。仓库根目录只有一个SKILL.md。

详细步骤与可复制提示词见[安装说明](docs/INSTALL.md)。完整源码包不要直接当GUI技能ZIP上传。已有同名4.4或人工定制配置会保留并报告冲突，不自动覆盖。5.0适合评估与后续开发，普通使用者可继续选择4.4。

Python工具需要本机正常可用的Python3.9以上，仅使用标准库；安装不强迫更换模型。安装提问连同必要原生确认最多5个。

## 原配置与共享

默认保留原指令、人设、模型、权限、其他技能、已有Hook、连接器及启停状态；不读取或写入个人记忆。安装仅新增缺失内容，同名不同内容保留；回退只处理本包拥有且未被后来改动的新增内容。

公开包采用MIT许可证，Copyright (c) 2026 3748019-gif，不包含账号凭据、真实任务资料、个人记忆、日志或私有收据。可选入口会临时读取当前会话日志以判断规则是否已读，不另存会话正文。

## 维护入口

```text
SKILL.md                唯一技能入口
references/             按需读取的任务参考
scripts/                本地读取与交付检查工具
tools/                  安装目录准备、安装器和两套程序自检
tests/fixtures/         虚构安装自检材料
docs/                   安装、验证与已知问题
bundle-manifest.json    15份技能文件的SHA
release-manifest.json   发布源码清单
```

维护者从本版本继续开发，先读[版本记录](CHANGELOG.md)和[已知问题](docs/VERIFICATION.md)，保留原失败证据，用新任务检验改进。文件安装、产品发现、实际读取和结果正确须分别验证。

本项目为社区技能，与腾讯WorkBuddy官方无隶属关系。
