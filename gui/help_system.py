from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.system_info import resource_root


@dataclass(frozen=True)
class HelpTopic:
    key: str
    title: str
    file_name: str
    fallback_text: str


HELP_TOPICS: dict[str, HelpTopic] = {
    "quick_start": HelpTopic(
        key="quick_start",
        title="快速引导",
        file_name="快速引导.txt",
        fallback_text=(
            "欢迎使用 影界 HDDE V0.3\n\n"
            "1. 添加图片或选择图片文件夹。\n"
            "2. 选择输出文件夹。\n"
            "3. 首次测试建议使用 fidelity 原图忠实增强模式。\n"
            "4. 点击开始处理并查看输出结果。\n\n"
            "软件不会覆盖原图，默认不添加角标。"
        ),
    ),
    "user_guide": HelpTopic(
        key="user_guide",
        title="使用说明",
        file_name="使用说明.txt",
        fallback_text="使用说明文件未找到。请检查 help/使用说明.txt 是否已随软件一起打包。",
    ),
    "faq": HelpTopic(
        key="faq",
        title="常见问题",
        file_name="FAQ.txt",
        fallback_text="常见问题文件未找到。请检查 help/FAQ.txt 是否已随软件一起打包。",
    ),
    "logs": HelpTopic(
        key="logs",
        title="日志位置说明",
        file_name="日志位置说明.txt",
        fallback_text="日志说明文件未找到。请检查 help/日志位置说明.txt 是否已随软件一起打包。",
    ),
}


def help_dir() -> Path:
    return resource_root() / "help"


def list_help_topics() -> list[HelpTopic]:
    """Return registered help topics in menu order."""
    return [
        HELP_TOPICS["quick_start"],
        HELP_TOPICS["user_guide"],
        HELP_TOPICS["faq"],
        HELP_TOPICS["logs"],
    ]


def read_help_topic(key: str) -> tuple[str, str]:
    topic = HELP_TOPICS[key]
    path = help_dir() / topic.file_name
    try:
        return topic.title, path.read_text(encoding="utf-8")
    except Exception:
        return topic.title, topic.fallback_text
