"""
导出预设管理 — 保存/加载/编辑 FBX 导出预设

预设存储位置: 用户主目录下 ~/.maya/batch_exporter/presets/
默认预设: UE5, Unity, Custom (随工具打包，不可删除)

每个预设包含:
- fbx_settings: FBX 导出选项 (ascii, triangulate, smooth_mesh, ...)
- preprocess: 导出前预处理 (freeze_transform, delete_history, center_pivot)
- naming: 命名规范 (preset, pattern)
- path_mapping: 路径映射 (subfolder_by_category, create_subfolders)
"""

import os
import json
import copy
from typing import Optional
from pathlib import Path


# ── 路径常量 ──────────────────────────────────────────────────

# 默认配置文件 (随工具打包)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.json"

# 用户预设目录
USER_PRESETS_DIR = Path.home() / ".maya" / "batch_exporter" / "presets"

# 内置预设名 (不可删除)
BUILTIN_PRESETS = {"UE5", "Unity", "Custom"}


class PresetManager:
    """
    预设管理器

    用法:
        pm = PresetManager()
        preset = pm.get_preset("UE5")
        pm.save_preset("MyTeam_UE5", custom_data)
        pm.list_presets()
    """

    def __init__(self):
        self._default_presets = self._load_defaults()
        self._ensure_user_dir()

    def _ensure_user_dir(self):
        """确保用户预设目录存在"""
        USER_PRESETS_DIR.mkdir(parents=True, exist_ok=True)

    def _load_defaults(self) -> dict:
        """加载默认配置文件"""
        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise RuntimeError(f"无法加载默认配置文件: {DEFAULT_CONFIG_PATH}\n错误: {e}")

    def list_presets(self) -> list:
        """
        列出所有可用预设 (内置 + 用户自定义)

        Returns:
            list of {"name": str, "description": str, "builtin": bool}
        """
        presets = []

        # 内置预设
        for name, data in self._default_presets.items():
            presets.append({
                "name": name,
                "description": data.get("description", ""),
                "builtin": True,
            })

        # 用户自定义预设
        if USER_PRESETS_DIR.exists():
            for f in USER_PRESETS_DIR.glob("*.json"):
                preset_name = f.stem
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    presets.append({
                        "name": preset_name,
                        "description": data.get("description", ""),
                        "builtin": False,
                    })
                except (json.JSONDecodeError, IOError):
                    continue

        return presets

    def get_preset(self, name: str) -> Optional[dict]:
        """
        获取预设完整数据

        优先级: 用户自定义 > 内置默认
        """
        # 检查用户自定义预设
        user_path = USER_PRESETS_DIR / f"{name}.json"
        if user_path.exists():
            try:
                with open(user_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # 回退到内置预设
        if name in self._default_presets:
            return copy.deepcopy(self._default_presets[name])

        return None

    def save_preset(self, name: str, data: dict) -> bool:
        """
        保存预设 (仅支持用户自定义预设，不允许覆盖内置预设)

        Args:
            name: 预设名
            data: 预设数据 dict

        Returns:
            True 如果保存成功
        """
        if not name or not name.strip():
            return False

        # 清理预设名 (只允许字母数字下划线)
        import re
        clean_name = re.sub(r"[^\w\-]", "_", name.strip())

        # 不允许覆盖内置预设
        if clean_name in BUILTIN_PRESETS:
            # 自动加后缀
            clean_name = f"{clean_name}_Custom"

        data["description"] = data.get("description", f"用户自定义预设: {clean_name}")

        file_path = USER_PRESETS_DIR / f"{clean_name}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except IOError:
            return False

    def delete_preset(self, name: str) -> bool:
        """
        删除用户自定义预设 (内置预设不可删除)

        Returns:
            True 如果删除成功
        """
        if name in BUILTIN_PRESETS:
            return False

        file_path = USER_PRESETS_DIR / f"{name}.json"
        if file_path.exists():
            try:
                file_path.unlink()
                return True
            except IOError:
                return False
        return False

    def duplicate_preset(self, source: str, target: str) -> bool:
        """
        复制预设 (从已有预设创建副本，方便编辑)

        Args:
            source: 源预设名
            target: 目标预设名

        Returns:
            True 如果复制成功
        """
        preset = self.get_preset(source)
        if preset is None:
            return False

        return self.save_preset(target, preset)

    def validate_preset(self, data: dict) -> tuple:
        """
        验证预设数据是否完整有效

        Returns:
            (is_valid: bool, issues: list[str])
        """
        issues = []

        # 检查必需字段
        required_sections = ["fbx_settings", "preprocess", "naming", "path_mapping"]
        for section in required_sections:
            if section not in data:
                issues.append(f"缺少必需字段: {section}")

        if not issues:
            # 检查 fbx_settings
            fbx = data.get("fbx_settings", {})
            if not isinstance(fbx.get("triangulate"), bool):
                issues.append("fbx_settings.triangulate 应为布尔值")
            if fbx.get("up_axis", "y") not in ("y", "z"):
                issues.append("fbx_settings.up_axis 应为 'y' 或 'z'")

            # 检查 naming
            naming = data.get("naming", {})
            pattern = naming.get("pattern", "")
            if not pattern:
                issues.append("naming.pattern 不能为空")

        return len(issues) == 0, issues
