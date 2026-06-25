"""工艺文件编辑对话框。

支持新建/编辑 pWPS / WPS / PQR，编辑全部字段：
  表头（编号/方法/类型/依据PQR/标准/冲击）
  母材（从标准库选择 + 厚度）
  焊材（牌号/型号/分类栏位/直径）
  接头/坡口
  焊道参数表（可增删行）
  预热 / PWHT / 焊接位置

编辑结果以 Procedure 领域对象返回（QDialog.Accepted 时通过 get_procedure() 取）。
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain.base_metal import BaseMetal, BaseMetalThicknessPair
from ..domain.consumable import Consumable, ConsumableType
from ..domain.enums import (
    CurrentType,
    JointType,
    MaterialGroup,
    Mechanization,
    Position,
    ProcedureType,
    WeldingProcess,
)
from ..domain.joint import GrooveDesign, Joint
from ..domain.procedure import PassLayer, Procedure, PWHTSpec
from ..standards.base import StandardProfile


_PROCESS_ITEMS = [
    (WeldingProcess.SMAW, "SMAW 焊条电弧焊"),
    (WeldingProcess.GTAW, "GTAW 钨极氩弧焊"),
    (WeldingProcess.SAW, "SAW 埋弧焊"),
    (WeldingProcess.GMAW, "GMAW 熔化极气保焊"),
    (WeldingProcess.FCAW, "FCAW 药芯焊丝"),
    (WeldingProcess.PAW, "PAW 等离子弧焊"),
]


def _process_label(p: WeldingProcess) -> str:
    """焊接方法下拉显示文本：代号+中文名。"""
    return next((lab for proc, lab in _PROCESS_ITEMS if proc == p), f"{p.value} {p.cn}")


def _coerce_enum(value, enum_cls):
    """把 QComboBox.currentData() 返回值强制转回枚举。

    Qt 对 (str,Enum) 会把 data 退化为纯 str；已是枚举则原样返回。
    """
    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    return enum_cls(value)
_POSITION_ITEMS = [
    Position.PLATE_1G, Position.PLATE_2G, Position.PLATE_3G, Position.PLATE_4G,
    Position.PIPE_1G, Position.PIPE_2G, Position.PIPE_5G, Position.PIPE_6G,
]
_CURRENT_ITEMS = [
    (CurrentType.DCEP, "直流反接 DCEP"),
    (CurrentType.DCEN, "直流正接 DCEN"),
    (CurrentType.AC, "交流 AC"),
    (CurrentType.PULSE, "脉冲"),
    (CurrentType.VP, "变极性 VP"),
]


class ProcedureDialog(QDialog):
    """工艺文件编辑对话框。"""

    def __init__(
        self,
        standard: StandardProfile,
        procedure: Procedure | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.standard = standard
        self._procedure = copy.deepcopy(procedure) if procedure else None
        self.setWindowTitle(
            "编辑工艺文件" if procedure else "新建工艺文件"
        )
        self.resize(900, 720)
        self._build_ui()
        self._fit_to_screen()
        if self._procedure:
            self._load_from_procedure(self._procedure)

    def _fit_to_screen(self) -> None:
        """根据可用屏幕尺寸自适应：小屏幕上把窗口限制在可视区内。

        避免固定 resize(900,720) 在 1366x768 笔记本上底部按钮被任务栏遮挡。
        """
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is None:
            return
        w, h = self.width(), self.height()
        # 留出一些边距，确保不被任务栏遮挡
        max_h = screen.height() - 40
        max_w = screen.width() - 40
        if h > max_h:
            self.resize(min(w, max_w), max_h)
        elif w > max_w:
            self.resize(max_w, h)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # 内容区包裹在 QScrollArea 中：小屏幕上可滚动，按钮始终可见
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)

        content_layout.addWidget(self._build_header_group())
        content_layout.addWidget(self._build_doc_info_group())
        content_layout.addWidget(self._build_base_metal_group())
        content_layout.addWidget(self._build_consumable_group())
        content_layout.addWidget(self._build_joint_group())
        content_layout.addWidget(self._build_pass_group(), stretch=1)
        content_layout.addWidget(self._build_post_group())

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

        # 按钮区固定在底部（不随滚动）
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_header_group(self) -> QGroupBox:
        gb = QGroupBox("表头")
        form = QFormLayout(gb)
        self.doc_no = QLineEdit()
        self.type_combo = QComboBox()
        for t in ProcedureType:
            self.type_combo.addItem(t.value, t)
        self.process_combo = QComboBox()
        for p, label in _PROCESS_ITEMS:
            self.process_combo.addItem(label, p)
        self.mech_combo = QComboBox()
        for m in Mechanization:
            self.mech_combo.addItem(m.cn, m)
        self.supporting_pqr = QLineEdit()
        self.impact_check = QCheckBox("有冲击试验要求")

        form.addRow("文件编号：", self.doc_no)
        form.addRow("类型：", self.type_combo)
        form.addRow("焊接方法：", self.process_combo)
        form.addRow("机械化：", self.mech_combo)
        form.addRow("依据PQR编号：", self.supporting_pqr)
        form.addRow("冲击要求：", self.impact_check)
        return gb

    def _build_doc_info_group(self) -> QGroupBox:
        """文档元信息分组（单位/项目/图号/签字人，用于报表表头）。"""
        gb = QGroupBox("文档信息（用于报表表头 / 特检院报检）")
        form = QFormLayout(gb)
        self.manufacturer = QLineEdit()
        self.manufacturer.setPlaceholderText("编制单位名称")
        self.project_no = QLineEdit()
        self.project_no.setPlaceholderText("项目/产品编号")
        self.drawing_no = QLineEdit()
        self.drawing_no.setPlaceholderText("产品图号")
        self.prepared_by = QLineEdit()
        self.reviewed_by = QLineEdit()
        self.approved_by = QLineEdit()
        self.prepare_date = QLineEdit()
        self.prepare_date.setPlaceholderText("如 2026-06-24")

        form.addRow("编制单位：", self.manufacturer)
        form.addRow("项目编号：", self.project_no)
        form.addRow("产品图号：", self.drawing_no)
        # 签字人一行三个
        signer_row = QHBoxLayout()
        signer_row.addWidget(QLabel("编制:")); signer_row.addWidget(self.prepared_by)
        signer_row.addWidget(QLabel("审核:")); signer_row.addWidget(self.reviewed_by)
        signer_row.addWidget(QLabel("批准:")); signer_row.addWidget(self.approved_by)
        signer_w = QWidget(); signer_w.setLayout(signer_row)
        form.addRow("签字人：", signer_w)
        form.addRow("编制日期：", self.prepare_date)
        return gb

    def _build_base_metal_group(self) -> QGroupBox:
        gb = QGroupBox("母材（从标准库选择）")
        lay = QVBoxLayout(gb)
        self.bm_table = QTableWidget(0, 5)
        self.bm_table.setHorizontalHeaderLabels(
            ["牌号", "类别号", "组别号", "厚度(mm)", ""]
        )
        self.bm_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.bm_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.bm_table)
        btn_row = QHBoxLayout()
        add_bm = QPushButton("+ 添加母材")
        add_bm.clicked.connect(lambda: self._add_base_metal_row())
        del_bm = QPushButton("− 删除选中")
        del_bm.clicked.connect(lambda: self._del_selected_row(self.bm_table, 4))
        btn_row.addWidget(add_bm)
        btn_row.addWidget(del_bm)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return gb

    def _build_consumable_group(self) -> QGroupBox:
        gb = QGroupBox("焊接材料")
        lay = QVBoxLayout(gb)
        self.cons_table = QTableWidget(0, 5)
        self.cons_table.setHorizontalHeaderLabels(
            ["牌号", "型号", "分类栏位", "直径(mm)", "类型"]
        )
        self.cons_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.cons_table)
        btn_row = QHBoxLayout()
        add_c = QPushButton("+ 添加焊材")
        add_c.clicked.connect(lambda: self._add_consumable_row())
        del_c = QPushButton("− 删除选中")
        del_c.clicked.connect(lambda: self._del_selected_row(self.cons_table))
        btn_row.addWidget(add_c)
        btn_row.addWidget(del_c)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return gb

    def _build_joint_group(self) -> QGroupBox:
        gb = QGroupBox("接头与坡口")
        form = QFormLayout(gb)
        self.joint_type = QComboBox()
        for j in JointType:
            self.joint_type.addItem(j.cn, j)
        self.groove_type = QComboBox()
        self.groove_type.addItems(["V", "U", "X", "I"])
        self.groove_type.setCurrentText("V")
        self.groove_angle = QDoubleSpinBox()
        self.groove_angle.setRange(0, 180); self.groove_angle.setValue(60)
        self.groove_angle.setDecimals(0)
        self.root_face = QDoubleSpinBox()
        self.root_face.setRange(0, 50); self.root_face.setValue(2)
        self.root_face.setDecimals(1)
        self.root_gap = QDoubleSpinBox()
        self.root_gap.setRange(0, 20); self.root_gap.setValue(2)
        self.root_gap.setDecimals(1)
        self.backing_check = QCheckBox("带衬垫")
        self.outer_diameter = QDoubleSpinBox()
        self.outer_diameter.setRange(0, 5000); self.outer_diameter.setValue(0)
        self.outer_diameter.setDecimals(1)
        self.outer_diameter.setSpecialValueText("（板材/无）")

        form.addRow("接头形式：", self.joint_type)
        form.addRow("坡口形式：", self.groove_type)
        form.addRow("坡口角度(°)：", self.groove_angle)
        form.addRow("钝边(mm)：", self.root_face)
        form.addRow("根部间隙(mm)：", self.root_gap)
        form.addRow("管外径(mm)：", self.outer_diameter)
        form.addRow("衬垫：", self.backing_check)
        return gb

    def _build_pass_group(self) -> QGroupBox:
        gb = QGroupBox("焊道参数（按焊道，支持组合焊：每道可选独立方法）")
        lay = QVBoxLayout(gb)
        self.pass_table = QTableWidget(0, 9)
        self.pass_table.setHorizontalHeaderLabels(
            ["层次", "焊接方法", "焊材牌号", "直径(mm)", "电流下限(A)", "电流上限(A)",
             "电压下限(V)", "电压上限(V)", "极性"]
        )
        self.pass_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        lay.addWidget(self.pass_table)
        btn_row = QHBoxLayout()
        add_p = QPushButton("+ 添加焊道")
        add_p.clicked.connect(lambda: self._add_pass_row())
        del_p = QPushButton("− 删除选中")
        del_p.clicked.connect(lambda: self._del_selected_row(self.pass_table))
        btn_row.addWidget(add_p)
        btn_row.addWidget(del_p)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return gb

    def _build_post_group(self) -> QGroupBox:
        gb = QGroupBox("预热 / 焊后热处理 / 焊接位置")
        form = QFormLayout(gb)
        self.preheat = QDoubleSpinBox()
        self.preheat.setRange(0, 800); self.preheat.setValue(0)
        self.preheat.setDecimals(0)
        self.preheat.setSpecialValueText("（无预热）")

        self.pwht_apply = QCheckBox("进行焊后热处理")
        self.pwht_type = QLineEdit()
        self.pwht_upper = QCheckBox("上转变温度热处理（影响补加因素失效）")
        self.pwht_austenitic = QCheckBox("奥氏体固溶处理（影响补加因素失效）")
        self.pwht_temp_min = QDoubleSpinBox()
        self.pwht_temp_min.setRange(0, 1500); self.pwht_temp_min.setDecimals(0)
        self.pwht_temp_max = QDoubleSpinBox()
        self.pwht_temp_max.setRange(0, 1500); self.pwht_temp_max.setDecimals(0)
        self.pwht_hold = QDoubleSpinBox()
        self.pwht_hold.setRange(0, 100000); self.pwht_hold.setDecimals(0)

        self.position_combo = QComboBox()
        for p in _POSITION_ITEMS:
            self.position_combo.addItem(p.value, p)

        form.addRow("最低预热温度(℃)：", self.preheat)
        form.addRow(self.pwht_apply)
        form.addRow("PWHT类型：", self.pwht_type)
        form.addRow("PWHT温度(℃)：",
                    self._hbox(self.pwht_temp_min, QLabel("~"), self.pwht_temp_max))
        form.addRow("保温时间(min)：", self.pwht_hold)
        form.addRow(self.pwht_upper)
        form.addRow(self.pwht_austenitic)
        form.addRow("焊接位置：", self.position_combo)
        return gb

    def _hbox(self, *widgets) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            lay.addWidget(x)
        lay.addStretch()
        return w

    # ------------------------------------------------------------------
    # 表格行操作
    # ------------------------------------------------------------------

    def _add_base_metal_row(self, grade: str = "", thickness: float = 0.0) -> None:
        metals = {m.grade: m for m in self.standard.all_base_metals()}
        row = self.bm_table.rowCount()
        self.bm_table.insertRow(row)
        grade_combo = QComboBox()
        grade_combo.setEditable(True)
        for g in sorted(metals.keys()):
            grade_combo.addItem(g)
        if grade:
            grade_combo.setEditText(grade)
        grade_combo.currentTextChanged.connect(
            lambda txt, r=row: self._on_grade_changed(r, txt)
        )
        self.bm_table.setCellWidget(row, 0, grade_combo)
        cat_item = QTableWidgetItem("")
        grp_item = QTableWidgetItem("")
        cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        grp_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.bm_table.setItem(row, 1, cat_item)
        self.bm_table.setItem(row, 2, grp_item)
        thick = QDoubleSpinBox()
        thick.setRange(0, 500); thick.setDecimals(1); thick.setValue(thickness)
        self.bm_table.setCellWidget(row, 3, thick)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda _, r=row: self.bm_table.removeRow(r))
        self.bm_table.setCellWidget(row, 4, del_btn)
        self._on_grade_changed(row, grade_combo.currentText())

    def _on_grade_changed(self, row: int, grade: str) -> None:
        metal = self.standard.get_base_metal(grade)
        if metal:
            self.bm_table.item(row, 1).setText(metal.category)
            self.bm_table.item(row, 2).setText(metal.group.group)

    def _add_consumable_row(
        self, brand: str = "", model: str = "", slot: str = "",
        diameter: float = 0.0, ctype: ConsumableType = ConsumableType.ELECTRODE,
    ) -> None:
        row = self.cons_table.rowCount()
        self.cons_table.insertRow(row)
        # 牌号：可编辑下拉 + 智能匹配（从焊材库加载，便于选标准库焊材）
        brand_combo = QComboBox()
        brand_combo.setEditable(True)
        brand_combo.addItems(self._library_brands())
        brand_combo.setCurrentText(brand)
        self.cons_table.setCellWidget(row, 0, brand_combo)
        # 型号/分类栏位联动：牌号变化时从库中查找
        brand_combo.currentTextChanged.connect(
            lambda t, r=row: self._on_brand_changed(r, t))
        self.cons_table.setItem(row, 1, QTableWidgetItem(model))
        self.cons_table.setItem(row, 2, QTableWidgetItem(slot))
        dia = QDoubleSpinBox()
        dia.setRange(0, 20); dia.setDecimals(1); dia.setValue(diameter)
        self.cons_table.setCellWidget(row, 3, dia)
        type_combo = QComboBox()
        for t in ConsumableType:
            type_combo.addItem(t.cn, t)
        type_combo.setCurrentText(ctype.cn)
        self.cons_table.setCellWidget(row, 4, type_combo)

    def _library_brands(self) -> list[str]:
        """焊材库全部牌号（内置+用户自定义）。"""
        try:
            return [c.brand for c in self.standard.all_consumables()]
        except Exception:
            return []

    def _on_brand_changed(self, row: int, brand: str) -> None:
        """牌号变化：若库中存在，自动联动型号/分类栏位/类型/直径。"""
        brand = brand.strip()
        if not brand:
            return
        c = self.standard.get_consumable(brand)
        if c is None:
            return
        if self.cons_table.item(row, 1):
            self.cons_table.item(row, 1).setText(c.model)
        if self.cons_table.item(row, 2):
            self.cons_table.item(row, 2).setText(c.classification_slot)
        dia = self.cons_table.cellWidget(row, 3)
        if dia and c.diameter:
            dia.setValue(c.diameter)
        tc = self.cons_table.cellWidget(row, 4)
        if tc:
            idx = tc.findData(c.type)
            if idx >= 0:
                tc.setCurrentIndex(idx)

    def _add_pass_row(
        self, role: str = "填充", process: WeldingProcess | None = None,
        brand: str = "", diameter: float = 0.0,
        i_min: float = 0, i_max: float = 0, v_min: float = 0, v_max: float = 0,
        ctype: CurrentType | None = None,
    ) -> None:
        row = self.pass_table.rowCount()
        self.pass_table.insertRow(row)
        self.pass_table.setItem(row, 0, QTableWidgetItem(role))
        # 焊接方法下拉（组合焊支持：每道可选独立方法，默认"（继承）"）
        proc_combo = QComboBox()
        proc_combo.addItem("（继承）", None)
        for p, lab in _PROCESS_ITEMS:
            proc_combo.addItem(lab, p)
        if process is not None:
            idx = proc_combo.findData(process)
            if idx >= 0:
                proc_combo.setCurrentIndex(idx)
        self.pass_table.setCellWidget(row, 1, proc_combo)
        self.pass_table.setItem(row, 2, QTableWidgetItem(brand))

        def spin(val, lo, hi, dec=0):
            s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec)
            s.setValue(val); return s

        self.pass_table.setCellWidget(row, 3, spin(diameter, 0, 20, 1))
        self.pass_table.setCellWidget(row, 4, spin(i_min, 0, 2000))
        self.pass_table.setCellWidget(row, 5, spin(i_max, 0, 2000))
        self.pass_table.setCellWidget(row, 6, spin(v_min, 0, 100))
        self.pass_table.setCellWidget(row, 7, spin(v_max, 0, 100))
        ct = QComboBox()
        for c, lab in _CURRENT_ITEMS:
            ct.addItem(lab, c)
        if ctype is not None:
            idx = ct.findData(ctype)
            if idx >= 0:
                ct.setCurrentIndex(idx)
        self.pass_table.setCellWidget(row, 8, ct)

    def _del_selected_row(self, table: QTableWidget, *_):
        rows = sorted(
            {i.row() for i in table.selectedIndexes()}, reverse=True
        )
        for r in rows:
            table.removeRow(r)

    # ------------------------------------------------------------------
    # 加载 / 收集
    # ------------------------------------------------------------------

    def _load_from_procedure(self, p: Procedure) -> None:
        self.doc_no.setText(p.doc_no)
        self.type_combo.setCurrentText(p.type.value)
        self.process_combo.setCurrentText(_process_label(p.process))
        self.mech_combo.setCurrentText(p.mechanization.cn)
        self.supporting_pqr.setText(p.supporting_pqr_no)
        self.impact_check.setChecked(p.impact_required)
        # 文档信息
        self.manufacturer.setText(p.manufacturer)
        self.project_no.setText(p.project_no)
        self.drawing_no.setText(p.drawing_no)
        self.prepared_by.setText(p.prepared_by)
        self.reviewed_by.setText(p.reviewed_by)
        self.approved_by.setText(p.approved_by)
        self.prepare_date.setText(p.prepare_date)

        for bm in p.base_metals:
            self._add_base_metal_row(bm.metal.grade, bm.thickness)
        for c in p.consumables:
            self._add_consumable_row(c.brand, c.model, c.classification_slot,
                                     c.diameter or 0.0, c.type)
        if p.joints:
            j = p.joints[0]
            self.joint_type.setCurrentText(j.type.cn)
            self.groove_type.setCurrentText(j.groove.type)
            self.groove_angle.setValue(j.groove.angle or 60)
            self.root_face.setValue(j.groove.root_face or 0)
            self.root_gap.setValue(j.groove.root_gap or 0)
            self.backing_check.setChecked(j.groove.has_backing)
            self.outer_diameter.setValue(j.outer_diameter or 0)
        for pa in p.passes:
            self._add_pass_row(
                pa.layer_role,
                pa.process,
                pa.consumable.brand if pa.consumable else "",
                pa.diameter or 0.0,
                pa.current_min or 0, pa.current_max or 0,
                pa.voltage_min or 0, pa.voltage_max or 0,
                pa.current_type,
            )
        self.preheat.setValue(p.preheat_min or 0)
        pwht = p.pwht
        self.pwht_apply.setChecked(pwht.applied)
        self.pwht_type.setText(pwht.pwht_type)
        self.pwht_upper.setChecked(pwht.upper_transformation)
        self.pwht_austenitic.setChecked(pwht.austenitic_solution_treated)
        self.pwht_temp_min.setValue(pwht.temp_min or 0)
        self.pwht_temp_max.setValue(pwht.temp_max or 0)
        self.pwht_hold.setValue(pwht.hold_time or 0)
        if p.positions:
            self.position_combo.setCurrentText(p.positions[0].value)

    def _collect(self) -> Procedure:
        """从表单收集为 Procedure 领域对象。"""
        doc_no = self.doc_no.text().strip() or "未命名"
        # Qt 会把 (str,Enum) currentData 退化为纯 str，强制转回枚举
        proc_type = _coerce_enum(self.type_combo.currentData(), ProcedureType)
        process = _coerce_enum(self.process_combo.currentData(), WeldingProcess)
        mech = _coerce_enum(self.mech_combo.currentData(), Mechanization)

        # 母材
        base_metals: list[BaseMetalThicknessPair] = []
        for r in range(self.bm_table.rowCount()):
            grade_combo = self.bm_table.cellWidget(r, 0)
            if grade_combo is None:
                continue
            grade = grade_combo.currentText().strip()
            if not grade:
                continue
            metal = self.standard.get_base_metal(grade)
            if metal is None:
                metal = BaseMetal(
                    grade=grade,
                    group=MaterialGroup("?", grade, grade),
                    standard="",
                )
            thick = self.bm_table.cellWidget(r, 3).value()
            base_metals.append(BaseMetalThicknessPair(metal, thick))

        # 焊材
        consumables: list[Consumable] = []
        for r in range(self.cons_table.rowCount()):
            # 牌号现在是 QComboBox（cellWidget），型号/栏位仍是 QTableWidgetItem
            brand_widget = self.cons_table.cellWidget(r, 0)
            brand = brand_widget.currentText().strip() if brand_widget else ""
            if not brand:
                continue
            consumables.append(Consumable(
                brand=brand,
                model=self.cons_table.item(r, 1).text().strip(),
                classification_slot=self.cons_table.item(r, 2).text().strip(),
                standard="",
                diameter=self.cons_table.cellWidget(r, 3).value(),
                type=_coerce_enum(self.cons_table.cellWidget(r, 4).currentData(), ConsumableType),
            ))

        # 接头
        joint = Joint(
            type=_coerce_enum(self.joint_type.currentData(), JointType),
            groove=GrooveDesign(
                type=self.groove_type.currentText().strip() or "V",
                angle=self.groove_angle.value(),
                root_face=self.root_face.value(),
                root_gap=self.root_gap.value(),
                has_backing=self.backing_check.isChecked(),
            ),
            outer_diameter=(self.outer_diameter.value() or None),
        )
        joints = [joint] if base_metals else []

        # 焊道
        passes: list[PassLayer] = []
        cons_by_brand = {c.brand: c for c in consumables}
        for r in range(self.pass_table.rowCount()):
            role_item = self.pass_table.item(r, 0)
            brand_item = self.pass_table.item(r, 2)
            if role_item is None or brand_item is None:
                continue
            brand = brand_item.text().strip()
            # 焊接方法（组合焊）：Qt 退化纯 str，转回枚举；None 表示继承
            proc_raw = self.pass_table.cellWidget(r, 1).currentData()
            pass_process: WeldingProcess | None = None
            if proc_raw is not None:
                pass_process = (proc_raw if isinstance(proc_raw, WeldingProcess)
                                else WeldingProcess(proc_raw))
            # 极性同样转回枚举
            ctype_raw = self.pass_table.cellWidget(r, 8).currentData()
            ctype: CurrentType | None = None
            if ctype_raw is not None:
                ctype = (ctype_raw if isinstance(ctype_raw, CurrentType)
                         else CurrentType(ctype_raw))
            passes.append(PassLayer(
                sequence=r + 1,
                layer_role=role_item.text().strip() or "填充",
                process=pass_process,
                consumable=cons_by_brand.get(brand),
                diameter=self.pass_table.cellWidget(r, 3).value() or None,
                current_min=self.pass_table.cellWidget(r, 4).value() or None,
                current_max=self.pass_table.cellWidget(r, 5).value() or None,
                voltage_min=self.pass_table.cellWidget(r, 6).value() or None,
                voltage_max=self.pass_table.cellWidget(r, 7).value() or None,
                current_type=ctype,
            ))

        # PWHT
        pwht = PWHTSpec(
            applied=self.pwht_apply.isChecked(),
            pwht_type=self.pwht_type.text().strip(),
            temp_min=self.pwht_temp_min.value() or None,
            temp_max=self.pwht_temp_max.value() or None,
            hold_time=self.pwht_hold.value() or None,
            upper_transformation=self.pwht_upper.isChecked(),
            austenitic_solution_treated=self.pwht_austenitic.isChecked(),
        )

        return Procedure(
            doc_no=doc_no,
            type=proc_type,
            process=process,
            mechanization=mech,
            base_metals=base_metals,
            consumables=consumables,
            joints=joints,
            passes=passes,
            positions=[_coerce_enum(self.position_combo.currentData(), Position)],
            preheat_min=self.preheat.value() or None,
            pwht=pwht,
            impact_required=self.impact_check.isChecked(),
            deposited_thickness=max((bm.thickness for bm in base_metals), default=None),
            supporting_pqr_no=self.supporting_pqr.text().strip(),
            standard_version=self.standard.registry_key,
            manufacturer=self.manufacturer.text().strip(),
            project_no=self.project_no.text().strip(),
            drawing_no=self.drawing_no.text().strip(),
            prepared_by=self.prepared_by.text().strip(),
            reviewed_by=self.reviewed_by.text().strip(),
            approved_by=self.approved_by.text().strip(),
            prepare_date=self.prepare_date.text().strip(),
        )

    def _on_accept(self) -> None:
        if not self.doc_no.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请填写文件编号")
            return
        self.accept()

    def get_procedure(self) -> Procedure:
        """对话框接受后调用，返回编辑后的 Procedure。"""
        return self._collect()
