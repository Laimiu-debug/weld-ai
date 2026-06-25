"""焊接成本计算视图。

输入：焊缝几何（长度/截面积）+ 焊接参数 + 价格
输出：焊材/气体/人工成本分解 + 热输入

焊材从标准库（NB/T 47014 consumables.yaml）加载，选中后自动填充
密度与熔敷效率。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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


# 焊接方法 → 典型熔敷效率 / 典型熔敷速度(kg/h) / 是否耗气
_PROCESS_PRESET = {
    WeldingProcess.SMAW: (0.55, 1.6, False),
    WeldingProcess.GTAW: (0.98, 0.8, True),
    WeldingProcess.GMAW: (0.95, 2.5, True),
    WeldingProcess.FCAW: (0.90, 2.2, True),
    WeldingProcess.SAW: (0.99, 6.0, False),
}
# 钢熔敷金属密度 kg/mm³
_STEEL_DENSITY = 7.85e-6


class CostView(QWidget):
    """成本计算视图（嵌入主窗口标签页）。"""

    def __init__(self):
        super().__init__()
        self._engine = CostEngine()
        self._consumables: list = []  # 标准库焊材列表
        self._build_ui()
        self._load_consumables()

    def _load_consumables(self) -> None:
        """从标准库加载焊材到下拉。"""
        self.consumable_combo.blockSignals(True)
        self.consumable_combo.clear()
        self.consumable_combo.addItem("（自定义）", None)
        try:
            from ..standards import get_default_standard
            std = get_default_standard()
            self._consumables = std.all_consumables()
            for c in self._consumables:
                label = f"{c.brand} [{c.model}]" + (f" φ{c.diameter:g}" if c.diameter else "")
                self.consumable_combo.addItem(label, c)
        except Exception:
            self._consumables = []
        self.consumable_combo.blockSignals(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(self._build_input_group())
        root.addWidget(self._build_result(), stretch=1)

    def _build_input_group(self) -> QGroupBox:
        gb = QGroupBox("💰 焊接成本计算")
        lay = QVBoxLayout(gb)

        # 焊缝几何
        geo_row = QHBoxLayout()
        geo_row.addWidget(QLabel("焊缝长度(mm)："))
        self.weld_length = QDoubleSpinBox()
        self.weld_length.setRange(1, 100000); self.weld_length.setValue(1000)
        geo_row.addWidget(self.weld_length)
        geo_row.addWidget(QLabel("坡口截面积(mm²)："))
        self.groove_area = QDoubleSpinBox()
        self.groove_area.setRange(1, 10000); self.groove_area.setValue(50)
        geo_row.addWidget(self.groove_area)
        geo_row.addStretch()
        lay.addLayout(geo_row)

        # 焊材选择（从标准库）+ 焊接方法
        mat_row = QHBoxLayout()
        mat_row.addWidget(QLabel("焊材："))
        self.consumable_combo = QComboBox()
        self.consumable_combo.setMinimumWidth(220)
        self.consumable_combo.currentIndexChanged.connect(self._on_consumable_change)
        mat_row.addWidget(self.consumable_combo)
        mat_row.addWidget(QLabel("焊接方法："))
        self.process = QComboBox()
        for p in (WeldingProcess.SMAW, WeldingProcess.GTAW, WeldingProcess.GMAW,
                  WeldingProcess.FCAW, WeldingProcess.SAW):
            self.process.addItem(f"{p.value} {p.cn}", p)
        self.process.currentIndexChanged.connect(self._on_process_change)
        mat_row.addWidget(self.process)
        mat_row.addStretch()
        lay.addLayout(mat_row)

        # 熔敷参数（被焊材/方法联动填充）
        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("熔敷效率："))
        self.efficiency = QDoubleSpinBox()
        self.efficiency.setRange(0.01, 1.0); self.efficiency.setDecimals(2)
        self.efficiency.setValue(0.55)
        param_row.addWidget(self.efficiency)
        param_row.addWidget(QLabel("熔敷速度(kg/h)："))
        self.deposition_rate = QDoubleSpinBox()
        self.deposition_rate.setRange(0, 50); self.deposition_rate.setValue(1.6)
        self.deposition_rate.setDecimals(2)
        param_row.addWidget(self.deposition_rate)
        param_row.addStretch()
        lay.addLayout(param_row)

        param_row2 = QHBoxLayout()
        param_row2.addWidget(QLabel("平均电流(A)："))
        self.current = QDoubleSpinBox()
        self.current.setRange(0, 2000); self.current.setValue(120)
        param_row2.addWidget(self.current)
        param_row2.addWidget(QLabel("平均电压(V)："))
        self.voltage = QDoubleSpinBox()
        self.voltage.setRange(0, 100); self.voltage.setValue(24)
        param_row2.addWidget(self.voltage)
        param_row2.addWidget(QLabel("焊接速度(cm/min)："))
        self.travel_speed = QDoubleSpinBox()
        self.travel_speed.setRange(0, 500); self.travel_speed.setValue(30)
        param_row2.addWidget(self.travel_speed)
        param_row2.addWidget(QLabel("气体流量(L/min)："))
        self.gas_flow = QDoubleSpinBox()
        self.gas_flow.setRange(0, 100); self.gas_flow.setValue(10)
        param_row2.addWidget(self.gas_flow)
        param_row2.addStretch()
        lay.addLayout(param_row2)

        # 价格参数
        price_row = QHBoxLayout()
        price_row.addWidget(QLabel("焊材(元/kg)："))
        self.mat_price = QDoubleSpinBox()
        self.mat_price.setRange(0, 10000); self.mat_price.setValue(30)
        price_row.addWidget(self.mat_price)
        price_row.addWidget(QLabel("气体(元/瓶)："))
        self.gas_price = QDoubleSpinBox()
        self.gas_price.setRange(0, 10000); self.gas_price.setValue(50)
        price_row.addWidget(self.gas_price)
        price_row.addWidget(QLabel("人工(元/h)："))
        self.labor_rate = QDoubleSpinBox()
        self.labor_rate.setRange(0, 10000); self.labor_rate.setValue(80)
        price_row.addWidget(self.labor_rate)
        price_row.addStretch()
        lay.addLayout(price_row)

        self.btn_calc = QPushButton("📊 计算")
        self.btn_calc.clicked.connect(self._on_calc)
        lay.addWidget(self.btn_calc)
        # 触发一次方法联动以设置初始效率/速度
        self._on_process_change()
        return gb

    def _build_result(self) -> QWidget:
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        return self.result

    def _on_consumable_change(self) -> None:
        """选中标准库焊材时，按其类型联动熔敷效率。"""
        c = self.consumable_combo.currentData()
        if c is None:
            return
        # 按焊材类型设效率（焊条0.55/焊丝0.95/埋弧组合0.99）
        try:
            self.efficiency.setValue(c.type.deposition_efficiency)
        except Exception:
            pass

    def _on_process_change(self) -> None:
        """焊接方法联动典型熔敷效率与熔敷速度。"""
        p = self.process.currentData()
        if p in _PROCESS_PRESET:
            eff, rate, _gas = _PROCESS_PRESET[p]
            self.efficiency.setValue(eff)
            self.deposition_rate.setValue(rate)

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

        # 成本占比
        def pct(x):
            return f"{x / bd.total * 100:.1f}%" if bd.total > 0 else "—"

        cons_name = ""
        c = self.consumable_combo.currentData()
        if c is not None:
            cons_name = f"（{c.brand}/{c.model}）"

        lines = [
            f"<h3>成本计算结果</h3>",
            f"<p>焊缝：{geo.weld_length:g}mm × {geo.groove_area:g}mm²{cons_name}</p>",
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
