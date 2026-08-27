"""
Maya Batch Exporter
==================
Maya DCC 批量导出 + 命名规范工具

功能:
  - 扫描选中对象，自动生成标准导出名
  - 支持命名模式自定义 ({prefix}_{category}_{name}_{variant})
  - 预设驱动 FBX 导出 (UE5 / Unity / Custom)
  - 导出前预处理 (冻结变换 / 删除历史 / 居中轴心)
  - 批量导出进度反馈 + 结果日志
  - 可停靠 Maya 界面

安装:
  1. 将整个 maya_batch_exporter 文件夹复制到 Maya 脚本目录:
     Windows: %USERPROFILE%\\Documents\\maya\\scripts\\
     macOS:   ~/Library/Preferences/Autodesk/maya/scripts/
     Linux:   ~/maya/scripts/

  2. 在 Maya Script Editor 中执行:
     import maya_batch_exporter
     maya_batch_exporter.show()

  3. (可选) 添加到 Shelf:
     python("import maya_batch_exporter; maya_batch_exporter.show()")

版本: 1.0.0
作者: UnityEditorToolDeveloper
许可: MIT
"""

__version__ = "1.0.0"
__author__ = "UnityEditorToolDeveloper"

# 兼容性: 支持绝对导入 (Maya 2018) 和相对导入 (Maya 2022+)
# 相对导入优先，因为它能正确处理 Maya 的 sys.path 配置
try:
    from .main_window import show, BatchExporterWindow
    from .naming_engine import NamingEngine, NamingResult, NAMING_PRESETS
    from .fbx_exporter import FBXExporter, ExportResult, BatchExportReport
    from .presets import PresetManager
except (ImportError, ValueError):
    # 回退到绝对导入 (兼容独立运行)
    from main_window import show, BatchExporterWindow
    from naming_engine import NamingEngine, NamingResult, NAMING_PRESETS
    from fbx_exporter import FBXExporter, ExportResult, BatchExportReport
    from presets import PresetManager


def create_shelf_button(shelf_name="Custom", label="BatchExp",
                         tooltip="Maya Batch Exporter — 批量导出工具"):
    """
    在指定 Shelf 上创建工具按钮

    Args:
        shelf_name: Shelf 标签名 (如 "Custom", "Rendering")
        label: 按钮显示文字
        tooltip: 鼠标悬停提示
    """
    try:
        import maya.cmds as cmds
    except ImportError:
        print("[BatchExporter] Maya 环境不可用，无法创建 Shelf 按钮")
        return

    # 确保 Shelf 标签存在
    shelf_tabs = cmds.shelfTabLayout("ShelfLayout", query=True, childArray=True) or []
    if shelf_name not in [cmds.shelfTabLayout(tab, query=True, label=True)
                          for tab in shelf_tabs]:
        cmds.shelfLayout(shelf_name, parent="ShelfLayout")

    # 检查是否已有同名按钮
    children = cmds.shelfLayout(shelf_name, query=True, childArray=True) or []
    for child in children:
        if cmds.shelfButton(child, query=True, exists=True):
            if cmds.shelfButton(child, query=True, label=True) == label:
                cmds.deleteUI(child)

    # 创建按钮
    cmd = 'import maya_batch_exporter; maya_batch_exporter.show()'
    cmds.shelfButton(
        parent=shelf_name,
        label=label,
        annotation=tooltip,
        image="commandButton",
        command=cmd,
        sourceType="python",
        width=32,
        height=32,
    )
    print(f"[BatchExporter] Shelf 按钮已创建: {shelf_name} > {label}")


def add_menu_item():
    """在 Maya 菜单栏添加 Tools > Batch Exporter 菜单项"""
    try:
        import maya.cmds as cmds
    except ImportError:
        return

    menu_name = "batchExporterMenu"
    if cmds.menu(menu_name, exists=True):
        cmds.deleteUI(menu_name)

    cmds.menu(
        menu_name,
        parent="MayaWindow",
        label="Tools",
        tearOff=True,
    )
    cmds.menuItem(
        label="Batch Exporter",
        parent=menu_name,
        command='import maya_batch_exporter; maya_batch_exporter.show()',
        sourceType="python",
        annotation="打开 Maya Batch Exporter 批量导出工具",
    )
    print("[BatchExporter] 菜单已添加: Tools > Batch Exporter")
