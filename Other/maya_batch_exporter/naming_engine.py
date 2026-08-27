"""
命名规则引擎 — 模式匹配、自动命名、命名验证

支持的命名模式: {prefix}_{category}_{name}_{variant}
示例:
  SM_Rock_Desert_Boulder_01
  SK_Prop_Character_NPC_02
  T_Rock_Desert_BC

用法:
    engine = NamingEngine(pattern="{prefix}_{category}_{name}_{variant}")
    result = engine.generate_name("pCube1", obj_info={
        "type": "mesh",
        "hierarchy": ["Environment", "Rocks", "Boulder"],
        "custom_attrs": {"category": "Desert"}
    })
    # result.name = "SM_Rock_Desert_Boulder_01"
    # result.valid = True
    # result.warnings = []
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── 预设命名规范 ──────────────────────────────────────────────

NAMING_PRESETS = {
    "UE5": {
        "description": "Unreal Engine 5 命名规范",
        "pattern": "{prefix}_{category}_{name}_{variant}",
        "prefixes": {
            "static_mesh": "SM",
            "skeletal_mesh": "SK",
            "texture": "T",
            "material": "M",
            "material_instance": "MI",
        },
        "rules": {
            "case": "PascalCase",
            "separator": "_",
            "no_spaces": True,
            "max_length": 64,
            "allowed_chars": r"[A-Za-z0-9_\-]",
        },
    },
    "Unity": {
        "description": "Unity 命名规范",
        "pattern": "{prefix}_{category}_{name}_{variant}",
        "prefixes": {
            "static_mesh": "M",
            "skeletal_mesh": "SK",
            "texture": "T",
            "material": "Mat",
            "material_instance": "MI",
        },
        "rules": {
            "case": "PascalCase",
            "separator": "_",
            "no_spaces": True,
            "max_length": 128,
            "allowed_chars": r"[A-Za-z0-9_\-]",
        },
    },
    "Custom": {
        "description": "自定义命名规范",
        "pattern": "{prefix}_{name}_{variant}",
        "prefixes": {
            "static_mesh": "SM",
            "skeletal_mesh": "SK",
        },
        "rules": {
            "case": "PascalCase",
            "separator": "_",
            "no_spaces": True,
            "max_length": 64,
            "allowed_chars": r"[A-Za-z0-9_\-]",
        },
    },
}


# ── 命名结果数据类 ────────────────────────────────────────────

@dataclass
class NamingResult:
    """单个对象的命名结果"""
    original_name: str
    generated_name: str
    valid: bool = True
    warnings: list = field(default_factory=list)
    tokens: dict = field(default_factory=dict)


# ── 命名引擎 ──────────────────────────────────────────────────

class NamingEngine:
    """
    命名规则引擎

    根据模式和对象信息生成标准化导出名称，支持:
    - 模式匹配与 token 替换
    - 从对象名/层级/自定义属性中提取信息
    - 命名验证（长度、字符集、大小写）
    - 预设规范加载
    """

    TOKEN_PATTERN = re.compile(r"\{(\w+)\}")

    def __init__(self, pattern: str = "{prefix}_{category}_{name}_{variant}",
                 preset_name: str = "UE5"):
        self.pattern = pattern
        self.preset = NAMING_PRESETS.get(preset_name, NAMING_PRESETS["UE5"])
        self.prefixes = self.preset.get("prefixes", {})
        self.rules = self.preset.get("rules", {})

    def _extract_tokens(self, obj_name: str, obj_info: dict) -> dict:
        """
        从对象名、层级和自定义属性中提取 token 值

        提取策略（按优先级）:
        1. custom_attrs 中显式指定的值
        2. 从对象名中解析已有部分
        3. 从层级路径中推断
        4. 使用默认值
        """
        tokens = {}
        custom = obj_info.get("custom_attrs", {})

        # prefix: 根据对象类型推断
        obj_type = obj_info.get("type", "mesh")
        tokens["prefix"] = custom.get("prefix", self.prefixes.get(
            "skeletal_mesh" if obj_type == "skeletal" else "static_mesh", "SM"
        ))

        # category: 优先用 custom_attrs，其次从层级第1层推断
        hierarchy = obj_info.get("hierarchy", [])
        tokens["category"] = custom.get("category", hierarchy[0] if hierarchy else "Default")

        # name: 从对象名中提取（去除命名空间前缀和类型标识）
        clean_name = obj_name.split(":")[-1]  # 去除 namespace:前缀
        # 去除常见 Maya 类型前缀 (pCube, pSphere, mesh_, grp_)
        # 使用 lookahead 只移除 p，不吞掉后面的字母
        clean_name = re.sub(r"^(p(?=[A-Z])|mesh_|grp_)", "", clean_name)
        tokens["name"] = custom.get("name", clean_name or "unnamed")

        # variant: 自定义属性或递增序号
        variant = custom.get("variant", "")
        if not variant:
            index = obj_info.get("index", 1)
            variant = f"{index:02d}"
        tokens["variant"] = variant

        return tokens

    def _apply_case(self, value: str, case_rule: str) -> str:
        """根据大小写规则处理字符串"""
        if case_rule == "PascalCase":
            # 分割后首字母大写
            parts = re.split(r"[_\-\s]+", value)
            return "".join(p.capitalize() for p in parts if p)
        elif case_rule == "lowercase":
            return value.lower().replace(" ", "_")
        elif case_rule == "UPPERCASE":
            return value.upper().replace(" ", "_")
        return value

    def _sanitize(self, value: str) -> str:
        """清理非法字符"""
        allowed = self.rules.get("allowed_chars", r"[A-Za-z0-9_\-]")
        pattern = f"[^{allowed[1:-1]}]"  # 去除方括号
        cleaned = re.sub(pattern, "", value)
        return cleaned

    def generate_name(self, obj_name: str, obj_info: Optional[dict] = None) -> NamingResult:
        """
        为单个对象生成标准导出名称

        Args:
            obj_name: Maya 中的对象名 (可能含命名空间)
            obj_info: 对象信息 dict，包含:
                - type: "mesh" | "skeletal" | "group"
                - hierarchy: list[str] 层级路径
                - custom_attrs: dict 用户自定义属性
                - index: int 在批量列表中的序号

        Returns:
            NamingResult 包含生成名称、验证状态、警告
        """
        obj_info = obj_info or {}
        warnings = []

        # 提取 tokens
        tokens = self._extract_tokens(obj_name, obj_info)

        # 应用大小写规则 — prefix 保持原样 (SM, SK, T, M 等已是正确格式)
        case_rule = self.rules.get("case", "PascalCase")
        for key in tokens:
            if key == "prefix":
                continue  # 前缀不参与大小写转换
            tokens[key] = self._apply_case(tokens[key], case_rule)

        # 清理非法字符
        for key in tokens:
            tokens[key] = self._sanitize(tokens[key])

        # 替换模式中的 token
        result_name = self.pattern
        for match in self.TOKEN_PATTERN.finditer(self.pattern):
            token_name = match.group(1)
            value = tokens.get(token_name, "")
            result_name = result_name.replace(match.group(0), value)

        # 清理连续分隔符和首尾分隔符
        separator = self.rules.get("separator", "_")
        result_name = re.sub(f"{re.escape(separator)}+", separator, result_name)
        result_name = result_name.strip(separator)

        # 验证
        valid = True
        max_length = self.rules.get("max_length", 64)
        if len(result_name) > max_length:
            warnings.append(f"名称超过最大长度限制 ({len(result_name)}/{max_length})")
            # 截断而非报错，保留有效部分
            result_name = result_name[:max_length].rstrip(separator)

        if self.rules.get("no_spaces", True) and " " in result_name:
            result_name = result_name.replace(" ", "_")
            warnings.append("发现空格，已替换为下划线")

        # 检查是否为空
        if not result_name or result_name == separator:
            valid = False
            warnings.append("生成的名称为空，请检查模式和对象信息")

        # 检查是否以数字开头（某些引擎不允许）
        if result_name and result_name[0].isdigit():
            warnings.append("名称以数字开头，某些引擎可能不接受")

        return NamingResult(
            original_name=obj_name,
            generated_name=result_name,
            valid=valid,
            warnings=warnings,
            tokens=tokens,
        )

    def validate_name(self, name: str) -> tuple:
        """
        验证单个名称是否符合规范

        Returns:
            (is_valid: bool, issues: list[str])
        """
        issues = []

        if not name:
            return False, ["名称为空"]

        if self.rules.get("no_spaces", True) and " " in name:
            issues.append("名称包含空格")

        max_length = self.rules.get("max_length", 64)
        if len(name) > max_length:
            issues.append(f"名称超过最大长度 ({len(name)}/{max_length})")

        allowed = self.rules.get("allowed_chars", r"[A-Za-z0-9_\-]")
        invalid_chars = set(re.sub(allowed, "", name))
        if invalid_chars:
            issues.append(f"包含非法字符: {', '.join(sorted(invalid_chars))}")

        if name[0].isdigit():
            issues.append("名称以数字开头")

        return len(issues) == 0, issues

    def batch_generate(self, objects: list) -> list:
        """
        批量生成名称

        Args:
            objects: list of (obj_name, obj_info) tuples

        Returns:
            list of NamingResult
        """
        results = []
        for i, item in enumerate(objects):
            if isinstance(item, str):
                obj_name = item
                obj_info = {"index": i + 1}
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                obj_name, obj_info = item
                obj_info = {**obj_info, "index": i + 1}
            else:
                obj_name = str(item)
                obj_info = {"index": i + 1}

            results.append(self.generate_name(obj_name, obj_info))

        return results
