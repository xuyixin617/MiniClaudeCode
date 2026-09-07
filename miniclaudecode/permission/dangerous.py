"""高危危险命令检测 —— 正则匹配 20 类危险操作。

仅用于 bash 工具的"命令串"检测（也用于 write_file/edit_file 的路径参数检测）。
命中即视为高风险，需要更严格的确认流程。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DangerousPattern:
    id: str
    pattern: str
    description: str


# 20 类高危命令（正则，re.IGNORECASE 匹配）
DANGEROUS_PATTERNS: list[DangerousPattern] = [
    DangerousPattern("rm_recursive", r"\brm\s+(-\w*\s*)*r[fv]*\b", "递归删除目录"),
    DangerousPattern("rm_force", r"\brm\s+(-\w*\s*)*f\b", "强制删除文件"),
    DangerousPattern("rm_home", r"\brm\s+.*(~/|/home/|/Users/|\$HOME)", "删除家目录内容"),
    DangerousPattern("sudo", r"\bsudo\b", "提权执行"),
    DangerousPattern("su_root", r"\bsu\s+-?\s*root\b", "切换 root"),
    DangerousPattern("chmod_777", r"\bchmod\s+(-\w*\s*)*777\b", "赋予 777 全开放权限"),
    DangerousPattern("chown_system", r"\bchown\s+(-R\s+)?\S+\s+/(usr|etc|var|bin|lib)", "修改系统目录属主"),
    DangerousPattern("mkfs", r"\bmkfs\b", "格式化文件系统"),
    DangerousPattern("dd_device", r"\bdd\s+.*\bof=/dev/", "直接写块设备"),
    DangerousPattern("shutdown_reboot", r"\b(shutdown|reboot|halt|poweroff|init\s+0)\b", "关机/重启"),
    DangerousPattern("pipe_to_shell", r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", "下载脚本并直接执行"),
    DangerousPattern("git_push_force", r"\bgit\s+push\b.*(--force|--force-with-lease|:\s*\w+)", "强制推送/删除远程分支"),
    DangerousPattern("git_reset_hard", r"\bgit\s+reset\s+--hard\b", "硬重置丢弃提交"),
    DangerousPattern("git_clean", r"\bgit\s+clean\s+(-\w*\s*)*f", "强制清理未跟踪文件"),
    DangerousPattern("drop_database", r"\b(drop\s+(table|database)|truncate\s+table)\b", "删除数据库/表"),
    DangerousPattern("overwrite_system", r">\s*(/etc/|/usr/|/boot/|/bin/)", "覆写系统文件"),
    DangerousPattern("kill_all", r"\b(killall|pkill\s+-9|kill\s+-9\s+1)\b", "强制杀进程"),
    DangerousPattern("firewall_flush", r"\biptables\s+-F\b|\bufw\s+disable\b", "清空防火墙规则"),
    DangerousPattern("ssh_secret", r"\bcat\s+~?/\.(ssh|aws|gnupg)", "读取密钥/凭证"),
    DangerousPattern("env_secret", r"\b(export\s+)?(AWS_SECRET|API_KEY|TOKEN)\s*=", "导出敏感凭证"),
]


def detect_danger(command: str) -> list[DangerousPattern]:
    """返回命中的所有危险模式。"""
    hits: list[DangerousPattern] = []
    for p in DANGEROUS_PATTERNS:
        try:
            if re.search(p.pattern, command, re.IGNORECASE):
                hits.append(p)
        except re.error:
            continue
    return hits


def describe_danger(hits: list[DangerousPattern]) -> str:
    return "; ".join(f"{h.id}({h.description})" for h in hits)
