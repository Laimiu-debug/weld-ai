"""焊工编辑对话框。

编辑焊工档案（钢印号/证书号/姓名/出生日期）+ 资格项目表（TSG Z6002 七要素）。
资格项目按行录入，实时显示生成的项目代号。
"""
from __future__ import annotations

import copy
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain.enums import Position, WeldingProcess
from ..domain.welder import Welder, WelderQualification

_PROCESS_ITEMS = [
    (WeldingProcess.SMAW, "SMAW 焊条电弧焊"),
    (WeldingProcess.GTAW, "GTAW 钨极氩弧焊"),
    (WeldingProcess.SAW, "SAW 埋弧焊"),
    (WeldingProcess.GMAW, "GMAW 熔化极气保焊"),
    (WeldingProcess.FCAW, "FCAW 药芯焊丝"),
]

# 填充金属类别代号（TSG Z6002 表A-3，⑥要素）
_FILL_METAL_CLASSES = [
    "Fef1", "Fef2", "Fef3", "Fef3J", "Fef4", "Fef4J", "FefS",
    "FefA", "FefB", "FefC", "FefD", "FefM",
]

# 焊接工艺因素代号（TSG Z6002 表A-5，⑦要素，按焊接方法预设）
_PROCESS_FACTORS: dict[WeldingProcess, list[str]] = {
    WeldingProcess.SMAW: ["01", "02", "03s", "03c", "04", "06", "08"],
    WeldingProcess.GTAW: ["01", "02", "03s", "06", "08", "09c", "10"],
    WeldingProcess.GMAW: ["01", "02", "06", "07", "08", "10"],
    WeldingProcess.FCAW: ["01", "02", "06", "07", "08", "10"],
    WeldingProcess.SAW: ["01", "02", "08"],
}

# 试件形式（用于位置联动）
_SPECIMEN_FORMS = ["板对接", "管对接", "管板角接", "管材角焊缝", "板材角焊缝"]

# 母材类别（TSG Z6002 用 FeⅠ~FeⅩ 罗马数字，兼容 Fe-1 写法）
_MATERIAL_CATEGORIES = [
    "FeⅠ", "FeⅡ", "FeⅢ", "FeⅣ", "FeⅤ", "FeⅥ", "FeⅦ", "FeⅧ", "FeⅨ", "FeⅩ",
]


def _positions_for_form(form: str) -> list[Position]:
    """按试件形式筛选适用的焊接位置（TSG Z6002 表A-4）。"""
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


class MultiFactorButton(QPushButton):
    """⑦焊接工艺因素多选按钮：点击弹出复选菜单，支持多选。

    用法：构造时传入可选项；selected_factors() 返回选中项列表。
    """

    def __init__(self, items: list[str], parent=None):
        super().__init__("（点击选择）", parent)
        self._items = list(items)
        self._checks: dict[str, QCheckBox] = {}
        self.setMenu(QMenu(self))
        self._build_menu()
        self.clicked.connect(self.showMenu)

    def _build_menu(self) -> None:
        menu = self.menu()
        menu.clear()
        self._checks.clear()
        for it in self._items:
            act = menu.addAction(it)
            act.setCheckable(True)
            act.toggled.connect(lambda checked, code=it: self._on_toggle(code, checked))

    def _on_toggle(self, code: str, checked: bool) -> None:
        if checked:
            self._checks[code] = True
        else:
            self._checks.pop(code, None)
        self._refresh_label()

    def _refresh_label(self) -> None:
        sel = sorted(self._checks.keys())
        self.setText("+".join(sel) if sel else "（点击选择）")

    def set_items(self, items: list[str]) -> None:
        """切换可选项时，保留仍有效的选中。"""
        old_sel = set(self._checks.keys())
        self._items = list(items)
        self._build_menu()
        # 恢复仍有效的选中
        for it in items:
            if it in old_sel:
                self._checks[it] = True
        self._refresh_label()

    def selected_factors(self) -> list[str]:
        return sorted(self._checks.keys())

    def set_selected(self, factors: list[str]) -> None:
        self._checks = {f: True for f in factors if f in self._items}
        # 同步菜单勾选状态
        for action in self.menu().actions():
            action.setChecked(action.text() in self._checks)
        self._refresh_label()


class WelderDialog(QDialog):
    """焊工档案 + 资格项目 编辑对话框。"""

    def __init__(
        self, welder: Welder | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._welder = copy.deepcopy(welder) if welder else None
        self.setWindowTitle("编辑焊工" if welder else "新建焊工")
        self.resize(800, 680)
        self._build_ui()
        from ._screen import fit_to_screen
        fit_to_screen(self)
        if self._welder:
            self._load(self._welder)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        # 内容区包进滚动区，按钮栏固定底部（小屏幕适配）
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.addWidget(self._build_profile_group())
        content_layout.addWidget(self._build_qual_group(), stretch=1)
        from ._screen import make_scroll_content
        root.addWidget(make_scroll_content(content), stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_profile_group(self) -> QGroupBox:
        gb = QGroupBox("焊工档案")
        form = QFormLayout(gb)
        self.stamp_no = QLineEdit()
        self.cert_no = QLineEdit()
        self.name = QLineEdit()
        self.birth_date = QDateEdit()
        self.birth_date.setCalendarPopup(True)
        self.birth_date.setDate(date(1990, 1, 1))
        self.birth_date.setDisplayFormat("yyyy-MM-dd")
        self.last_work_date = QDateEdit()
        self.last_work_date.setCalendarPopup(True)
        self.last_work_date.setSpecialValueText("（未记录）")
        self.last_work_date.setDate(date.today())
        self.last_work_date.setDisplayFormat("yyyy-MM-dd")

        form.addRow("钢印号 *：", self.stamp_no)
        form.addRow("证书号：", self.cert_no)
        form.addRow("姓名：", self.name)
        form.addRow("出生日期：", self.birth_date)
        form.addRow("最近施焊日期：", self.last_work_date)
        return gb

    def _build_qual_group(self) -> QGroupBox:
        gb = QGroupBox("合格资格项目（TSG Z6002 ①-②-③-④/⑤-⑥-⑦）")
        lay = QVBoxLayout(gb)
        # 10列：试件形式(驱动) + ①方法 ②母材 ③位置 ④厚度 ⑤管径 ⑥填充金属 ⑦工艺因素 衬垫 到期
        self.qual_table = QTableWidget(0, 10)
        self.qual_table.setHorizontalHeaderLabels(
            ["试件形式", "①方法", "②母材类", "③位置", "④厚度(mm)",
             "⑤管径(mm)", "⑥填充金属", "⑦工艺因素", "衬垫", "到期日"]
        )
        self.qual_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.qual_table)
        btn_row = QHBoxLayout()
        add_q = QPushButton("+ 添加资格项目")
        add_q.clicked.connect(lambda: self._add_qual_row())
        del_q = QPushButton("− 删除选中")
        del_q.clicked.connect(self._del_qual_row)
        btn_row.addWidget(add_q)
        btn_row.addWidget(del_q)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        tip = QLabel("<small style='color:#888'>提示：在「试件形式」列选择后，「③位置」列会自动联动出对应代号。</small>")
        lay.addWidget(tip)
        # 项目代号实时预览
        self.code_preview = QLabel(
            "<small style='color:#888'>选中资格行查看项目代号预览</small>")
        lay.addWidget(self.code_preview)
        self.qual_table.itemSelectionChanged.connect(self._update_code_preview)
        return gb

    def _update_code_preview(self) -> None:
        """实时预览选中行的项目代号。"""
        rows = self.qual_table.selectionModel().selectedRows()
        if not rows:
            self.code_preview.setText(
                "<small style='color:#888'>选中资格行查看项目代号预览</small>")
            return
        r = rows[0].row()
        try:
            proc_raw = self.qual_table.cellWidget(r, 1).currentData()
            proc = (proc_raw if isinstance(proc_raw, WeldingProcess)
                    else WeldingProcess(proc_raw))
            pos_raw = self.qual_table.cellWidget(r, 3).currentData()
            pos = (pos_raw if isinstance(pos_raw, Position)
                   else Position(pos_raw))
            fa_widget = self.qual_table.cellWidget(r, 7)
            if isinstance(fa_widget, MultiFactorButton):
                factors = fa_widget.selected_factors()
            else:
                txt = fa_widget.currentText().strip()
                factors = txt.split("+") if "+" in txt else ([txt] if txt else [])
            q = WelderQualification(
                process=proc,
                material_category=self.qual_table.cellWidget(r, 2).currentText(),
                position=pos,
                deposited_thickness=self.qual_table.cellWidget(r, 4).value(),
                outer_diameter=(self.qual_table.cellWidget(r, 5).value() or None),
                fill_metal_class=self.qual_table.cellWidget(r, 6).currentText().strip(),
                process_factors=factors,
                has_backing=self.qual_table.cellWidget(r, 8).isChecked(),
            )
            self.code_preview.setText(
                f"<b style='color:#1565c0'>项目代号：{q.project_code}</b>")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 资格项目行操作
    # ------------------------------------------------------------------

    def _add_qual_row(self, q: WelderQualification | None = None) -> None:
        row = self.qual_table.rowCount()
        self.qual_table.insertRow(row)

        # col0: 试件形式（驱动该行位置列表，每行独立联动）
        form_combo = QComboBox()
        form_combo.addItems(_SPECIMEN_FORMS)
        # col1: ①方法
        proc = QComboBox()
        for p, lab in _PROCESS_ITEMS:
            proc.addItem(lab, p)
        # col2: ②母材类
        mat = QComboBox()
        mat.setEditable(True)
        mat.addItems(_MATERIAL_CATEGORIES)
        # col3: ③位置（由试件形式联动填充）
        pos = QComboBox()
        # col4: ④厚度
        thick = QDoubleSpinBox()
        thick.setRange(0, 200); thick.setDecimals(1); thick.setValue(12.0)
        # col5: ⑤管径
        dia = QDoubleSpinBox()
        dia.setRange(0, 5000); dia.setDecimals(1); dia.setValue(0)
        dia.setSpecialValueText("（板材）")
        # col6: ⑥填充金属类别
        fill_metal = QComboBox()
        fill_metal.setEditable(True)
        fill_metal.addItems(_FILL_METAL_CLASSES)
        # col7: ⑦工艺因素（多选）
        factor = MultiFactorButton(_PROCESS_FACTORS.get(WeldingProcess.SMAW, []))
        # col8: 衬垫
        backing = QCheckBox("带衬垫")
        # col9: 到期日
        expire = QDateEdit()
        expire.setCalendarPopup(True)
        expire.setDisplayFormat("yyyy-MM-dd")
        expire.setDate(date.today().replace(year=date.today().year + 4))

        widgets = [form_combo, proc, mat, pos, thick, dia, fill_metal, factor, backing, expire]
        for col, w in enumerate(widgets):
            self.qual_table.setCellWidget(row, col, w)

        # 联动：试件形式变化 → 该行位置列表 + 管径启用（每行独立）
        form_combo.currentTextChanged.connect(
            lambda t, r=row, p=pos, d=dia: self._on_form_change(r, t, p, d))
        # 联动：焊接方法 → 工艺因素预设项刷新
        proc.currentIndexChanged.connect(
            lambda _, r=row, pr=proc, fa=factor: self._on_process_change_row(r, pr, fa))

        if q is not None:
            proc.setCurrentText(next((l for p, l in _PROCESS_ITEMS if p == q.process), ""))
            mat.setEditText(q.material_category)
            thick.setValue(q.deposited_thickness)
            dia.setValue(q.outer_diameter or 0)
            # 根据位置推断试件形式，先设试件形式（触发联动填充位置列表）
            init_form = q.position.form_type
            form_combo.blockSignals(True)
            form_combo.setCurrentText(init_form)
            form_combo.blockSignals(False)
            self._on_form_change(row, init_form, pos, dia)
            pos.setCurrentText(q.position.value)
            fill_metal.setEditText(q.fill_metal_class)
            self._on_process_change_row(row, proc, factor)
            factor.set_selected(q.process_factors)
            backing.setChecked(q.has_backing)
            if q.expire_date:
                from PySide6.QtCore import QDate
                expire.setDate(QDate(q.expire_date.year, q.expire_date.month,
                                     q.expire_date.day))
        else:
            # 新行：不预填试件形式，位置列表为空提示用户先选形式
            pos.addItem("（请先选试件形式）", None)
            dia.setEnabled(False)
            self._on_process_change_row(row, proc, factor)

    def _on_form_change(self, row: int, form_text: str,
                        pos_combo: QComboBox, dia_spin: QDoubleSpinBox) -> None:
        """试件形式联动：刷新位置列表 + 启用/禁用管径。"""
        positions = _positions_for_form(form_text)
        cur = pos_combo.currentData()
        pos_combo.blockSignals(True)
        pos_combo.clear()
        for p in positions:
            pos_combo.addItem(p.value, p)
        # 尝试恢复选中
        if cur is not None:
            idx = pos_combo.findData(cur)
            if idx >= 0:
                pos_combo.setCurrentIndex(idx)
        pos_combo.blockSignals(False)
        # 管板/管对接启用管径，板材禁用
        is_tube = "管" in form_text
        dia_spin.setEnabled(is_tube)
        if is_tube and dia_spin.value() == 0:
            dia_spin.setValue(60)  # 典型管径
        elif not is_tube:
            dia_spin.setValue(0)

    def _on_process_change_row(self, row: int, proc_combo: QComboBox,
                               factor_combo) -> None:
        """焊接方法联动：刷新工艺因素预设项（多选按钮）。"""
        proc_raw = proc_combo.currentData()
        proc = (proc_raw if isinstance(proc_raw, WeldingProcess)
                else WeldingProcess(proc_raw))
        items = _PROCESS_FACTORS.get(proc, [])
        # MultiFactorButton 用 set_items；旧式 QComboBox 兼容
        if isinstance(factor_combo, MultiFactorButton):
            factor_combo.set_items(items)
        else:
            cur = factor_combo.currentText()
            factor_combo.blockSignals(True)
            factor_combo.clear()
            for f in items:
                factor_combo.addItem(f)
            factor_combo.blockSignals(False)
            if cur:
                factor_combo.setEditText(cur)

    def _del_qual_row(self) -> None:
        rows = sorted(
            {i.row() for i in self.qual_table.selectedIndexes()}, reverse=True
        )
        for r in rows:
            self.qual_table.removeRow(r)

    # ------------------------------------------------------------------
    # 加载 / 收集
    # ------------------------------------------------------------------

    def _load(self, w: Welder) -> None:
        self.stamp_no.setText(w.stamp_no)
        self.cert_no.setText(w.cert_no)
        self.name.setText(w.name)
        if w.birth_date:
            from PySide6.QtCore import QDate
            self.birth_date.setDate(
                QDate(w.birth_date.year, w.birth_date.month, w.birth_date.day))
        if w.last_work_date:
            from PySide6.QtCore import QDate
            self.last_work_date.setDate(
                QDate(w.last_work_date.year, w.last_work_date.month,
                      w.last_work_date.day))
        for q in w.qualifications:
            self._add_qual_row(q)

    def _collect(self) -> Welder:
        from PySide6.QtCore import QDate

        bd = self.birth_date.date()
        lw = self.last_work_date.date()
        welder = Welder(
            stamp_no=self.stamp_no.text().strip(),
            cert_no=self.cert_no.text().strip(),
            name=self.name.text().strip(),
            birth_date=date(bd.year(), bd.month(), bd.day()),
            last_work_date=(date(lw.year(), lw.month(), lw.day())
                            if self.last_work_date.dateTime() != self.last_work_date.minimumDateTime()
                            else None),
        )
        for r in range(self.qual_table.rowCount()):
            # 新结构：col0=试件形式 col1=方法 col2=母材 col3=位置 col4=厚度
            # col5=管径 col6=填充金属 col7=因素 col8=衬垫 col9=到期
            proc_raw = self.qual_table.cellWidget(r, 1).currentData()
            proc = proc_raw if isinstance(proc_raw, WeldingProcess) else WeldingProcess(proc_raw)
            mat = self.qual_table.cellWidget(r, 2).currentText()
            pos_raw = self.qual_table.cellWidget(r, 3).currentData()
            pos = pos_raw if isinstance(pos_raw, Position) else Position(pos_raw)
            thick = self.qual_table.cellWidget(r, 4).value()
            dia = self.qual_table.cellWidget(r, 5).value()
            fill_metal = self.qual_table.cellWidget(r, 6).currentText().strip()
            fa_widget = self.qual_table.cellWidget(r, 7)
            # 工艺因素多选：从 MultiFactorButton 取选中列表，兼容旧 QComboBox
            if isinstance(fa_widget, MultiFactorButton):
                factors = fa_widget.selected_factors()
            else:
                txt = fa_widget.currentText().strip()
                factors = txt.split("+") if "+" in txt else ([txt] if txt else [])
            backing = self.qual_table.cellWidget(r, 8).isChecked()
            ed = self.qual_table.cellWidget(r, 9).date()
            welder.qualifications.append(WelderQualification(
                process=proc,
                material_category=mat,
                position=pos,
                deposited_thickness=thick,
                outer_diameter=(dia or None),
                fill_metal_class=fill_metal,
                process_factors=factors,
                specimen_form=pos.form_type,
                has_backing=backing,
                qualified_date=date.today(),
                expire_date=date(ed.year(), ed.month(), ed.day()),
            ))
        return welder

    def _on_accept(self) -> None:
        if not self.stamp_no.text().strip():
            QMessageBox.warning(self, "提示", "请填写钢印号")
            return
        self.accept()

    def get_welder(self) -> Welder:
        return self._collect()
