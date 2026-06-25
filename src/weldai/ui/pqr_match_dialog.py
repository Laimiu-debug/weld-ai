"""PQR 匹配查询对话框。

输入焊缝需求（母材+厚度+位置+方法），筛选出能覆盖它的 PQR。
解决生产高频问题："这条焊缝，现有哪些 PQR 能用，不用重新评定？"
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.enums import Position, WeldingProcess
from ..engine import PQRMatcher, WeldRequirement
from ..persistence import ProcedureRepository, get_session
from ..standards import get_default_standard

_PROCESS_ITEMS = [
    (WeldingProcess.SMAW, "SMAW 焊条电弧焊"),
    (WeldingProcess.GTAW, "GTAW 钨极氩弧焊"),
    (WeldingProcess.SAW, "SAW 埋弧焊"),
    (WeldingProcess.GMAW, "GMAW 熔化极气保焊"),
]
_POSITION_ITEMS = [
    Position.PLATE_1G, Position.PLATE_2G, Position.PLATE_3G, Position.PLATE_4G,
    Position.PIPE_1G, Position.PIPE_2G, Position.PIPE_5G, Position.PIPE_6G,
]


class PQRMatchDialog(QDialog):
    """焊缝需求 → 匹配 PQR 查询对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 焊缝匹配 PQR（筛选可覆盖的工艺评定）")
        self.resize(960, 720)
        self._standard = get_default_standard()
        self._build_ui()
        from ._screen import fit_to_screen
        fit_to_screen(self)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        # 内容区包进滚动区（小屏幕适配）
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.addWidget(self._build_input_group())
        content_layout.addWidget(self._build_result_group(), stretch=1)
        from ._screen import make_scroll_content
        root.addWidget(make_scroll_content(content), stretch=1)

    def _build_input_group(self) -> QGroupBox:
        gb = QGroupBox("焊缝需求（待匹配参数）")
        form = QFormLayout(gb)

        self.material = QComboBox()
        self.material.setEditable(True)
        for m in sorted(self._standard.all_base_metals(), key=lambda x: str(x.grade)):
            self.material.addItem(str(m.grade))
        form.addRow("母材牌号：", self.material)

        self.process = QComboBox()
        for p, lab in _PROCESS_ITEMS:
            self.process.addItem(lab, p)
        form.addRow("焊接方法：", self.process)

        row = QHBoxLayout()
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.5, 300); self.thickness.setValue(16.0)
        self.thickness.setDecimals(1)
        self.position = QComboBox()
        for p in _POSITION_ITEMS:
            self.position.addItem(p.value, p)
        self.outer_diameter = QDoubleSpinBox()
        self.outer_diameter.setRange(0, 5000); self.outer_diameter.setValue(0)
        self.outer_diameter.setSpecialValueText("（板材/无）")
        self.impact = QCheckBox("有冲击要求")
        row.addWidget(QLabel("厚度(mm):")); row.addWidget(self.thickness)
        row.addWidget(QLabel("位置:")); row.addWidget(self.position)
        row.addWidget(QLabel("管径(mm):")); row.addWidget(self.outer_diameter)
        row.addWidget(self.impact)
        row_w = QWidget(); row_w.setLayout(row)
        form.addRow("参数：", row_w)

        self.btn_match = QPushButton("🔍 开始匹配")
        self.btn_match.clicked.connect(self._on_match)
        form.addRow(self.btn_match)
        return gb

    def _build_result_group(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("匹配结果（按覆盖度排序，✓为完全覆盖）"))
        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(
            ["PQR编号", "匹配状态", "不满足项数", "维度详情"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.result_table)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(180)
        self.detail.setPlaceholderText("选中上方某行 PQR，查看各维度匹配详情。")
        lay.addWidget(self.detail)
        self.result_table.itemSelectionChanged.connect(self._on_select)
        return w

    def _on_match(self):
        req = WeldRequirement(
            process=self.process.currentData(),
            material_grade=self.material.currentText(),
            thickness=self.thickness.value(),
            outer_diameter=(self.outer_diameter.value() or None),
            position=self.position.currentData(),
            impact_required=self.impact.isChecked(),
        )
        repo = ProcedureRepository(get_session(), self._standard)
        matcher = PQRMatcher(repo, self._standard)
        self._results = matcher.match(req)

        if not self._results:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "数据库中没有 PQR。请先在工艺评定页新建 PQR。")
            return

        # 填充结果表
        self.result_table.setRowCount(len(self._results))
        matched_count = sum(1 for r in self._results if r.fully_matched)
        for i, r in enumerate(self._results):
            color = "#2e7d32" if r.fully_matched else ("#ef6c00" if r.miss_count == 1 else "#c62828")
            no_item = QTableWidgetItem(r.pqr_no)
            status_item = QTableWidgetItem(r.verdict_cn)
            status_item.setForeground(Qt.GlobalColor.darkGreen if r.fully_matched else Qt.GlobalColor.red)
            miss_item = QTableWidgetItem(str(r.miss_count))
            miss_item.setForeground(Qt.GlobalColor.red if r.miss_count else Qt.GlobalColor.darkGreen)
            # 维度简表（✓/✗ 标记）
            dim_summary = "  ".join(
                f"{'✓' if d.passed else '✗'}{d.name}" for d in r.dimensions
            )
            dim_item = QTableWidgetItem(dim_summary)
            self.result_table.setItem(i, 0, no_item)
            self.result_table.setItem(i, 1, status_item)
            self.result_table.setItem(i, 2, miss_item)
            self.result_table.setItem(i, 3, dim_item)

        # 顶部汇总
        self.detail.setHtml(
            f"<h3>匹配汇总</h3>"
            f"<p>共评估 {len(self._results)} 个 PQR | "
            f"<span style='color:#2e7d32'><b>完全覆盖 {matched_count} 个</b></span> | "
            f"部分满足 {sum(1 for r in self._results if r.miss_count==1)} 个 | "
            f"不满足 {sum(1 for r in self._results if r.miss_count>1)} 个</p>"
            f"<p style='font-size:11px;color:#666'>"
            f"完全覆盖 = 该 PQR 可直接用于此焊缝（无需重新评定）。"
            f"部分满足 = 仅1项不满足，可能通过补做冲击或改WPS解决。</p>"
        )

    def _on_select(self):
        rows = self.result_table.selectionModel().selectedRows()
        if not rows or not hasattr(self, "_results"):
            return
        r = self._results[rows[0].row()]
        lines = [
            f"<h4>{r.pqr_no} 的维度匹配详情</h4>",
            "<table border='1' cellspacing='0' cellpadding='4'"
            " style='border-collapse:collapse;font-size:12px;width:100%'>",
            "<tr style='background:#f0f0f0'><th>维度</th><th>结果</th><th>说明</th></tr>",
        ]
        for d in r.dimensions:
            color = "#2e7d32" if d.passed else "#c62828"
            mark = "✓ 满足" if d.passed else "✗ 不满足"
            lines.append(
                f"<tr><td>{d.name}</td>"
                f"<td style='color:{color}'>{mark}</td>"
                f"<td>{d.detail}</td></tr>"
            )
        lines.append("</table>")
        self.detail.setHtml("\n".join(lines))
