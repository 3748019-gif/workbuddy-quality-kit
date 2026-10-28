# 安装与回退

## 两种使用方式

导入技能：下载[专用技能包 workbuddy-quality-kit-v4.4.zip](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v4.4/workbuddy-quality-kit-v4.4.zip)，通过 WorkBuddy 的“添加技能 → 上传技能”导入。包内只有一个技能，包含 11 份原版核心文件及 MIT `LICENSE`，共 12 份。导入后检查技能发现、启用状态及一次新任务的实际调用。该流程不等于执行了可选 Hook 安装器。入口依据：[WorkBuddy 官方技能说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。本次检查了 ZIP 布局，但尚未在 WorkBuddy 界面中重新导入；现场结果应如实报告。

增量自配置：下载[完整源码包](https://github.com/3748019-gif/workbuddy-quality-kit/releases/download/v4.4/workbuddy-quality-kit-source-v4.4.zip)，或通过 GitHub 的 Code → Download ZIP 取得完整源码仓库，使用下面提示词，让 WorkBuddy 从解压后的目录准备 4.4 原版安装布局，运行自检，再核实安装计划。可选自动入口会改动本机设置文件，须保留原有内容并使用单独收据。不要将含 README、tools 等维护文件的完整源码仓库当作 GUI 技能包导入，以免被原版严格安装校验判为同名差异。

遇到已安装的同名定制或较新版本，默认保留，不用删除、覆盖或改名重复安装来消除冲突。GUI 可能增加产品元数据；旧 4.4 包若缺少本次新增的 LICENSE，也可能被 CLI 判为文件集合不同。两种途径不保证直接复用，发生差异时保留并报告。

## 安装提示词

把以下整段与解压后的完整仓库目录一起交给 WorkBuddy：

```text
请读取本目录 README.md、docs/INSTALL.md 和 tools/setup-policy.json，在本机安装并验收 workbuddy-quality-kit 4.4。

先核实当前 WorkBuddy 版本、实际生效的技能目录、技能启停状态、设置文件格式，以及正常可用的 Python 3.9 以上解释器。不要猜目录，不要把示例路径当真实路径。

运行 tools/prepare_setup.py --output 指向本次工作目录下、仓库外且尚不存在的新目录。它会校验发布文件，并将原 11 份核心、MIT LICENSE、原安装器及虚构自检材料重建为 25 份文件的兼容安装布局；这一步只准备材料，不安装。进入生成目录，实际运行 selftest.py，确认退出码为0且71项通过。

保留我的原指令、人设、默认模型、个人记忆、其他技能及启停状态、已有Hook、连接器、权限和代理；不要读取或改写个人记忆。只按本包原版 install_skill.py 的 plan/apply/verify 新增或复用这一个技能。相同内容直接复用；同名定制、较新版本或归属不明时保留并报告，不覆盖、不降级、不重复安装。若已通过产品界面导入，先核实实际安装目录，不能再创建第二份同名技能。

我同意在兼容时按原版 install_entry.py 的 plan/apply/verify 追加本包缺失的 SessionStart 和 PreToolUse 入口；保留所有已有Hook，不改安全机制。设置格式或产品入口不兼容时保留原配置，完成可行的技能安装并给出显式调用方法，不把入口失败算作成功。

所有新日志、备份、自检材料和收据仅存入本次独立工作目录。自检失败或权限拒绝不能通过移除安全保护、改预期或反复换命令绕过。

分别验证文件安装、产品发现与启用、新任务实际读取技能与适用参考，以及一个虚构短任务的输出正确和原件保留。安装使用我指定的可用模型，不改全局默认模型；未指定时选可用的 DeepSeek、GLM 或混元，不用Kimi或模型分配不明确的Auto。

安装提问和原生授权确认合计不超过5个。可自行核实的信息自行核实，保留必要的安全确认；可选功能如需超出预算，保留当前可用配置并说明未完成项。

最后说明实际变更、保留项、71项自检、新任务验收、冲突及未验证项，并给出本机私有备份和收据位置及回退命令。不要把文件复制成功等同于产品实际启用。
```

## 手动准备与校验

以下从解压后的仓库根目录执行。命令中的 Python 名称和目录要替换成已核实的本机值；Windows 可使用正常的 `python` 或 `py -3`。

```shell
python3 tools/prepare_setup.py --output ../quality-kit-setup
python3 ../quality-kit-setup/selftest.py
```

输出目录的父目录必须存在；输出目录必须不存在，且不得在仓库内部。出现错误会返回非零退出码，不自动清理或覆盖已有目录。

## 安装与入口

在准备出的目录执行。以下路径仅是待替换的参数说明，不可直接作为实际安装路径：

```shell
python3 install_skill.py plan --root "<核实后的现有技能目录>"
python3 install_skill.py apply --root "<核实后的现有技能目录>" --receipt "<独立工作目录中的新收据文件>"
python3 install_skill.py verify --root "<核实后的现有技能目录>"
```

MIT `LICENSE` 与 11 份核心一起安装，不省略许可文件。`verify` 返回 `reuse` 才表示文件集合与该版本完全匹配，仍须验证产品发现和启用。安装器不覆盖同名差异，也不会创建一个尚不存在的全局技能目录。

只有选择启用自动入口并确认设置兼容时，才使用 `install_entry.py`：

```shell
python3 install_entry.py plan --settings "<实际设置文件>" --skill-root "<实际已安装技能目录>"
python3 install_entry.py apply --settings "<实际设置文件>" --skill-root "<实际已安装技能目录>" --receipt "<独立工作目录中的新入口收据>"
python3 install_entry.py verify --settings "<实际设置文件>" --skill-root "<实际已安装技能目录>"
```

若需指定解释器，用原安装器的 `--python` 参数传入已核实的正常解释器路径。入口检查只检查规则读取，不批准命令，也不替代内容验收。

## 回退

使用本次安装在本机生成的原收据，先回退入口，再回退技能：

```shell
python3 install_entry.py rollback --settings "<实际设置文件>" --receipt "<本次入口收据>"
python3 install_skill.py rollback --root "<原技能目录>" --receipt "<本次技能收据>"
```

回退只处理本包拥有且未被后续修改的内容。遇到人工修改、新增文件或无法核实归属时应停止自动覆盖并报告。原技能安装器以归档方式保留内容，不恢复整份旧设置文件覆盖新设置。
