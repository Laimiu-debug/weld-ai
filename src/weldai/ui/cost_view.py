"""焊接成本计算视图。

流程：先选焊接方法 → 再选焊材（按方法过滤，支持手动输入+智能匹配）
      → 绘制坡口自动算截面积 → 选中焊材联动价格/效率 → 计算。

焊材从标准库（NB/T 47014 consumables.yaml + 用户自定义 DB）加载，
按焊接方法过滤，避免无关焊材混入。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCompleter,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.cost import CostFactors, PassCostInput, WeldGeometry
from ..domain.enums import WeldingProcess
from ..engine import CostEngine


# 焊接方法 → 典型熔敷效率 / 典型熔敷速度(kg/h)
_PROCESS_PRESET = {
    WeldingProcess.SMAW: (0.55, 1.6),
    WeldingProcess.GTAW: (0.98, 0.8),
    WeldingProcess.GMAW: (0.95, 2.5),
    WeldingProcess.FCAW: (0.90, 2.2),
    WeldingProcess.SAW: (0.99, 6.0),
}
# 钢熔敷金属密度 kg/mm³
_STEEL_DENSITY = 7.85e-6


class CostView(QWidget):
    """成本计算视图（嵌入主窗口标签页）。"""

    def __init__(self):
        super().__init__()
        self._engine = CostEngine()
        self._consumables: list = []  # 当前方法下的焊材缓存
        self._groove_area: float = 50.0  # 当前坡口截面积（可由绘制对话框填入）
        self._build_ui()
        self._on_process_change()  # 初始填充焊材下拉

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self._build_input_group())
        root.addWidget(self._build_result(), stretch=1)

    def _build_input_group(self) -> QGroupBox:
        gb = QGroupBox("💰 焊接成本计算")
        lay = QVBoxLayout(gb)

        # 第1行：焊接方法（先选）+ 绘制坡口按钮
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("① 焊接方法："))
        self.process = QComboBox()
        for p in (WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.GMAW,
                  WeldingProcess.FCAW, WeldingProcess.SAW):
            self.process.addItem(f"{p.value} {p.cn}", p)
        self.process.currentIndexChanged.connect(self._on_process_change)
        row0.addWidget(self.process)
        self.btn_groove = QPushButton("📐 绘制坡口")
        self.btn_groove.clicked.connect(self._on_draw_groove)
        row0.addWidget(self.btn_groove)
        row0.addStretch()
        lay.addLayout(row0)

        # 第2行：焊材（按方法过滤，可手动输入+智能匹配）
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("② 焊材："))
        self.consumable = QComboBox()
        self.consumable.setEditable(True)  # 支持手动输入
        self.consumable.setMinimumWidth(260)
        # 智能匹配：按牌号/型号模糊补全
        self._completer = QCompleter([], self)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.consumable.setCompleter(self._completer)
        self.consumable.currentIndexChanged.connect(self._on_consumable_change)
        self.consumable.editTextChanged.connect(self._on_consumable_text)
        row1.addWidget(self.consumable)
        row1.addStretch()
        lay.addLayout(row1)

        # 第3行：坡口截面积（绘制后自动填，也可手填）+ 焊缝长度
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("坡口截面积(mm²)："))
        self.groove_area = QDoubleSpinBox()
        self.groove_area.setRange(1, 10000); self.groove_area.setValue(50)
        self.groove_area.valueChanged.connect(
            lambda v: setattr(self, "_groove_area", v))
        row2.addWidget(self.groove_area)
        row2.addWidget(QLabel("焊缝长度(mm)："))
        self.weld_length = QDoubleSpinBox()
        self.weld_length.setRange(1, 100000); self.weld_length.setValue(1000)
        row2.addWidget(self.weld_length)
        row2.addStretch()
        lay.addLayout(row2)

        # 第4行：熔敷参数
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("熔敷效率："))
        self.efficiency = QDoubleSpinBox()
        self.efficiency.setRange(0.01, 1.0); self.efficiency.setDecimals(2)
        self.efficiency.setValue(0.55)
        row3.addWidget(self.efficiency)
        row3.addWidget(QLabel("熔敷速度(kg/h)："))
        self.deposition_rate = QDoubleSpinBox()
        self.deposition_rate.setRange(0, 50); self.deposition_rate.setValue(1.6)
        self.deposition_rate.setDecimals(2)
        row3.addWidget(self.deposition_rate)
        row3.addStretch()
        lay.addLayout(row3)

        # 第5行：电参数
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("平均电流(A)："))
        self.current = QDoubleSpinBox()
        self.current.setRange(0, 2000); self.current.setValue(120)
        row4.addWidget(self.current)
        row4.addWidget(QLabel("平均电压(V)："))
        self.voltage = QDoubleSpinBox()
        self.voltage.setRange(0, 100); self.voltage.setValue(24)
        row4.addWidget(self.voltage)
        row4.addWidget(QLabel("焊接速度(cm/min)："))
        self.travel_speed = QDoubleSpinBox()
        self.travel_speed.setRange(0, 500); self.travel_speed.setValue(30)
        row4.addWidget(self.travel_speed)
        row4.addWidget(QLabel("气体流量(L/min)："))
        self.gas_flow = QDoubleSpinBox()
        self.gas_flow.setRange(0, 100); self.gas_flow.setValue(10)
        row4.addWidget(self.gas_flow)
        row4.addStretch()
        lay.addLayout(row4)

        # 第6行：价格（选中焊材后联动带入，可改）
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("焊材价(元/kg)："))
        self.mat_price = QDoubleSpinBox()
        self.mat_price.setRange(0, 100000); self.mat_price.setValue(30)
        self.mat_price.setDecimals(2)
        row5.addWidget(self.mat_price)
        row5.addWidget(QLabel("气体(元/瓶)："))
        self.gas_price = QDoubleSpinBox()
        self.gas_price.setRange(0, 10000); self.gas_price.setValue(50)
        row5.addWidget(self.gas_price)
        row5.addWidget(QLabel("人工(元/h)："))
        self.labor_rate = QDoubleSpinBox()
        self.labor_rate.setRange(0, 10000); self.labor_rate.setValue(80)
        row5.addWidget(self.labor_rate)
        row5.addStretch()
        lay.addLayout(row5)

        self.btn_calc = QPushButton("📊 计算")
        self.btn_calc.clicked.connect(self._on_calc)
        lay.addWidget(self.btn_calc)
        return gb

    def _build_result(self) -> QWidget:
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        return self.result

    # ---- 联动逻辑 ----

    def _on_process_change(self) -> None:
        """焊接方法变化：重新加载该方法的焊材 + 联动典型效率/速度。"""
        # Qt 把 (str,Enum) currentData 退化为纯 str，强制转回枚举
        p_raw = self.process.currentData()
        p = (p_raw if isinstance(p_raw, WeldingProcess)
             else WeldingProcess(p_raw))
        # 重新填充焊材下拉（按方法过滤）
        self.consumable.blockSignals(True)
        self.consumable.clear()
        self.consumable.addItem("（自定义/手填）", None)
        self._consumables = []
        try:
            from ..standards import get_default_standard
            std = get_default_standard()
            self._consumables = std.consumables_for_process(p)
            for c in self._consumables:
                label = f"{c.brand} [{c.model}]"
                if c.diameter:
                    label += f" φ{c.diameter:g}"
                if c.price > 0:
                    label += f" ¥{c.price:g}/kg"
                self.consumable.addItem(label, c)
        except Exception:
            pass
        # 更新补全候选词（牌号+型号）
        self._update_completer()
        self.consumable.blockSignals(False)
        self.consumable.setCurrentIndex(0)
        # 联动典型熔敷效率/速度
        if p in _PROCESS_PRESET:
            eff, rate = _PROCESS_PRESET[p]
            self.efficiency.setValue(eff)
            self.deposition_rate.setValue(rate)

    def _update_completer(self) -> None:
        """更新智能匹配补全候选词（牌号+型号，便于手输时匹配）。"""
        words = []
        for c in self._consumables:
            words.append(c.brand)
            words.append(c.model)
        # 用 QStringListModel 更新（QCompleter 需 model 而非 list）
        from PySide6.QtCore import QStringListModel
        self._completer.setModel(QStringListModel(words))

    def _on_consumable_change(self) -> None:
        """下拉选中标准库焊材：联动价格 + 效率。"""
        c = self.consumable.currentData()
        if c is None:
            return
        # 价格联动（库中有价则带入，无价则保留当前）
        if c.price and c.price > 0:
            self.mat_price.setValue(c.price)
        # 效率按焊材类型联动
        try:
            self.efficiency.setValue(c.type.deposition_efficiency)
        except Exception:
            pass

    def _on_consumable_text(self, text: str) -> None:
        """手输焊材文本时：尝试智能匹配库中焊材，匹配到则联动价格。"""
        text = text.strip()
        if not text:
            return
        # 在库中按牌号/型号模糊匹配
        for c in self._consumables:
            if text in (c.brand, c.model) or text in c.brand or text in c.model:
                if c.price and c.price > 0:
                    self.mat_price.setValue(c.price)
                try:
                    self.efficiency.setValue(c.type.deposition_efficiency)
                except Exception:
                    pass
                return

    def _on_draw_groove(self) -> None:
        """打开坡口绘制对话框，选定后自动填入截面积。"""
        from .groove_designer import GrooveDesignerDialog
        dlg = GrooveDesignerDialog(parent=self)
        if dlg.exec() == GrooveDesignerDialog.DialogCode.Accepted:
            self.groove_area.setValue(dlg.result_area)
            self._groove = dlg.result_groove  # 保存坡口对象供显示

    def _on_calc(self) -> None:
        geo = WeldGeometry(
            weld_length=self.weld_length.value(),
            groove_area=self.groove_area.value(),
        )
        p = PassCostInput(
            consumable_density=_STEEL_DENSITY,
            deposition_efficiency=self.efficiency.value(),
            deposition_rate=self.deposition_rate.value(),
            current_avg=self.current.value(),
            voltage_avg=self.voltage.value(),
            travel_speed=self.travel_speed.value(),
            gas_flow=self.gas_flow.value(),
        )
        factors = CostFactors(
            consumable_price=self.mat_price.value(),
            gas_price=self.gas_price.value(),
            labor_rate=self.labor_rate.value(),
        )
        bd = self._engine.estimate_pass(geo, p, factors)

        def pct(x):
            return f"{x / bd.total * 100:.1f}%" if bd.total > 0 else "—"

        cons_name = self.consumable.currentText() or "自定义"
        proc_raw = self.process.currentData()
        proc_code = proc_raw.value if hasattr(proc_raw, "value") else str(proc_raw)
        lines = [
            f"<h3>成本计算结果</h3>",
            f"<p>焊缝：{geo.weld_length:g}mm × {geo.groove_area:g}mm²"
            f"（{proc_code}）</p>",
            f"<p>焊材：{cons_name} @ ¥{self.mat_price.value():g}/kg</p>",
            "<table border='1' cellspacing='0' cellpadding='4'"
            " style='border-collapse:collapse;font-size:13px'>",
            "<tr style='background:#f0f0f0'><th>项目</th><th>消耗量</th>"
            "<th>成本(元)</th><th>占比</th></tr>",
            f"<tr><td>焊材</td><td>{bd.consumable_mass:.3f} kg</td>"
            f"<td>{bd.consumable_cost:.2f}</td><td>{pct(bd.consumable_cost)}</td></tr>",
            f"<tr><td>气体</td><td>{bd.gas_volume:.0f} L</td>"
            f"<td>{bd.gas_cost:.2f}</td><td>{pct(bd.gas_cost)}</td></tr>",
            f"<tr><td>人工</td><td>{bd.total_time:.2f} h</td>"
            f"<td>{bd.labor_cost:.2f}</td><td>{pct(bd.labor_cost)}</td></tr>",
            f"<tr style='background:#e3f2fd'><td><b>合计</b></td>"
            f"<td>燃弧{bd.arc_time:.2f}h</td>"
            f"<td><b>{bd.total:.2f}</b></td><td>100%</td></tr>",
            "</table>",
        ]
        if bd.heat_input > 0:
            lines.append(
                f"<p style='margin-top:8px'>热输入(线能量)：<b>{bd.heat_input:.2f} kJ/mm</b></p>"
            )
        lines.append(
            "<p style='font-size:11px;color:#666'>"
            f"说明：钢密度 {_STEEL_DENSITY:g} kg/mm³，总工时按电弧系数"
            f"{factors.arc_time_factor:.0%}估算（含换条/清渣等非燃弧时间）。</p>"
        )
        self.result.setHtml("\n".join(lines))
