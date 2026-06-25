"""焊材库管理视图（标签页）。

展示全部焊材（系统内置 YAML + 用户自定义 DB），支持新增/编辑/删除。
用户自定义焊材存数据库，确保在成本计算、工艺评定等处可见。

内置焊材（来自 YAML）标记为只读，编辑时会提示另存为自定义。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain.consumable import Consumable, ConsumableType
from ..domain.enums import WeldingProcess
from ..persistence import ConsumableRepository, get_session


class ConsumableView(QWidget):
    """焊材库管理标签页。"""

    def __init__(self):
        super().__init__()
        self._repo = ConsumableRepository(get_session())
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 工具栏
        bar = QHBoxLayout()
        bar.addWidget(QLabel("📚 焊材库（内置 + 用户自定义）"))
        bar.addStretch()
        self.btn_add = QPushButton("➕ 新增焊材")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_edit = QPushButton("✏ 编辑")
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_del = QPushButton("🗑 删除")
        self.btn_del.clicked.connect(self._on_del)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self._refresh)
        for b in (self.btn_add, self.btn_edit, self.btn_del, self.btn_refresh):
            bar.addWidget(b)
        root.addLayout(bar)

        # 焊材表格
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["牌号", "型号", "类型", "适用方法", "直径(mm)", "价格(元/kg)", "标准", "来源"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.table, stretch=1)

        tip = QLabel(
            "<small style='color:#888'>内置焊材（YAML）只读；"
            "新增/编辑的焊材存数据库，自动在成本计算、工艺评定中可用。</small>"
        )
        root.addWidget(tip)

    def _all_consumables(self) -> tuple[list[Consumable], set[str]]:
        """返回(全部焊材, 用户自定义brand集合)。内置+DB合并，DB覆盖同名。"""
        from ..standards import get_default_standard
        std = get_default_standard()
        builtin = std.all_consumables()  # 已含DB合并
        custom_brands = {c.brand for c in self._repo.list_all()}
        return builtin, custom_brands

    def _refresh(self) -> None:
        consumables, custom_brands = self._all_consumables()
        self.table.setRowCount(0)
        for c in consumables:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(c.brand))
            self.table.setItem(row, 1, QTableWidgetItem(c.model))
            self.table.setItem(row, 2, QTableWidgetItem(c.type.cn))
            procs = c.applicable_processes()
            self.table.setItem(row, 3, QTableWidgetItem(", ".join(procs)))
            self.table.setItem(row, 4, QTableWidgetItem(
                f"{c.diameter:g}" if c.diameter else ""))
            self.table.setItem(row, 5, QTableWidgetItem(
                f"{c.price:g}" if c.price > 0 else "—"))
            self.table.setItem(row, 6, QTableWidgetItem(c.standard))
            src = "自定义" if c.brand in custom_brands else "内置"
            item = QTableWidgetItem(src)
            if src == "内置":
                item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 7, item)

    def _selected_brand(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).text()

    def _on_add(self) -> None:
        dlg = ConsumableEditDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            c = dlg.get_consumable()
            try:
                self._repo.save(c)
                self._refresh()
                QMessageBox.information(self, "成功", f"已添加焊材：{c.brand}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _on_edit(self) -> None:
        brand = self._selected_brand()
        if not brand:
            QMessageBox.information(self, "提示", "请先选中一个焊材")
            return
        _, custom_brands = self._all_consumables()
        if brand not in custom_brands:
            # 内置只读：提示另存为自定义
            ret = QMessageBox.question(
                self, "内置焊材",
                f"「{brand}」是系统内置焊材（只读）。\n是否另存为自定义焊材进行编辑？",
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        existing = self._repo.get(brand)
        if existing is None:
            # 内置但DB无副本：取内置值作编辑初始
            from ..standards import get_default_standard
            existing = get_default_standard().get_consumable(brand)
        dlg = ConsumableEditDialog(parent=self, consumable=existing)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            c = dlg.get_consumable()
            try:
                self._repo.save(c)
                self._refresh()
                QMessageBox.information(self, "成功", f"已保存焊材：{c.brand}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _on_del(self) -> None:
        brand = self._selected_brand()
        if not brand:
            QMessageBox.information(self, "提示", "请先选中一个焊材")
            return
        _, custom_brands = self._all_consumables()
        if brand not in custom_brands:
            QMessageBox.information(self, "提示", f"「{brand}」是内置焊材，不可删除")
            return
        ret = QMessageBox.question(
            self, "确认删除", f"确定删除自定义焊材「{brand}」？",
        )
        if ret == QMessageBox.StandardButton.Yes:
            if self._repo.delete(brand):
                self._refresh()
                QMessageBox.information(self, "成功", "已删除")


class ConsumableEditDialog(QDialog):
    """焊材新增/编辑对话框（含适用方法多选 + 价格）。"""

    def __init__(self, parent=None, consumable: Consumable | None = None):
        super().__init__(parent)
        self.setWindowTitle("编辑焊材" if consumable else "新增焊材")
        self.resize(480, 460)
        self._build_ui(consumable)
        from ._screen import fit_to_screen
        fit_to_screen(self)

    def _build_ui(self, c: Consumable | None) -> None:
        form = QFormLayout(self)

        self.brand = QLineEdit(c.brand if c else "")
        self.brand.setPlaceholderText("如 J507、ER50-6")
        form.addRow("牌号 *：", self.brand)

        self.model = QLineEdit(c.model if c else "")
        self.model.setPlaceholderText("如 E5015、ER50-6")
        form.addRow("型号 *：", self.model)

        self.type = QComboBox()
        for t in ConsumableType:
            self.type.addItem(t.cn, t)
        if c:
            idx = self.type.findData(c.type)
            if idx >= 0:
                self.type.setCurrentIndex(idx)
        form.addRow("焊材类型 *：", self.type)

        self.classification_slot = QLineEdit(c.classification_slot if c else "")
        self.classification_slot.setPlaceholderText("如 表2-E50（变更判定基准）")
        form.addRow("分类栏位：", self.classification_slot)

        self.standard = QLineEdit(c.standard if c else "")
        self.standard.setPlaceholderText("如 GB/T 5118")
        form.addRow("产品标准：", self.standard)

        self.diameter = QDoubleSpinBox()
        self.diameter.setRange(0, 30); self.diameter.setSingleStep(0.5)
        self.diameter.setDecimals(1); self.diameter.setValue(c.diameter or 3.2)
        self.diameter.setSuffix(" mm")
        form.addRow("直径：", self.diameter)

        self.price = QDoubleSpinBox()
        self.price.setRange(0, 100000); self.price.setSingleStep(0.5)
        self.price.setDecimals(2); self.price.setValue(c.price if c else 0)
        self.price.setSuffix(" 元/kg")
        form.addRow("参考价格：", self.price)

        # 适用焊接方法多选
        proc_box = QWidget()
        proc_lay = QHBoxLayout(proc_box)
        proc_lay.setContentsMargins(0, 0, 0, 0)
        self.proc_checks: dict[str, QCheckBox] = {}
        for p in (WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.GMAW,
                  WeldingProcess.FCAW, WeldingProcess.SAW):
            cb = QCheckBox(p.value)
            cb.setToolTip(p.cn)
            self.proc_checks[p.value] = cb
            proc_lay.addWidget(cb)
        if c and c.processes:
            for code in c.processes:
                if code in self.proc_checks:
                    self.proc_checks[code].setChecked(True)
        form.addRow("适用方法：", proc_box)
        hint = QLabel("<small style='color:#888'>不勾选时按类型自动推断"
                      "（焊条→SMAW、焊丝→GTAW/GMAW/FCAW）</small>")
        form.addRow("", hint)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _on_accept(self) -> None:
        if not self.brand.text().strip():
            QMessageBox.warning(self, "提示", "请填写牌号")
            return
        if not self.model.text().strip():
            QMessageBox.warning(self, "提示", "请填写型号")
            return
        self.accept()

    def get_consumable(self) -> Consumable:
        procs = [code for code, cb in self.proc_checks.items() if cb.isChecked()]
        return Consumable(
            brand=self.brand.text().strip(),
            model=self.model.text().strip(),
            type=self.type.currentData(),
            classification_slot=self.classification_slot.text().strip() or "—",
            standard=self.standard.text().strip(),
            diameter=self.diameter.value() or None,
            price=self.price.value(),
            processes=procs,
        )
