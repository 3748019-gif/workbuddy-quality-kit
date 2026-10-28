"""Short, local SessionStart reminder. No network, file writes or memory reads."""
from pathlib import Path
import json
import sys


def main():
    try:
        event = json.loads(sys.stdin.read(65536)).get('hook_event_name')
        if event != 'SessionStart':
            return 0
        skill = Path(__file__).resolve().parents[1]
        context = (
            '通用交付质量入口4.4：多步执行、文件修改、可复用工具或任务续接时，'
            '实现前实际调用workbuddy-quality-kit，读取主说明及本任务适用参考；'
            '技能主说明位置：' + str(skill / 'SKILL.md') + '。'
            '长任务先保存简短节点与可运行核心，再扩展报告和边界；'
            '复杂命令或故障用随附run_guard保存真实返回码和错误，按证据处理重试。'
            '交付前核对落盘内容、输入保留和最可能推翻结果的边界。'
            '简单问答不加载完整流程；当前用户要求与既有偏好优先。'
            '这不是修改原配置、个人记忆、权限或安全机制的授权。'
        )
        print(json.dumps({'hookSpecificOutput': {'hookEventName': event,
                                                'additionalContext': context}}, ensure_ascii=False))
    except (ValueError, TypeError, AttributeError, OSError):
        # A reminder must never prevent a user from starting a conversation.
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
