# 5.0 安装与使用

5.0是用户指定的后续开发基线，承接4.5离线候选r3。它已发布源码与安装材料，但完整内容验收仍未通过；详情见[验证记录](VERIFICATION.md)。4.4保留为历史稳定版。

## 选择下载包

- [GUI技能包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-v5.0.zip)：只有一个技能目录，14份核心文件加MIT许可证，共15份。仅用于WorkBuddy技能上传入口，不包含自动入口安装或完整自配置材料。
- [完整自配置包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-setup-v5.0.zip)：含安装器、自检、虚构材料、可独立还原源码的Word/TXT手册及安装提示词。推荐交给WorkBuddy读取。
- [源码包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v5.0/workbuddy-quality-kit-source-v5.0.zip)：用于维护、审查或从源码准备安装目录。仓库根目录只有一个SKILL.md，不将整个源码仓库当GUI技能包上传。

安装默认保留所有原配置。已存在同名4.4或定制版时，安装器会拒绝覆盖；这是正常保护，不是已经升级成功。若要评估5.0，请用明确的隔离测试环境。升级迁移覆盖旧文件不在本次包的自动操作范围内。

## 安装提示词

```text
请读取这份 WorkBuddy Quality Kit 5.0 开发基线的说明并完成自配置。我了解它保留已知的文字说明一致性问题，发布不等于完整内容验收通过。

先在本次独立工作目录准备材料并自检。保留我的原全局指令、人设、默认模型、个人记忆、权限、安全保护、代理、登录、连接器、其他技能、已有Hook及启停状态，不读取或写入个人记忆。核实本机 WorkBuddy 版本、实际技能目录、设置格式，以及正常可用的 Python 3.9 以上解释器，不猜路径。

若提供的是源码仓库，运行 tools/prepare_setup.py --output 指向仓库外一个尚不存在的新目录；若提供完整自配置包，使用包内安装文件；若只有Word或TXT手册，先按附录还原29份文件并逐项核对字节数和SHA-256。实际执行 selftest.py 和 selftest_offline.py，分别确认71/71、41/41及退出码0。失败时保留现场和错误，不改期望、不关闭保护、不换不明解释器来凑通过。

按 install_skill.py 的 plan/apply/verify 处理这一个技能。目标不存在时才新增；内容完全一致时复用；发现同名4.4、定制版、较新版本、产品附加元数据或人工修改时保留并报告冲突，不覆盖、不删除、不改名制造第二份同名技能。出现冲突可以完成隔离测试，不得宣称升级成功。

如实际安装已成功且设置兼容，我同意按 install_entry.py 的 plan/apply/verify 只追加本包缺失的 SessionStart 和 PreToolUse 入口，保留原Hook顺序和所有无关字段。入口不可兼容时保留原设置，提供显式调用方法，并如实说明未完成。

所有新收据、备份和日志只放本次独立目录。沿用我指定的可用模型，不改变全局默认模型；本轮研发使用DeepSeek V4.1 Flash并不要求他人更换模型。安装提问连同必要原生确认合计不超过5个；必要授权不能省略，超过上限则保留已完成部分并报告剩余事项。

安装后分别核实文件安装、产品发现及启用、新任务实际读取技能与适用参考、一个虚构短任务的结果正确与原件保留。特别核对最终说明里的数量、全部/部分、空值和范围是否与原资料及成品一致，不能把程序自检通过当作内容已通过。

最后报告真实变更、原配置保留、两个自检、新任务结果、同名冲突、未验证范围，以及本机私有收据位置和有限回退命令。共享时不带收据、日志、账号或真实任务资料。
```

## 源码准备与自检

在源码仓库目录，用本机已核实的解释器执行：

```shell
python3 tools/prepare_setup.py --output ../quality-kit-setup-v5
python3 ../quality-kit-setup-v5/selftest.py
python3 ../quality-kit-setup-v5/selftest_offline.py
```

输出目录的父目录必须存在，输出目录须尚不存在且位于仓库外。准备工具校验SHA并生成29份安装文件，只准备材料、不写全局设置。工具只使用Python标准库。单份Word/TXT手册恢复方式在手册正文中。

## 计划、安装与回退

进入准备后的目录执行；下面大写占位符必须替换成已核实的路径：

```shell
python3 install_skill.py plan --root SKILL_ROOT
python3 install_skill.py apply --root SKILL_ROOT --receipt NEW_RECEIPT
python3 install_skill.py verify --root SKILL_ROOT
```

只有选择本包入口、确认设置兼容且技能安装成功时，才执行：

```shell
python3 install_entry.py plan --settings SETTINGS --skill-root INSTALLED_SKILL
python3 install_entry.py apply --settings SETTINGS --skill-root INSTALLED_SKILL --receipt NEW_ENTRY_RECEIPT
python3 install_entry.py verify --settings SETTINGS --skill-root INSTALLED_SKILL
```

安装器可用`--python`指定已核实的正常解释器。入口验证只证明所查规则读取条件，不证明业务内容正确。原入口实现来自4.4，其内部提示保留历史组件版本文字；5.0新增能力通过主技能及按需参考读取。

回退使用本次私有收据，先入口后技能：

```shell
python3 install_entry.py rollback --settings SETTINGS --receipt NEW_ENTRY_RECEIPT
python3 install_skill.py rollback --root SKILL_ROOT --receipt NEW_RECEIPT
```

仅处理本包拥有且未被后来修改的新增内容。人工改动、无法核实归属或同名冲突均保留；不会用整份旧设置覆盖当前设置。技能回退采用可恢复归档。
