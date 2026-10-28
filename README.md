# WorkBuddy Quality Kit

让 WorkBuddy 在复杂任务中更认真地读要求、保留原件、检查结果，并在中断后接着完成工作。

这是一个独立技能，名称为 `workbuddy-quality-kit`，当前核心版本为 4.4。项目仓库：[3748019-gif/workbuddy-quality-kit](https://github.com/3748019-gif/workbuddy-quality-kit)。仓库根目录只有一个 `SKILL.md`。它适用于多文件处理、Word/Excel/PPT 修改、数据核对、可复用脚本、故障恢复和跨会话续接；简单问答不强加完整流程。

## 能改善什么

- 做之前确认输入和交付要求，减少漏项和理解偏差。
- 文件改完后检查实际产物，并尽量保留原格式、原件和人工修改。
- 多份结果一起更新时，使用版本检查与中断恢复，减少交付混用新旧版本。
- 工具报错时保留真实返回结果，减少没有新依据的重复尝试。
- 长任务保存必要节点，换会话后核对最新材料再继续。

技能提供工作方法和本地检查工具，不保证检索找全或复杂判断永远正确，也不承诺达到某个模型的统一能力分数。

## 安装

一般使用：从 Releases 下载[专用技能包 workbuddy-quality-kit-v4.4.zip](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v4.4/workbuddy-quality-kit-v4.4.zip)，在 WorkBuddy 的“专家·技能·连接器 → 技能 → 添加技能 → 上传技能”中导入，并在新任务里验证调用。不同版本的界面可能不同，以[官方技能说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)为准。

需要复现 4.4 的增量配置、可选自动入口及回退收据时，下载并解压[完整源码包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v4.4/workbuddy-quality-kit-source-v4.4.zip)，或使用 GitHub 的 Code → Download ZIP 取得完整仓库，把目录交给 WorkBuddy，发送 [安装提示词](docs/INSTALL.md#安装提示词)。准备工具只在你指定的新目录生成安装材料，不会直接改动 WorkBuddy 配置。完整源码仓库含维护文件，不作为 GUI 导入包；专用技能包包含 11 份原版核心文件及 MIT `LICENSE`，共 12 份。两种安装途径仍需分别核验；产品导入可能添加元数据，CLI 不承诺自动复用 GUI 导入的目录。

Python 检查工具要求正常可用的 Python 3.9 或以上，只使用标准库。技能文件本身的导入与执行脚本所需的 Python 环境是两件事。

## 日常使用

可直接说：

> 请使用 workbuddy-quality-kit 完成下面的任务，读取适用参考，检查最终文件，并说明未验证的部分。

自动调用取决于产品发现、启用状态及任务匹配。可选入口与技能导入分别验收，入口不兼容时仍可显式调用技能。

## 原配置与数据

默认保留原指令、个人记忆、模型、其他技能、已有 Hook 和安全设置。同名内容有差异时保留并报告，不强行覆盖。只有明确选择完整配置时，才按计划新增本包兼容的入口。

仓库按授权公开维护者的 GitHub 署名，不包含个人记忆、账号凭据、密钥、真实任务资料、运行日志或安装收据。本包 Python 工具不内置联网请求；模型和 WorkBuddy 自身的数据处理遵循你使用的产品设置。可选入口会临时读取当前会话日志来判断规则是否已读取，不另存会话正文。

## 验证范围

11 份核心文件保持原 4.4 正式包字节一致，MIT `LICENSE` 作为第 12 份附属文件随技能安装和分发。仓库新增的目录准备工具单独验证，重建 25 份文件的安装目录；原 71 项自检在该目录运行。具体结果与边界见 [验证说明](docs/VERIFICATION.md)。

原版本曾在 macOS 的 WorkBuddy 5.8.3 进行实际测试；这不代表当前所有 WorkBuddy 版本、Windows 或其他账户均已实装验证。新环境应完成现场安装与短任务验收。

## 仓库内容

```text
SKILL.md                 唯一技能入口
references/              按任务读取的参考
scripts/                 4.4 原版检查工具
tools/                   安装目录准备工具和原版安装器
tests/fixtures/          纯虚构自检材料
docs/                    安装与验证说明
bundle-manifest.json     11 份核心与 LICENSE 校验
release-manifest.json    仓库发布文件校验
```

版本变化见 [CHANGELOG.md](CHANGELOG.md)。采用 [MIT 许可证](LICENSE)，Copyright (c) 2026 3748019-gif。许可文件随专用技能包、源码包和安装内容分发。

本项目为社区制作的技能，与腾讯 WorkBuddy 官方无隶属关系。
