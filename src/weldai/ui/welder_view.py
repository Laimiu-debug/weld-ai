"""焊工管理视图：焊工列表 + 档案详情 + 资格覆盖查询。

功能：
  - 焊工列表（钢印/姓名/状态/资格数/到期预警标记）
  - 新建/编辑/删除焊工
  - 选中焊工后显示其资格项目（项目代号 + 到期预警）
  - 资格覆盖查询：输入焊缝任务，查询哪些焊工可施焊
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.enums import Position, WeldingProcess
from ..domain.welder import Welder
from ..engine.welder_engine import WeldTask, WelderEngine
from ..persistence import WelderRepository, get_session
from .welder_dialog import WelderDialog

_PROCESS_ITEMS = [
    (WeldingProcess.SMAW, "SMAW"), (WeldingProcess.GTAW, "GTAW"),
    (WeldingProcess.SAW, "SAW"), (WeldingProcess.GMAW, "GMAW"),
]
_MATERIAL_CATEGORIES = [
    "FeⅠ", "FeⅡ", "FeⅢ", "FeⅣ", "FeⅤ", "FeⅥ", "FeⅦ", "FeⅧ", "FeⅨ", "FeⅩ",
]


def _positions_for_form(form: str) -> list[Position]:
    """按试件形式筛选适用的焊接位置（同焊工对话框）。"""
    mapping = {
        "板对接": [Position.PLATE_1G, Position.PLATE_2G,
                  Position.PLATE_3G, Position.PLATE_4G],
        "管对接": [Position.PIPE_1G, Position.PIPE_2G, Position.PIPE_5G,
                  Position.PIPE_6G, Position.PIPE_6GR],
        "管板角接": [Position.TUBE_2FRG, Position.TUBE_2FG, Position.TUBE_4FG,
                    Position.TUBE_5FG, Position.TUBE_6FG],
        "管材角焊缝": [Position.PIPE_F_1F, Position.PIPE_F_2F,
                      Position.PIPE_F_4F, Position.PIPE_F_5F],
        "板材角焊缝": [Position.PLATE_1F, Position.PLATE_2F,
                      Position.PLATE_3F, Position.PLATE_4F],
    }
    return mapping.get(form, list(Position))


class WelderView(QWidget):
    """焊工管理主视图（嵌入主窗口的标签页）。"""

    def __init__(self) -> None:
        super().__init__()
        self._repo = WelderRepository(get_session())
        self._engine = WelderEngine()
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 工具栏
        toolbar = QHBoxLayout()
        self.btn_new = QPushButton("✚ 新建焊工")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_edit = QPushButton("✎ 编辑")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_del = QPushButton("✖ 删除")
        self.btn_del.clicked.connect(self._on_delete)
        for b in (self.btn_new, self.btn_edit, self.btn_del):
            toolbar.addWidget(b)
        toolbar.addStretch()
        root.addLayout(toolbar)

        # 列表 + 详情
        sp = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("焊工列表"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["钢印号", "姓名", "状态", "资格数", "预警"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._on_select)
        ll.addWidget(self.table)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("资格项目 / 预警"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(280)
        rl.addWidget(self.detail)
        rl.addWidget(self._build_coverage_group())

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setSizes([480, 720])
        root.addWidget(sp, stretch=1)

    def _build_coverage_group(self) -> QGroupBox:
        gb = QGroupBox("资格覆盖查询（哪些焊工可施焊此任务）")
        lay = QVBoxLayout(gb)
        row1 = QHBoxLayout()
        self.cov_process = QComboBox()
        for p, lab in _PROCESS_ITEMS:
            self.cov_process.addItem(lab, p)
        self.cov_material = QComboBox()
        self.cov_material.setEditable(True)
        self.cov_material.addItems(_MATERIAL_CATEGORIES)
        self.cov_form = QComboBox()
        self.cov_form.setEditable(True)
        self.cov_form.addItems(["板对接", "管对接", "管板角接", "管材角焊缝", "板材角焊缝"])
        self.cov_form.currentTextChanged.connect(self._on_cov_form_change)
        self.cov_position = QComboBox()
        row1.addWidget(QLabel("方法")); row1.addWidget(self.cov_process)
        row1.addWidget(QLabel("母材类")); row1.addWidget(self.cov_material)
        row1.addWidget(QLabel("试件")); row1.addWidget(self.cov_form)
        row1.addWidget(QLabel("位置")); row1.addWidget(self.cov_position)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.cov_thickness = QDoubleSpinBox()
        self.cov_thickness.setRange(0, 200); self.cov_thickness.setDecimals(1)
        self.cov_thickness.setValue(12.0)
        self.cov_diameter = QDoubleSpinBox()
        self.cov_diameter.setRange(0, 5000); self.cov_diameter.setDecimals(1)
        self.cov_diameter.setSpecialValueText("（板材）")
        self.cov_backing = QCheckBox("带衬垫")
        row2.addWidget(QLabel("焊缝厚度(mm)")); row2.addWidget(self.cov_thickness)
        row2.addWidget(QLabel("管径(mm)")); row2.addWidget(self.cov_diameter)
        row2.addWidget(self.cov_backing)
        row2.addStretch()
        self.btn_cov = QPushButton("🔍 查询可施焊焊工")
        self.btn_cov.clicked.connect(self._on_coverage_query)
        row2.addWidget(self.btn_cov)
        lay.addLayout(row2)

        self.cov_result = QTextEdit()
        self.cov_result.setReadOnly(True)
        self.cov_result.setMaximumHeight(150)
        lay.addWidget(self.cov_result)
        # 初始填充位置（板对接）
        self._on_cov_form_change(self.cov_form.currentText())
        return gb

    def _on_cov_form_change(self, form_text: str) -> None:
        """查询页：试件形式联动位置列表 + 管径启用。"""
        positions = _positions_for_form(form_text)
        cur = self.cov_position.currentData()
        self.cov_position.blockSignals(True)
        self.cov_position.clear()
        for p in positions:
            self.cov_position.addItem(p.value, p)
        if cur is not None:
            idx = self.cov_position.findData(cur)
            if idx >= 0:
                self.cov_position.setCurrentIndex(idx)
        self.cov_position.blockSignals(False)
        is_tube = "管" in form_text
        self.cov_diameter.setEnabled(is_tube)
        if not is_tube:
            self.cov_diameter.setValue(0)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def _selected_stamp(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).text()

    def _refresh(self) -> None:
        welders = self._repo.list_all()
        self.table.setRowCount(len(welders))
        for i, w in enumerate(welders):
            alerts = w.alerts()
            alert_mark = "⚠" + str(len(alerts)) if alerts else "—"
            self.table.setItem(i, 0, QTableWidgetItem(w.stamp_no))
            self.table.setItem(i, 1, QTableWidgetItem(w.name))
            self.table.setItem(i, 2, QTableWidgetItem(w.status))
            self.table.setItem(i, 3, QTableWidgetItem(str(len(w.qualifications))))
            warn_item = QTableWidgetItem(alert_mark)
            if alerts:
                warn_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(i, 4, warn_item)

    def _on_new(self) -> None:
        dlg = WelderDialog(parent=self)
        if dlg.exec() == WelderDialog.DialogCode.Accepted:
            try:
                self._repo.save(dlg.get_welder())
            except Exception as e:
                QMessageBox.warning(self, "保存失败", str(e))
                return
            self._refresh()

    def _on_edit(self) -> None:
        stamp = self._selected_stamp()
        if not stamp:
            QMessageBox.information(self, "提示", "请先选中一个焊工")
            return
        welder = self._repo.get(stamp)
        if not welder:
            return
        dlg = WelderDialog(welder=welder, parent=self)
        if dlg.exec() == WelderDialog.DialogCode.Accepted:
            self._repo.save(dlg.get_welder())
            self._refresh()
            self._on_select()

    def _on_delete(self) -> None:
        stamp = self._selected_stamp()
        if not stamp:
            return
        if QMessageBox.question(
            self, "确认删除", f"确定删除焊工 {stamp} 吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._repo.delete(stamp)
        self._refresh()

    def _on_select(self) -> None:
        stamp = self._selected_stamp()
        if not stamp:
            self.detail.clear()
            return
        welder = self._repo.get(stamp)
        if not welder:
            return
        self._render_detail(welder)

    def _render_detail(self, w: Welder) -> None:
        lines = [f"<h3>{w.name}（钢印 {w.stamp_no}）</h3>"]
        lines.append(f"<p>证书号：{w.cert_no or '—'} | "
                     f"出生：{w.birth_date or '—'}（{w.age or '?'}岁）| "
                     f"状态：{w.status}</p>")
        if w.qualifications:
            lines.append("<p><b>资格项目：</b></p>")
            lines.append("<table border='1' cellspacing='0' cellpadding='3'"
                         " style='border-collapse:collapse;font-size:12px;width:100%'>")
            lines.append("<tr style='background:#f0f0f0'><th>项目代号</th>"
                         "<th>到期日</th><th>状态</th></tr>")
            for q in w.qualifications:
                status = "已过期" if q.is_expired else (
                    f"{q.days_to_expire}天后到期" if q.days_to_expire is not None else "—"
                )
                color = "#c62828" if q.is_expired else "#333"
                lines.append(
                    f"<tr><td>{q.project_code}</td>"
                    f"<td>{q.expire_date or '—'}</td>"
                    f"<td style='color:{color}'>{status}</td></tr>"
                )
            lines.append("</table>")
        alerts = w.alerts()
        if alerts:
            lines.append("<p style='color:#c62828;margin-top:8px'><b>⚠ 预警：</b></p>")
            for a in alerts:
                lines.append(f"<div style='color:#c62828;margin-left:12px'>• {a}</div>")
        elif w.is_interrupted:
            lines.append("<p style='color:#ef6c00'>中断超6个月，需重新考核</p>")
        self.detail.setHtml("\n".join(lines))

    def _on_coverage_query(self) -> None:
        # Qt 对 (str,Enum) 会把 currentData 退化为纯 str，这里强制转回枚举，
        # 避免下游 .value 访问报错（详见 welder_engine._ev）。
        proc_raw = self.cov_process.currentData()
        pos_raw = self.cov_position.currentData()
        process = proc_raw if isinstance(proc_raw, WeldingProcess) else WeldingProcess(proc_raw)
        position = pos_raw if isinstance(pos_raw, Position) else Position(pos_raw)
        task = WeldTask(
            process=process,
            material_category=self.cov_material.currentText(),
            joint_form=self.cov_form.currentText(),
            thickness=self.cov_thickness.value(),
            outer_diameter=(self.cov_diameter.value() or None),
            position=position,
            has_backing=self.cov_backing.isChecked(),
        )
        welders = self._repo.list_all()
        if not welders:
            self.cov_result.setHtml("<p style='color:#999'>（焊工库为空）</p>")
            return
        qualified: list[Welder] = []
        for w in welders:
            if self._engine.can_weld(w, task):
                qualified.append(w)
        if not qualified:
            self.cov_result.setHtml(
                "<p style='color:#c62828'>✗ 没有焊工具备该任务的施焊资格</p>"
                "<p style='font-size:11px;color:#666'>任务："
                f"{process.value}/{task.material_category}/"
                f"{task.thickness}mm/{position.value}</p>"
            )
            return
        lines = [
            f"<p style='color:#2e7d32'>✓ {len(qualified)} 名焊工可施焊：</p>",
            "<table border='1' cellspacing='0' cellpadding='3'"
            " style='border-collapse:collapse;font-size:12px;width:100%'>",
            "<tr style='background:#f0f0f0'><th>钢印</th><th>姓名</th>"
            "<th>匹配资格</th></tr>",
        ]
        for w in qualified:
            checks = self._engine.check(w, task)
            matched = next((c for c in checks if c.covered), None)
            lines.append(
                f"<tr><td>{w.stamp_no}</td><td>{w.name}</td>"
                f"<td>{matched.qualification.project_code if matched else '—'}</td></tr>"
            )
        lines.append("</table>")
        self.cov_result.setHtml("\n".join(lines))
