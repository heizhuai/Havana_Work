"""
FBX 批量导出核心 — 预设驱动导出、进度反馈、结果日志

支持:
- 逐个导出选中对象为独立 FBX 文件
- 预设驱动的 FBX 设置 (UE5 / Unity / Custom)
- 导出前预处理 (冻结变换 / 删除历史 / 居中轴心)
- 路径映射与自动子目录
- 进度回调
- 导出结果日志

依赖: Maya cmds / mel (运行时导入，支持 Maya 2022+ Python3)
"""

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# Maya 模块延迟导入 — 允许在非 Maya 环境中导入此文件进行代码审查
try:
    import maya.cmds as cmds
    import maya.mel as mel
    MAYA_AVAILABLE = True
except ImportError:
    cmds = None
    mel = None
    MAYA_AVAILABLE = False


# ── 导出结果数据类 ────────────────────────────────────────────

@dataclass
class ExportResult:
    """单个对象的导出结果"""
    object_name: str
    export_name: str
    file_path: str
    success: bool
    elapsed: float = 0.0
    error: str = ""


@dataclass
class BatchExportReport:
    """批量导出汇总报告"""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list = field(default_factory=list)
    total_elapsed: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.succeeded / self.total * 100


# ── FBX 导出器 ────────────────────────────────────────────────

class FBXExporter:
    """
    FBX 批量导出器

    工作流:
    1. 设置 FBX 导出选项 (从预设加载)
    2. 对每个选中对象:
       a. 预处理 (可选: 冻结变换, 删除历史, 居中轴心)
       b. 生成导出路径
       c. 执行 FBX 导出
       d. 记录结果
    3. 汇总报告
    """

    def __init__(self):
        if not MAYA_AVAILABLE:
            raise RuntimeError(
                "FBXExporter 需要 Maya 环境 (maya.cmds / maya.mel 不可用)\n"
                "请在 Maya 的 Script Editor 或 Python 环境中运行此工具。"
            )

    # ── FBX 选项设置 ──────────────────────────────────────────

    def apply_fbx_settings(self, settings: dict):
        """
        根据 settings dict 设置 Maya FBX 导出选项

        settings keys:
            ascii: bool — 二进制 vs ASCII
            triangulate: bool
            smooth_mesh: bool
            tangent_space: bool
            bake_animation: bool
            smoothing_groups: bool
            up_axis: str — "y" or "z"
            units: str — "cm", "m", "in"
            embed_media: bool
            export_materials: bool
            export_textures: bool
            axis_conversion: bool
            fbx_version: str — "FBX 2020", "FBX 2014", etc.
        """
        _safe_eval('FBXExportInAscii -v {}'.format(
            "true" if settings.get("ascii", False) else "false"
        ))

        _safe_eval('FBXExportTriangulate -v {}'.format(
            "true" if settings.get("triangulate", True) else "false"
        ))

        _safe_eval('FBXExportSmoothMesh -v {}'.format(
            "true" if settings.get("smooth_mesh", True) else "false"
        ))

        _safe_eval('FBXExportTangents -v {}'.format(
            "true" if settings.get("tangent_space", True) else "false"
        ))

        _safe_eval('FBXExportBakeComplexAnimation -v {}'.format(
            "true" if settings.get("bake_animation", False) else "false"
        ))

        _safe_eval('FBXExportSmoothingGroups -v {}'.format(
            "true" if settings.get("smoothing_groups", True) else "false"
        ))

        _safe_eval('FBXExportEmbeddedTexturesImport -v {}'.format(
            "true" if settings.get("embed_media", False) else "false"
        ))

        _safe_eval('FBXExportGenerateLog -v false')

        # 轴向设置
        up_axis = settings.get("up_axis", "y").lower()
        if up_axis == "z":
            _safe_eval('FBXExportUpAxis "z"')
        else:
            _safe_eval('FBXExportUpAxis "y"')

        # 单位
        units = settings.get("units", "cm")
        unit_map = {"cm": "cm", "m": "m", "in": "in", "ft": "ft"}
        if units in unit_map:
            _safe_eval('FBXExportUnits -v {}'.format(unit_map[units]))

    # ── 预处理 ────────────────────────────────────────────────

    def preprocess_object(self, obj: str, options: dict):
        """
        导出前预处理

        options keys:
            freeze_transform: bool — 冻结变换 (MakeIdentity)
            delete_history: bool — 删除构建历史
            center_pivot: bool — 居中轴心
            triangulate: bool — 三角化网格 (Maya 端)
        """
        if options.get("freeze_transform", True):
            try:
                cmds.makeIdentity(obj, apply=True, t=1, r=1, s=1, n=0)
            except Exception:
                pass

        if options.get("delete_history", True):
            try:
                cmds.delete(obj, constructionHistory=True)
            except Exception:
                pass

        if options.get("center_pivot", False):
            try:
                cmds.xform(obj, centerPivots=True)
            except Exception:
                pass

    # ── 单个导出 ──────────────────────────────────────────────

    def export_single(self, obj: str, export_name: str,
                      output_dir: str, settings: dict,
                      preprocess: Optional[dict] = None) -> ExportResult:
        """
        导出单个对象为 FBX

        Args:
            obj: Maya 对象名
            export_name: 导出文件名 (不含扩展名)
            output_dir: 输出目录
            settings: FBX 设置 dict
            preprocess: 预处理选项 dict (可选)

        Returns:
            ExportResult
        """
        start_time = time.time()
        file_path = os.path.join(output_dir, export_name + ".fbx")

        try:
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)

            # 预处理
            if preprocess:
                self.preprocess_object(obj, preprocess)

            # 选中对象 (含其子层级)
            cmds.select(obj, replace=True)

            # 应用 FBX 设置
            self.apply_fbx_settings(settings)

            # 导出
            cmds.file(
                file_path,
                exportSelected=True,
                type="FBX export",
                force=True,
                options="v=0;",
                pr=False,  # 不弹窗
            )

            elapsed = time.time() - start_time
            return ExportResult(
                object_name=obj,
                export_name=export_name,
                file_path=file_path,
                success=True,
                elapsed=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            return ExportResult(
                object_name=obj,
                export_name=export_name,
                file_path=file_path,
                success=False,
                elapsed=elapsed,
                error=str(e),
            )

    # ── 批量导出 ──────────────────────────────────────────────

    def batch_export(self, export_items: list,
                     output_dir: str, settings: dict,
                     preprocess: Optional[dict] = None,
                     subfolder_by_category: bool = True,
                     progress_callback: Optional[Callable[[int, int, str], None]] = None
                     ) -> BatchExportReport:
        """
        批量导出多个对象

        Args:
            export_items: list of (obj_name, export_name, category) tuples
                         category 用于子目录分组 (如果 subfolder_by_category=True)
            output_dir: 基础输出目录
            settings: FBX 设置 dict
            preprocess: 预处理选项 (可选)
            subfolder_by_category: 是否按 category 创建子目录
            progress_callback: callback(current, total, current_name)

        Returns:
            BatchExportReport
        """
        report = BatchExportReport(total=len(export_items))
        batch_start = time.time()

        # 保存当前选择，导出结束后恢复
        try:
            original_selection = cmds.ls(selection=True)
        except Exception:
            original_selection = []

        for i, item in enumerate(export_items):
            obj_name = item[0]
            export_name = item[1]
            category = item[2] if len(item) > 2 else ""

            # 确定输出目录
            if subfolder_by_category and category:
                target_dir = os.path.join(output_dir, category)
            else:
                target_dir = output_dir

            # 进度回调
            if progress_callback:
                progress_callback(i, report.total, export_name)

            # 执行导出
            result = self.export_single(
                obj=obj_name,
                export_name=export_name,
                output_dir=target_dir,
                settings=settings,
                preprocess=preprocess,
            )

            report.results.append(result)
            if result.success:
                report.succeeded += 1
            else:
                report.failed += 1

        # 最终进度回调
        if progress_callback:
            progress_callback(report.total, report.total, "完成")

        # 恢复选择
        try:
            if original_selection:
                cmds.select(original_selection, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:
            pass

        report.total_elapsed = time.time() - batch_start
        return report


# ── 辅助函数 ──────────────────────────────────────────────────

def _safe_eval(mel_command: str):
    """
    安全执行 mel 命令，忽略特定 FBX 选项不存在的错误
    (不同 Maya 版本的 FBX 插件支持的命令略有差异)
    """
    try:
        mel.eval(mel_command)
    except Exception:
        pass  # 选项不存在时静默跳过，不阻断导出流程


def get_selected_exportable_objects() -> list:
    """
    获取当前选中可导出的对象列表

    返回 list of dict:
        [{"name": str, "type": str, "path": str, "children": [str]}, ...]
    """
    if not MAYA_AVAILABLE:
        return []

    results = []

    # 获取选中的 transform 节点
    selection = cmds.ls(selection=True, long=True) or []

    for obj in selection:
        # 获取对象类型
        shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []
        if not shapes:
            # 可能是组节点，检查子级
            children = cmds.listRelatives(obj, children=True, fullPath=True) or []
            mesh_children = [c for c in children if cmds.nodeType(c) == "mesh"
                           or (cmds.listRelatives(c, shapes=True, fullPath=True))]
            if mesh_children:
                results.append({
                    "name": obj.split("|")[-1],
                    "path": obj,
                    "type": "group",
                    "children": mesh_children,
                })
        else:
            shape_type = cmds.nodeType(shapes[0])
            obj_type = "skeletal" if shape_type == "mesh" and cmds.listConnections(
                obj, type="skinCluster"
            ) else "mesh"
            results.append({
                "name": obj.split("|")[-1],
                "path": obj,
                "type": obj_type,
                "children": [],
            })

    return results
