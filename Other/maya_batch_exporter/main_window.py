"""
Maya Batch Exporter — PySide2/6 主窗口 UI

功能:
- 扫描 Maya 选中对象，自动生成导出名称
- 可编辑导出名称和分类
- 预设驱动 FBX 导出设置 (UE5 / Unity / Custom)
- 批量导出进度反馈
- 导出结果日志

嵌入方式: Maya workspaceControl (可停靠) 或 独立窗口
兼容: PySide2 (Maya 2020-2024) / PySide6 (Maya 2025+)
"""

import os
import sys

# ── PySide2 / PySide6 自动检测 ────────────────────────────────
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    PYSIDE_VERSION = 2

# ── Maya 模块延迟导入 ─────────────────────────────────────────
try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omUI
    try:
        from shiboken6 import wrapInstance
    except ImportError:
        from shiboken2 import wrapInstance
    MAYA_AVAILABLE = True
except ImportError:
    cmds = None
    omUI = None
    wrapInstance = None
    MAYA_AVAILABLE = False

# ── 本工具模块 ────────────────────────────────────────────────
from .naming_engine import NamingEngine, NAMING_PRESETS
from .fbx_exporter import FBXExporter, get_selected_exportable_objects
from .presets import PresetManager


# ── 常量 ──────────────────────────────────────────────────────

WINDOW_TITLE = "Maya Batch Exporter"
WORKSPACE_CONTROL_NAME = "batchExporterWorkspaceControl"

# UI 尺寸
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 640

# 颜色 (dark theme friendly)
COLOR_BG = "#2D2D2D"
COLOR_TEXT = "#E0E0E0"
COLOR_SUCCESS = "#4CAF50"
COLOR_WARNING = "#FF9800"
COLOR_ERROR = "#F44336"
COLOR_TABLE_ALT_ROW = "#333333"


class BatchExporterWindow(QtWidgets.QWidget):
    """
    批量导出器主窗口

    布局:
    ┌─ 工具栏: [刷新选择] [全选] [取消全选] ─────────────┐
    ├─ 对象列表表格 (可编辑导出名/分类) ──────────────────┤
    ├─ 命名设置: 模式输入 / 命名预设下拉 ────────────────┤
    ├─ 导出设置: 预设下拉 / 输出目录 / 预处理选项 ───────┤
    ├─ [批量导出] 按钮 + 进度条 ────────────────────────┤
    └─ 导出日志 (只读文本区) ───────────────────────────┘
    """

    # 信号: 导出完成
    export_complete = QtCore.Signal(object)  # BatchExportReport

    def __init__(self, parent=None):
        super().__init__(parent)

        # 核心引擎
        self._naming_engine = NamingEngine()
        self._preset_manager = PresetManager()
        self._fbx_exporter = None  # 延迟初始化 (需要 Maya 环境)

        # 当前对象列表: [{"obj_name": str, "path": str, "type": str,
        #                "export_name": str, "category": str, "selected": bool}]
        self._objects = []

        # 上次输出目录
        self._last_output_dir = os.path.expanduser("~")

        # 构建 UI
        self._build_ui()
        self._connect_signals()
        self._load_presets()

        # 初始扫描
        if MAYA_AVAILABLE:
            self.refresh_selection()

    # ── UI 构建 ────────────────────────────────────────────────

    def _build_ui(self):
        """构建完整 UI 布局"""
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── 工具栏 ──
        toolbar = QtWidgets.QHBoxLayout()
        self._btn_refresh = QtWidgets.QPushButton("刷新选择")
        self._btn_select_all = QtWidgets.QPushButton("全选")
        self._btn_deselect_all = QtWidgets.QPushButton("取消全选")
        self._btn_auto_name = QtWidgets.QPushButton("自动命名")

        toolbar.addWidget(self._btn_refresh)
        toolbar.addWidget(self._btn_select_all)
        toolbar.addWidget(self._btn_deselect_all)
        toolbar.addStretch()
        toolbar.addWidget(self._btn_auto_name)
        main_layout.addLayout(toolbar)

        # ── 对象列表表格 ──
        self._table = QtWidgets.QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["导出", "对象名", "导出名", "分类", "状态"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)

        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)

        table_group = QtWidgets.QGroupBox("对象列表")
        table_layout = QtWidgets.QVBoxLayout(table_group)
        table_layout.addWidget(self._table)
        main_layout.addWidget(table_group, stretch=3)

        # ── 命名设置 ──
        naming_group = QtWidgets.QGroupBox("命名设置")
        naming_layout = QtWidgets.QFormLayout(naming_group)

        self._input_pattern = QtWidgets.QLineEdit("{prefix}_{category}_{name}_{variant}")
        self._input_pattern.setToolTip(
            "命名模式，可用 token:\n"
            "  {prefix} - 类型前缀 (SM, SK, T, M...)\n"
            "  {category} - 分类名\n"
            "  {name} - 对象名\n"
            "  {variant} - 变体/序号"
        )
        naming_layout.addRow("命名模式:", self._input_pattern)

        self._combo_naming_preset = QtWidgets.QComboBox()
        for name in NAMING_PRESETS:
            self._combo_naming_preset.addItem(name)
        self._combo_naming_preset.setCurrentText("UE5")
        naming_layout.addRow("命名预设:", self._combo_naming_preset)

        # 命名开关: 不勾选时, 扫描选中对象直接用 obj_name 作为 export_name
        #           勾选时, 调命名引擎按 pattern 生成 export_name
        self._chk_auto_naming = QtWidgets.QCheckBox("扫描时应用自动命名 (默认用对象原名)")
        self._chk_auto_naming.setChecked(False)  # 默认不用, 保留用户已命名
        naming_layout.addRow("", self._chk_auto_naming)

        main_layout.addWidget(naming_group)

        # ── 导出设置 ──
        export_group = QtWidgets.QGroupBox("导出设置")
        export_layout = QtWidgets.QVBoxLayout(export_group)

        # 预设 + 输出目录行
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("导出预设:"))

        self._combo_export_preset = QtWidgets.QComboBox()
        preset_row.addWidget(self._combo_export_preset, stretch=1)

        preset_row.addSpacing(12)
        preset_row.addWidget(QtWidgets.QLabel("输出目录:"))

        self._input_output_dir = QtWidgets.QLineEdit()
        self._input_output_dir.setPlaceholderText("选择输出目录...")
        preset_row.addWidget(self._input_output_dir, stretch=2)

        self._btn_browse = QtWidgets.QPushButton("浏览...")
        preset_row.addWidget(self._btn_browse)

        export_layout.addLayout(preset_row)

        # 预处理选项
        preprocess_row = QtWidgets.QHBoxLayout()
        self._chk_freeze = QtWidgets.QCheckBox("冻结变换")
        self._chk_freeze.setChecked(True)
        self._chk_delete_history = QtWidgets.QCheckBox("删除历史")
        self._chk_delete_history.setChecked(True)
        self._chk_center_pivot = QtWidgets.QCheckBox("居中轴心")
        self._chk_subfolder = QtWidgets.QCheckBox("按分类创建子目录")
        self._chk_subfolder.setChecked(True)

        preprocess_row.addWidget(self._chk_freeze)
        preprocess_row.addWidget(self._chk_delete_history)
        preprocess_row.addWidget(self._chk_center_pivot)
        preprocess_row.addStretch()
        preprocess_row.addWidget(self._chk_subfolder)
        export_layout.addLayout(preprocess_row)

        main_layout.addWidget(export_group)

        # ── 导出按钮 + 进度条 ──
        export_btn_row = QtWidgets.QHBoxLayout()
        self._btn_export = QtWidgets.QPushButton("批量导出")
        self._btn_export.setMinimumHeight(36)
        font = self._btn_export.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._btn_export.setFont(font)

        export_btn_row.addWidget(self._btn_export)
        main_layout.addLayout(export_btn_row)

        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setVisible(False)
        main_layout.addWidget(self._progress_bar)

        self._lbl_progress = QtWidgets.QLabel("")
        self._lbl_progress.setStyleSheet(f"color: {COLOR_TEXT};")
        main_layout.addWidget(self._lbl_progress)

        # ── 导出日志 ──
        log_group = QtWidgets.QGroupBox("导出日志")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self._log_text = QtWidgets.QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setStyleSheet(
            f"QTextEdit {{ background-color: {COLOR_BG}; "
            f"color: {COLOR_TEXT}; font-family: Consolas, monospace; }}"
        )
        log_layout.addWidget(self._log_text)

        # 清除日志按钮
        log_btn_row = QtWidgets.QHBoxLayout()
        self._btn_clear_log = QtWidgets.QPushButton("清除日志")
        log_btn_row.addStretch()
        log_btn_row.addWidget(self._btn_clear_log)
        log_layout.addLayout(log_btn_row)

        main_layout.addWidget(log_group, stretch=1)

    # ── 信号连接 ──────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_refresh.clicked.connect(self.refresh_selection)
        self._btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        self._btn_deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        self._btn_auto_name.clicked.connect(self.auto_generate_names)
        self._btn_browse.clicked.connect(self._browse_output_dir)
        self._btn_export.clicked.connect(self._on_export_clicked)
        self._btn_clear_log.clicked.connect(self._log_text.clear)

        self._combo_naming_preset.currentTextChanged.connect(self._on_naming_preset_changed)
        self._combo_export_preset.currentTextChanged.connect(self._on_export_preset_changed)

        self._input_pattern.textChanged.connect(self.auto_generate_names)

        # 表格编辑信号
        self._table.cellChanged.connect(self._on_table_cell_changed)

    # ── 预设加载 ──────────────────────────────────────────────

    def _load_presets(self):
        """加载导出预设到下拉框"""
        self._combo_export_preset.blockSignals(True)
        self._combo_export_preset.clear()

        presets = self._preset_manager.list_presets()
        for p in presets:
            label = f"{p['name']}" + (" (内置)" if p["builtin"] else " (自定义)")
            self._combo_export_preset.addItem(label, p["name"])

        self._combo_export_preset.blockSignals(False)

        # 触发预设更新
        self._on_export_preset_changed()

    # ── 对象列表 ──────────────────────────────────────────────

    def refresh_selection(self):
        """扫描当前 Maya 选择，刷新对象列表"""
        if not MAYA_AVAILABLE:
            self._append_log("⚠ Maya 环境不可用，无法扫描选择", "warning")
            return

        objects = get_selected_exportable_objects()
        self._objects = []

        for i, obj in enumerate(objects):
            # 默认 export_name 直接用对象原名 (不破坏已命名资产)
            # 只有勾选"自动命名"时才调命名引擎覆盖
            export_name = obj["name"]
            category = "Default"

            if self._chk_auto_naming.isChecked():
                # 用命名引擎生成默认名称
                naming_result = self._naming_engine.generate_name(
                    obj["name"],
                    obj_info={
                        "type": obj["type"],
                        "hierarchy": [],
                        "index": i + 1,
                    }
                )
                export_name = naming_result.generated_name
                category = naming_result.tokens.get("category", "Default")

            self._objects.append({
                "obj_name": obj["name"],
                "path": obj["path"],
                "type": obj["type"],
                "export_name": export_name,
                "category": category,
                "selected": True,
            })

        self._populate_table()
        count = len(self._objects)
        self._append_log(f"扫描完成: 选中 {count} 个可导出对象", "info")

    def _populate_table(self):
        """填充对象列表表格"""
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for i, obj in enumerate(self._objects):
            self._table.insertRow(i)

            # Checkbox
            chk = QtWidgets.QCheckBox()
            chk.setChecked(obj["selected"])
            chk_widget = QtWidgets.QWidget()
            chk_layout = QtWidgets.QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(QtCore.Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(i, 0, chk_widget)

            # 对象名 (只读)
            name_item = QtWidgets.QTableWidgetItem(obj["obj_name"])
            name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self._table.setItem(i, 1, name_item)

            # 导出名 (可编辑)
            export_item = QtWidgets.QTableWidgetItem(obj["export_name"])
            self._table.setItem(i, 2, export_item)

            # 分类 (可编辑)
            cat_item = QtWidgets.QTableWidgetItem(obj["category"])
            self._table.setItem(i, 3, cat_item)

            # 状态 (验证结果)
            valid, issues = self._naming_engine.validate_name(obj["export_name"])
            status_text = "OK" if valid else "WARNING"
            status_item = QtWidgets.QTableWidgetItem(status_text)
            status_color = COLOR_SUCCESS if valid else COLOR_WARNING
            status_item.setForeground(QtGui.QColor(status_color))
            self._table.setItem(i, 4, status_item)

        self._table.blockSignals(False)

    def _on_table_cell_changed(self, row, col):
        """表格单元格编辑回调"""
        if col == 2:  # 导出名被编辑
            item = self._table.item(row, 2)
            if item and row < len(self._objects):
                self._objects[row]["export_name"] = item.text()
                # 验证新名称
                valid, issues = self._naming_engine.validate_name(item.text())
                status_item = self._table.item(row, 4)
                if status_item:
                    status_item.setText("OK" if valid else "WARNING")
                    status_item.setForeground(
                        QtGui.QColor(COLOR_SUCCESS if valid else COLOR_WARNING)
                    )

        elif col == 3:  # 分类被编辑
            item = self._table.item(row, 3)
            if item and row < len(self._objects):
                self._objects[row]["category"] = item.text()

    def _set_all_checked(self, checked: bool):
        """全选/取消全选复选框"""
        for i in range(self._table.rowCount()):
            widget = self._table.cellWidget(i, 0)
            if widget:
                chk = widget.findChild(QtWidgets.QCheckBox)
                if chk:
                    chk.setChecked(checked)
                    if i < len(self._objects):
                        self._objects[i]["selected"] = checked

    # ── 自动命名 ──────────────────────────────────────────────

    def auto_generate_names(self):
        """根据当前命名模式重新生成所有导出名"""
        pattern = self._input_pattern.text().strip()
        preset = self._combo_naming_preset.currentText()
        self._naming_engine = NamingEngine(pattern=pattern, preset_name=preset)

        for i, obj in enumerate(self._objects):
            result = self._naming_engine.generate_name(
                obj["obj_name"],
                obj_info={
                    "type": obj["type"],
                    "index": i + 1,
                    "custom_attrs": {"category": obj.get("category", "")},
                }
            )
            obj["export_name"] = result.generated_name

        self._populate_table()
        self._append_log(f"已应用命名模式: {pattern} (预设: {preset})", "info")

    def _on_naming_preset_changed(self):
        """命名预设变更回调"""
        preset = self._combo_naming_preset.currentText()
        if preset in NAMING_PRESETS:
            pattern = NAMING_PRESETS[preset].get("pattern", self._input_pattern.text())
            self._input_pattern.blockSignals(True)
            self._input_pattern.setText(pattern)
            self._input_pattern.blockSignals(False)
            self.auto_generate_names()

    # ── 导出设置 ──────────────────────────────────────────────

    def _on_export_preset_changed(self):
        """导出预设变更回调 — 更新预处理选项"""
        idx = self._combo_export_preset.currentIndex()
        if idx < 0:
            return
        preset_name = self._combo_export_preset.itemData(idx)
        if not preset_name:
            return

        preset = self._preset_manager.get_preset(preset_name)
        if not preset:
            return

        # 更新预处理复选框
        preprocess = preset.get("preprocess", {})
        self._chk_freeze.setChecked(preprocess.get("freeze_transform", True))
        self._chk_delete_history.setChecked(preprocess.get("delete_history", True))
        self._chk_center_pivot.setChecked(preprocess.get("center_pivot", False))

        # 更新路径映射
        path_mapping = preset.get("path_mapping", {})
        self._chk_subfolder.setChecked(path_mapping.get("subfolder_by_category", True))

    def _browse_output_dir(self):
        """打开文件对话框选择输出目录"""
        start_dir = self._input_output_dir.text() or self._last_output_dir
        dir_path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择输出目录", start_dir
        )
        if dir_path:
            self._input_output_dir.setText(dir_path)
            self._last_output_dir = dir_path

    # ── 批量导出 ──────────────────────────────────────────────

    def _on_export_clicked(self):
        """批量导出按钮点击"""
        if not MAYA_AVAILABLE:
            QtWidgets.QMessageBox.critical(
                self, "错误", "Maya 环境不可用，无法执行导出。"
            )
            return

        # 验证输出目录
        output_dir = self._input_output_dir.text().strip()
        if not output_dir:
            QtWidgets.QMessageBox.warning(
                self, "警告", "请先选择输出目录。"
            )
            return

        # 收集选中导出的对象
        export_items = []
        for i, obj in enumerate(self._objects):
            widget = self._table.cellWidget(i, 0)
            if widget:
                chk = widget.findChild(QtWidgets.QCheckBox)
                if chk and chk.isChecked():
                    export_items.append((
                        obj["path"],
                        obj["export_name"],
                        obj["category"],
                    ))

        if not export_items:
            QtWidgets.QMessageBox.warning(
                self, "警告", "没有选中任何对象进行导出。"
            )
            return

        # 获取导出设置
        idx = self._combo_export_preset.currentIndex()
        preset_name = self._combo_export_preset.itemData(idx) or "UE5"
        preset = self._preset_manager.get_preset(preset_name)
        if not preset:
            QtWidgets.QMessageBox.critical(
                self, "错误", f"无法加载预设: {preset_name}"
            )
            return

        fbx_settings = preset.get("fbx_settings", {})
        preprocess = {
            "freeze_transform": self._chk_freeze.isChecked(),
            "delete_history": self._chk_delete_history.isChecked(),
            "center_pivot": self._chk_center_pivot.isChecked(),
        }
        subfolder = self._chk_subfolder.isChecked()

        # 确认对话框
        confirm = QtWidgets.QMessageBox.question(
            self,
            "确认导出",
            f"即将导出 {len(export_items)} 个对象到:\n{output_dir}\n"
            f"预设: {preset_name}\n"
            f"子目录: {'是' if subfolder else '否'}\n\n"
            f"预处理: 冻结变换={preprocess['freeze_transform']}, "
            f"删除历史={preprocess['delete_history']}\n\n"
            f"确认开始导出？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )

        if confirm != QtWidgets.QMessageBox.Yes:
            return

        # 执行导出
        self._btn_export.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._lbl_progress.setText("准备导出...")
        self._append_log(
            f"━━━ 开始批量导出: {len(export_items)} 个对象 ━━━", "info"
        )
        self._append_log(f"预设: {preset_name} | 输出: {output_dir}", "info")

        try:
            self._fbx_exporter = FBXExporter()

            report = self._fbx_exporter.batch_export(
                export_items=export_items,
                output_dir=output_dir,
                settings=fbx_settings,
                preprocess=preprocess,
                subfolder_by_category=subfolder,
                progress_callback=self._progress_callback,
            )

            # 输出结果
            self._progress_bar.setValue(100)
            self._lbl_progress.setText("导出完成")
            self._append_log(
                f"━━━ 导出完成: 成功 {report.succeeded}/{report.total} "
                f"({report.success_rate:.1f}%) | "
                f"耗时 {report.total_elapsed:.2f}s ━━━",
                "success" if report.failed == 0 else "warning"
            )

            for r in report.results:
                if r.success:
                    self._append_log(
                        f"  [OK]   {r.export_name} → {r.file_path} "
                        f"({r.elapsed:.2f}s)",
                        "success"
                    )
                else:
                    self._append_log(
                        f"  [FAIL] {r.export_name} → {r.error}",
                        "error"
                    )

            self.export_complete.emit(report)

        except Exception as e:
            self._append_log(f"导出错误: {e}", "error")
            QtWidgets.QMessageBox.critical(
                self, "导出错误", str(e)
            )

        finally:
            self._btn_export.setEnabled(True)

    def _progress_callback(self, current, total, name):
        """进度回调 — 更新进度条和标签"""
        if total > 0:
            percent = int(current / total * 100)
            self._progress_bar.setValue(percent)
        self._lbl_progress.setText(f"导出中 ({current + 1}/{total}): {name}")
        QtWidgets.QApplication.processEvents()

    # ── 日志 ──────────────────────────────────────────────────

    def _append_log(self, message: str, level: str = "info"):
        """追加日志到日志区"""
        colors = {
            "info": COLOR_TEXT,
            "success": COLOR_SUCCESS,
            "warning": COLOR_WARNING,
            "error": COLOR_ERROR,
        }
        color = colors.get(level, COLOR_TEXT)
        self._log_text.append(
            f'<span style="color:{color};">{message}</span>'
        )
        # 自动滚动到底部
        cursor = self._log_text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self._log_text.setTextCursor(cursor)


# ── 窗口显示函数 ────────────────────────────────────────────────

def _get_maya_window():
    """获取 Maya 主窗口的 QWidget"""
    if not MAYA_AVAILABLE or omUI is None or wrapInstance is None:
        return None

    try:
        maya_window_ptr = omUI.MQtUtil.mainWindow()
        maya_window = wrapInstance(int(maya_window_ptr), QtWidgets.QWidget)
        return maya_window
    except Exception:
        return None


def show():
    """
    显示 Batch Exporter 窗口

    在 Maya 中: 创建可停靠的 workspaceControl
    在独立环境中: 创建普通 QWidget 窗口

    用法 (Maya Script Editor):
        import maya_batch_exporter
        maya_batch_exporter.show()

    健壮性设计:
      - 顶层清空 _window_instance 引用，配合 try/except 抗 C++ 已死
      - 始终创建新 BatchExporterWindow，永不复用旧 wrapper
      - control_widget 强引用保存到模块全局，防止被 GC 连带销毁
      - 每个 UI 操作都 try/except 包裹，单点失败不影响整体
    """
    global _window_instance, _control_widget_ref

    # ── 第一阶段: 全局清理 ──────────────────────────────────────
    # 删除旧 workspaceControl（如果有）
    if MAYA_AVAILABLE and cmds is not None:
        try:
            if cmds.workspaceControl(WORKSPACE_CONTROL_NAME, exists=True):
                cmds.deleteUI(WORKSPACE_CONTROL_NAME, control=True)
        except Exception:
            pass

    # 安全释放旧 _window_instance
    #   - reload 后可能未定义, 用 globals() 守卫
    #   - C++ 对象可能已死, 用 try/except 忽略
    _win = globals().get('_window_instance')
    if _win is not None:
        try:
            _win.hide()
        except Exception:
            pass
        try:
            _win.setParent(None)
        except Exception:
            pass
        try:
            _win.deleteLater()
        except Exception:
            pass
    _window_instance = None
    _control_widget_ref = None

    # ── 第二阶段: Maya 内创建 workspaceControl ─────────────────
    if MAYA_AVAILABLE and cmds is not None:
        # 创建 workspaceControl
        try:
            cmds.workspaceControl(
                WORKSPACE_CONTROL_NAME,
                label=WINDOW_TITLE,
                retain=False,
                floating=True,
                resizeWidth=True,
                initialWidth=DEFAULT_WIDTH,
                initialHeight=DEFAULT_HEIGHT,
            )
        except Exception as e:
            print(f"[BatchExporter] workspaceControl 创建失败: {e}")
            return None

        # 拿到 control 内嵌的 Qt 容器 widget
        try:
            control_ptr = omUI.MQtUtil.findControl(WORKSPACE_CONTROL_NAME)
            if control_ptr is None:
                print("[BatchExporter] 找不到 control widget, abort")
                return None
            control_widget = wrapInstance(int(control_ptr), QtWidgets.QWidget)
            control_widget.setObjectName("batchExporterContainer")
        except Exception as e:
            print(f"[BatchExporter] 包装 control widget 失败: {e}")
            return None

        # 关键: 强引用保存, 防止 Python GC 间接销毁 C++ 端
        _control_widget_ref = control_widget

        # 始终创建全新窗口实例 (绝不复用旧 wrapper)
        try:
            _window_instance = BatchExporterWindow(parent=control_widget)
        except Exception as e:
            print(f"[BatchExporter] 创建窗口实例失败: {e}")
            return None

        # 绑定到 control_widget 的布局
        try:
            layout = control_widget.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(control_widget)
                layout.setContentsMargins(0, 0, 0, 0)
            else:
                # 清除残留旧 widget
                while layout.count():
                    item = layout.takeAt(0)
                    child_widget = item.widget()
                    if child_widget is not None:
                        try:
                            child_widget.setParent(None)
                        except Exception:
                            pass
            layout.addWidget(_window_instance)
        except Exception as e:
            print(f"[BatchExporter] 设置布局失败: {e}")

        return _window_instance

    # ── 第三阶段: 独立模式 (无 Maya) ──────────────────────────
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    _window_instance = BatchExporterWindow()
    _window_instance.show()
    return _window_instance


# ── 全局状态 ────────────────────────────────────────────────
# 窗口实例 (C++ BatchExporterWindow 的 Python wrapper)
_window_instance = None
# workspaceControl 内嵌 widget 强引用 (防止 Python GC 引发 C++ 链式析构)
_control_widget_ref = None
