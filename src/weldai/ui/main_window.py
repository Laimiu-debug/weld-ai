"""主窗口：标准切换 + 标签页（工艺评定工作台 / 焊工管理）。

功能：
  - 顶部标准切换器（NB/T 47014-2023 / 预留）
  - 标签页1「工艺评定」：pWPS/WPS/PQR 列表 + 新建/编辑/删除/校验/导出
  - 标签页2「焊工管理」：焊工档案 + 资格项目 + 预警 + 资格覆盖查询
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.enums import ProcedureType
from ..engine import FactorEngine
from ..persistence import ProcedureRepository, get_session, init_db
from ..services import export_procedure
from ..standards import (
    default_standard_key,
    get_default_standard,
    get_standard,
    list_standards,
)
from .procedure_dialog import ProcedureDialog
from .welder_view import WelderView
from .cost_view import CostView
from .ai_view import AIView
from .trace_view import TraceView


class ProcedureView(QWidget):
    """工艺评定工作台视图（嵌入主窗口标签页）。"""

    def __init__(self, standard, repo, engine):
        super().__init__()
        self._standard = standard
        self._repo = repo
        self._engine = engine
        self._build_ui()
        self._refresh_list()

    def update_standard(self, standard, repo, engine):
        self._standard = standard
        self._repo = repo
        self._engine = engine
        self._refresh_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(QLabel("类型筛选："))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部", None)
        for t in ProcedureType:
            self.filter_combo.addItem(t.value, t)
        self.filter_combo.currentIndexChanged.connect(lambda _: self._refresh_list())
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch()

        self.btn_new = QPushButton("✚ 新建")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_edit = QPushButton("✎ 编辑")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_del = QPushButton("✖ 删除")
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_verify = QPushButton("🔍 校验 WPS")
        self.btn_verify.clicked.connect(self._on_verify)
        self.btn_export = QPushButton("📄 导出")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_clone = QPushButton("⎘ 克隆")
        self.btn_clone.clicked.connect(self._on_clone)
        self.btn_batch = QPushButton("📋 批量校验")
        self.btn_batch.clicked.connect(self._on_batch_verify)
        self.btn_match = QPushButton("🎯 匹配PQR")
        self.btn_match.clicked.connect(self._on_match_pqr)
        self.btn_excel = QPushButton("📤 Excel")
        self.btn_excel.clicked.connect(self._on_export_excel)
        for b in (self.btn_new, self.btn_edit, self.btn_del,
                  self.btn_verify, self.btn_export,
                  self.btn_clone, self.btn_batch, self.btn_match, self.btn_excel):
            toolbar.addWidget(b)
        root.addLayout(toolbar)
        root.addWidget(self._build_splitter(), stretch=1)

    def _build_splitter(self) -> QSplitter:
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("工艺文件列表"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["编号", "类型", "焊接方法", "母材", "依据PQR"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.doubleClicked.connect(lambda *_: self._on_edit())
        ll.addWidget(self.table)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("校验 / 详情"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(
            "选中一个 WPS 后点击「校验 WPS」，将对比其依据的 PQR "
            "并输出因素变更与覆盖范围校验结果。"
        )
        rl.addWidget(self.detail)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setSizes([620, 620])
        return sp

    def _selected_doc_no(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).text()

    def _refresh_list(self) -> None:
        doc_type = self.filter_combo.currentData()
        docs = self._repo.list_all(doc_type)
        self.table.setRowCount(len(docs))
        for i, p in enumerate(docs):
            grades = ", ".join(bm.metal.grade for bm in p.base_metals)
            self.table.setItem(i, 0, QTableWidgetItem(p.doc_no))
            self.table.setItem(i, 1, QTableWidgetItem(p.type.value))
            self.table.setItem(i, 2, QTableWidgetItem(p.process.cn))
            self.table.setItem(i, 3, QTableWidgetItem(grades))
            self.table.setItem(i, 4, QTableWidgetItem(p.supporting_pqr_no or "—"))

    def _on_new(self) -> None:
        dlg = ProcedureDialog(self._standard, parent=self)
        if dlg.exec() == ProcedureDialog.DialogCode.Accepted:
            try:
                self._repo.save(dlg.get_procedure())
            except Exception as e:
                QMessageBox.warning(self, "保存失败", str(e))
                return
            self._refresh_list()

    def _on_edit(self) -> None:
        doc_no = self._selected_doc_no()
        if not doc_no:
            QMessageBox.information(self, "提示", "请先选中一个工艺文件")
            return
        proc = self._repo.get(doc_no)
        if proc is None:
            return
        dlg = ProcedureDialog(self._standard, procedure=proc, parent=self)
        if dlg.exec() == ProcedureDialog.DialogCode.Accepted:
            self._repo.save(dlg.get_procedure())
            self._refresh_list()

    def _on_delete(self) -> None:
        doc_no = self._selected_doc_no()
        if not doc_no:
            return
        if QMessageBox.question(
            self, "确认删除", f"确定删除 {doc_no} 吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._repo.delete(doc_no)
        self._refresh_list()

    def _on_verify(self) -> None:
        doc_no = self._selected_doc_no()
        if not doc_no:
            QMessageBox.information(self, "提示", "请先选中一个 WPS")
            return
        wps = self._repo.get(doc_no)
        if wps is None:
            return
        if wps.type != ProcedureType.WPS:
            QMessageBox.information(self, "提示", "校验仅适用于 WPS。请选中一个 WPS。")
            return
        if not wps.supporting_pqr_no:
            QMessageBox.warning(self, "无法校验", f"{wps.doc_no} 未关联依据 PQR 编号。")
            return
        pqr = self._repo.get(wps.supporting_pqr_no)
        if pqr is None:
            QMessageBox.warning(
                self, "无法校验",
                f"找不到依据 PQR：{wps.supporting_pqr_no}。请先新建该 PQR。",
            )
            return
        result = self._engine.compare(pqr, wps)
        self.detail.setHtml(self._render_result(result))

    def _on_export(self) -> None:
        doc_no = self._selected_doc_no()
        if not doc_no:
            QMessageBox.information(self, "提示", "请先选中一个工艺文件")
            return
        proc = self._repo.get(doc_no)
        if proc is None:
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "导出工艺文件", f"{proc.doc_no}.docx",
            "Word 文档 (*.docx);;PDF 文件 (*.pdf)",
        )
        if not path:
            return
        # 根据选择的过滤器或文件后缀决定格式
        fmt = "pdf" if (".pdf" in sel or path.lower().endswith(".pdf")) else "docx"
        try:
            export_procedure(proc, path, fmt=fmt)
            QMessageBox.information(
                self, "导出成功",
                f"已保存到：{path}\n格式：{'Word(可编辑)' if fmt == 'docx' else 'PDF'}"
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_clone(self):
        """克隆当前选中的工艺文件。"""
        from PySide6.QtWidgets import QInputDialog
        doc_no = self._selected_doc_no()
        if not doc_no:
            QMessageBox.information(self, "提示", "请先选中一个工艺文件")
            return
        new_no, ok = QInputDialog.getText(
            self, "克隆工艺文件", f"新编号（源: {doc_no}）：",
            text=f"{doc_no}-副本",
        )
        if not ok or not new_no.strip():
            return
        from ..services import BatchService
        batch = BatchService(self._repo, self._standard)
        new = batch.clone(doc_no, new_no.strip())
        if new is None:
            QMessageBox.warning(self, "克隆失败", f"找不到源文件 {doc_no}")
            return
        self._refresh_list()
        QMessageBox.information(self, "克隆成功", f"已创建 {new.doc_no}")

    def _on_batch_verify(self):
        """批量校验所有 WPS，结果展示在详情区。"""
        from ..services import BatchService
        batch = BatchService(self._repo, self._standard)
        results = batch.verify_all_wps()
        if not results:
            QMessageBox.information(self, "提示", "当前没有 WPS 可校验")
            return
        # 统计
        ok_count = sum(1 for r in results if r.success)
        requalify_count = sum(1 for r in results if r.needs_requalify)
        # 渲染表格
        lines = [
            f"<h3>批量校验结果（{len(results)} 个 WPS）</h3>",
            f"<p>✓ 合格 {ok_count} 个 | ✗ 需重新评定 {requalify_count} 个 | "
            f"△ 其他问题 {len(results) - ok_count - requalify_count} 个</p>",
            "<table border='1' cellspacing='0' cellpadding='3'"
            " style='border-collapse:collapse;font-size:12px;width:100%'>",
            "<tr style='background:#f0f0f0'><th>WPS编号</th><th>依据PQR</th>"
            "<th>结论</th><th>变更数</th><th>状态</th></tr>",
        ]
        for r in results:
            color = "#2e7d32" if r.success else ("#c62828" if r.needs_requalify else "#ef6c00")
            status = "✓合格" if r.success else ("✗重新评定" if r.needs_requalify else "△注意")
            lines.append(
                f"<tr><td>{r.wps_no}</td><td>{r.pqr_no}</td>"
                f"<td>{r.verdict}</td><td>{r.changes_count}</td>"
                f"<td style='color:{color}'>{status}</td></tr>"
            )
        lines.append("</table>")
        self.detail.setHtml("\n".join(lines))

    def _on_match_pqr(self):
        """打开焊缝匹配 PQR 查询对话框。"""
        from .pqr_match_dialog import PQRMatchDialog
        dlg = PQRMatchDialog(self)
        dlg.exec()

    def _on_export_excel(self):
        """导出工艺文件清单到 Excel/CSV。"""
        from ..services import BatchService
        path, _ = QFileDialog.getSaveFileName(
            self, "导出工艺文件清单", "工艺文件清单.xlsx",
            "Excel 文件 (*.xlsx);;CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            batch = BatchService(self._repo, self._standard)
            saved = batch.export_to_excel(path)
            QMessageBox.information(self, "导出成功", f"已保存到：{saved}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _render_result(self, result) -> str:
        color = {
            "✓": "#2e7d32", "○": "#1565c0", "△": "#ef6c00", "✗": "#c62828",
        }.get(result.verdict_cn[0], "#333")
        lines = [
            f"<h3 style='color:{color}'>{result.verdict_cn}</h3>",
            f"<p>WPS: <b>{result.wps_no}</b> &nbsp; 依据 PQR: <b>{result.pqr_no}</b>"
            f" &nbsp; 标准: {result.standard}</p>",
            f"<p>最严重处置：<b>{result.worst_action.cn}</b>"
            f" &nbsp;| 变更项数：{len(result.changes)}</p>",
        ]
        if result.changes:
            lines.append("<table border='1' cellspacing='0' cellpadding='3'"
                         " style='border-collapse:collapse;font-size:12px;width:100%'>")
            lines.append("<tr style='background:#f0f0f0'><th>因素</th><th>等级</th>"
                         "<th>变更内容</th><th>处置</th></tr>")
            for c in result.changes:
                lines.append(
                    f"<tr><td>{c.factor_name}</td><td>{c.level_cn}</td>"
                    f"<td>{c.change_description}</td><td>{c.action_cn}</td></tr>"
                )
            lines.append("</table>")
        else:
            lines.append("<p>（无因素变更）</p>")
        lines.append("<p style='margin-top:8px'><b>覆盖范围校验：</b></p>")
        lines.append("<div style='font-size:12px'>")
        for n in result.coverage_notes:
            lines.append(f"{n}<br>")
        lines.append("</div>")
        return "\n".join(lines)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("weldAI · 焊接工艺管理平台")
        self.resize(1320, 860)

        init_db()
        self._standard_key = default_standard_key()
        self._standard = get_default_standard()
        self._repo = ProcedureRepository(get_session(), self._standard)
        self._engine = FactorEngine(self._standard)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        root.addWidget(self._build_toolbar())

        self.tabs = QTabWidget()
        self.proc_view = ProcedureView(
            self._standard, self._repo, self._engine
        )
        self.tabs.addTab(self.proc_view, "📐 工艺评定")
        self.welder_view = WelderView()
        self.tabs.addTab(self.welder_view, "👷 焊工管理")
        self.cost_view = CostView()
        self.tabs.addTab(self.cost_view, "💰 成本计算")
        self.ai_view = AIView()
        self.tabs.addTab(self.ai_view, "🤖 AI 辅助")
        self.trace_view = TraceView()
        self.tabs.addTab(self.trace_view, "🔩 焊缝追溯")
        # 切换到 AI 标签页时刷新 PQR 下拉
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)

        self._build_menu()
        # 小屏幕适配：把窗口限制在可用屏幕区内（860 高在 768 笔记本会溢出）
        from ._screen import fit_to_screen
        fit_to_screen(self)

    def _build_menu(self) -> None:
        """菜单栏：设置入口。"""
        from .settings_dialog import SettingsDialog

        menubar = self.menuBar()
        set_menu = menubar.addMenu("设置(S)")
        set_menu.setTitle("设置(&S)")

        act_llm = set_menu.addAction("LLM 焊接专家配置...")
        act_llm.setShortcut("Ctrl+,")
        act_llm.triggered.connect(self._on_settings)

    def _on_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        dlg = SettingsDialog(self)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            # 配置已保存，刷新 AI 视图的 LLM 实例
            self.ai_view.refresh_llm_config()
            QMessageBox.information(self, "设置已保存", "LLM 配置已更新。")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("评定标准："))
        self.std_combo = QComboBox()
        for key in list_standards():
            std = get_standard(key)
            self.std_combo.addItem(f"{std.standard_code}", key)
        self.std_combo.setCurrentText(self._standard_key)
        self.std_combo.currentTextChanged.connect(self._on_standard_changed)
        lay.addWidget(self.std_combo)
        lay.addStretch()
        lay.addWidget(QLabel(
            "<span style='color:#888;font-size:11px'>weldAI · "
            "国内压力容器焊接管理平台</span>"
        ))
        return bar

    def _on_standard_changed(self, key: str) -> None:
        self._standard_key = key
        self._standard = get_standard(key)
        self._repo = ProcedureRepository(get_session(), self._standard)
        self._engine = FactorEngine(self._standard)
        self.proc_view.update_standard(self._standard, self._repo, self._engine)
        self.ai_view.update_standard(self._standard)
        self.ai_view.refresh()

    def _on_tab_changed(self, index: int) -> None:
        """切到 AI 辅助标签页时刷新 PQR 下拉。"""
        if self.tabs.tabText(index).startswith("🤖"):
            self.ai_view.refresh()
