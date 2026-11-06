# 安装与使用

把完整 ZIP 和下面的提示词一并交给 WorkBuddy。也可先解压到独立目录，再把目录交给它。安装需要本机已有 Python 3.9 或更高版本。仅想试做一份演示时，跳过安装，按本页末尾的日常用法直接指定技能目录。

## 可直接发送的安装提示词

请读取随附的 WorkBuddy Quality Kit 5.2，按 docs/INSTALL.md 自配置。先在独立目录核验完整包并运行随包自检。保留现有技能、全局指令、模型、权限和已有 Hook，遇到同名不同内容就保留并说明。不要读取或写入个人记忆。仅安装这一项技能，选配功能按我的明确选择启用，安装提问和必要的原生确认合计最多五次。安装后在新任务中实际调用一次，说明安装位置、哪些已生效、哪些仍需我处理。

## 执行步骤

1. 确认客户端实际使用的技能目录，找到可用的 Python。下文的 PY 代表该解释器。先查看 ZIP 目录，拒绝绝对路径、跨目录条目与符号链接，将文件解到新的独立目录。读取包根的 SKILL.md、release-manifest.json 及本页。核对分享者提供的 ZIP 校验值（如有）；包内清单用于核对内容完整。
2. 在包根执行 `PY tools/prepare_setup.py --output 新目录`。指定包外尚不存在的准备目录，准备工具会核验发布清单及核心文件，再生成安装布局。进入这个准备目录，分别运行 `PY selftest.py`、`PY selftest_offline.py`、`PY selftest_gate.py`、`PY selftest_review.py`。期望各退出码为 0，分别通过 71、93、89、48 项。自检在独立准备目录运行，失败保留日志，停止安装。
3. 在准备目录运行 `PY install_skill.py plan --root 技能目录`。add 时运行 `PY install_skill.py apply --root 技能目录 --receipt 新收据路径`，再运行 `PY install_skill.py verify --root 技能目录`；reuse 直接 verify。收据放在技能目录外的私有工作区。conflict 时停止全局安装，保留同名旧版或人工定制；本次任务可直接从解压目录读取 5.2。绝不以先删除旧版、改名重复安装或改权限来消除冲突。
4. 在新的 WorkBuddy 任务确认可发现并实际读取 workbuddy-quality-kit；制作 PPT 时再读取 references/presentations.md。用虚构材料试做一页，检查是否可编辑、主要事实是否清楚、模板与原件是否保留。报告实际核验的范围与冲突。
5. 退出使用时，如为本包新增且内容仍与收据完全相符，可执行 `PY install_skill.py rollback --root 技能目录 --receipt 原收据路径`。回退把这次新增的技能移入收据旁的归档。技能内容后续有修改时，保留现场并报告。

## 选配与平台差异

普通安装不改设置文件。需要沿用或新增旧版可选入口时，先运行 `PY install_entry.py --help` 查看所需的 settings、skill-root、python 和 receipt 参数，按 plan / apply / verify 操作；只在用户选择且确认平台兼容时追加缺失入口。已有入口与其他字段照原样保留。项目级检查按 references/local-review.md，仅对明确选择的项目启用。外部 PPT 辅助技能的固定来源与校验值在 references/presentations.md；已有对应能力可直接复用。所有选配共用五次提问预算。

## 日常用法

“请用 workbuddy-quality-kit，根据附件材料和参考稿制作会议 PPT。优先沿用用途相同的原页，保留能说明成果的原图，完成后查看放映效果，再交付可编辑文件。”

“请按 5.2 帮我精修附件第 3 页。保留已认可的页面，让重点和操作顺序在投影时一眼可见。”

若全局有同名旧版，把以上提示词中的技能名替换为“先读这份解压目录的 SKILL.md 和 references/presentations.md，再按它完成本次任务”。
