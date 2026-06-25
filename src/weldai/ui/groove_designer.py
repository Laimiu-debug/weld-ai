"""坡口绘制设计对话框。

左侧调参（坡口形式/板厚/钝边/间隙/角度/衬垫），右侧 matplotlib 实时预览。
点「用此坡口」把参数（含自动计算的截面积）传回调用方，供成本计算使用。

支持 V/Y/U/X/I 五种坡口形式。
"""
from __future__ import annotations

import matplotlib
matplotlib.use("QtAgg")  # 嵌入 Qt 需要 Qt 后端
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
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
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..domain.joint import GrooveDesign
from ..services.groove_renderer import groove_cross_area

_GROOVE_TYPES = [
    ("V", "V形坡口（单面斜边坡口）"),
    ("Y", "Y形坡口（带直边钝边的V）"),
    ("U", "U形坡口（圆弧根部）"),
    ("X", "X形坡口（双面对称）"),
    ("I", "I形坡口（直边/间隙）"),
]


class GrooveDesignerDialog(QDialog):
    """坡口绘制对话框：实时预览 + 截面积计算。

    调用方读取 ``result_groove``、``result_thickness``、``result_area`` 获取用户选定参数。
    """

    def __init__(self, parent=None, groove: GrooveDesign | None = None,
                 thickness: float = 16.0):
        super().__init__(parent)
        self.setWindowTitle("📐 坡口绘制设计")
        self.resize(760, 520)
        self.result_groove: GrooveDesign | None = None
        self.result_thickness: float = thickness
        self.result_area: float = 0.0

        self._build_ui(groove or GrooveDesign(type="V", angle=60, root_face=2, root_gap=2),
                       thickness)
        self._refresh_preview()

    def _build_ui(self, groove: GrooveDesign, thickness: float) -> None:
        root = QHBoxLayout(self)

        # ---- 左：参数区 ----
        left = QVBoxLayout()
        param_gb = QGroupBox("坡口参数")
        form = QFormLayout(param_gb)

        self.type_combo = QComboBox()
        for code, desc in _GROOVE_TYPES:
            self.type_combo.addItem(f"{code} — {desc}", code)
        self.type_combo.setCurrentIndex(
            next((i for i, (c, _) in enumerate(_GROOVE_TYPES) if c == groove.type), 0)
        )
        self.type_combo.currentIndexChanged.connect(self._on_param_changed)
        form.addRow("坡口形式：", self.type_combo)

        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(2, 200); self.thickness.setSingleStep(1)
        self.thickness.setDecimals(1); self.thickness.setValue(thickness)
        self.thickness.setSuffix(" mm")
        self.thickness.valueChanged.connect(self._on_param_changed)
        form.addRow("板厚 t：", self.thickness)

        self.angle = QDoubleSpinBox()
        self.angle.setRange(10, 90); self.angle.setSingleStep(5)
        self.angle.setDecimals(0); self.angle.setValue(groove.angle or 60)
        self.angle.setSuffix(" °")
        self.angle.valueChanged.connect(self._on_param_changed)
        form.addRow("坡口角度：", self.angle)

        self.root_face = QDoubleSpinBox()
        self.root_face.setRange(0, 30); self.root_face.setSingleStep(0.5)
        self.root_face.setDecimals(1); self.root_face.setValue(groove.root_face or 2)
        self.root_face.setSuffix(" mm")
        self.root_face.valueChanged.connect(self._on_param_changed)
        form.addRow("钝边 p：", self.root_face)

        self.root_gap = QDoubleSpinBox()
        self.root_gap.setRange(0, 10); self.root_gap.setSingleStep(0.5)
        self.root_gap.setDecimals(1); self.root_gap.setValue(groove.root_gap or 2)
        self.root_gap.setSuffix(" mm")
        self.root_gap.valueChanged.connect(self._on_param_changed)
        form.addRow("根部间隙 b：", self.root_gap)

        self.has_backing = QCheckBox("带衬垫（单面焊）")
        self.has_backing.setChecked(groove.has_backing)
        self.has_backing.toggled.connect(self._on_param_changed)
        form.addRow("", self.has_backing)

        # 截面积实时显示
        self.area_label = QLabel()
        self.area_label.setStyleSheet("color:#1565c0; font-weight:bold; font-size:13px;")
        form.addRow("坡口截面积：", self.area_label)

        left.addWidget(param_gb)
        left.addStretch()

        # 提示
        hint = QLabel(
            "<small style='color:#888'>截面积由几何公式解析计算，"
            "用于焊材消耗量估算。<br>选定后点「用此坡口」可带入成本计算。</small>"
        )
        hint.setWordWrap(True)
        left.addWidget(hint)

        # ---- 右：预览区 ----
        self.fig, self.ax = plt.subplots(figsize=(4.5, 4.2))
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumWidth(320)

        root.addLayout(left, stretch=1)
        root.addWidget(self.canvas, stretch=2)

        # ---- 底部按钮 ----
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("用此坡口")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        left.addWidget(btns)

    def _current_groove(self) -> tuple[GrooveDesign, float]:
        g = GrooveDesign(
            type=self.type_combo.currentData(),
            angle=self.angle.value(),
            root_face=self.root_face.value(),
            root_gap=self.root_gap.value(),
            has_backing=self.has_backing.isChecked(),
        )
        return g, self.thickness.value()

    def _on_param_changed(self) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """重绘 matplotlib 预览 + 更新截面积标签。"""
        groove, t = self._current_groove()
        area = groove_cross_area(groove, t)
        self.area_label.setText(f"{area:.1f} mm²")
        # 直接在预览 axes 上绘制坡口（与 render_groove 几何一致，无文件IO）
        self.ax.clear()
        try:
            self._draw_groove_to_ax(self.ax, groove, t)
        except Exception:
            pass
        self.canvas.draw_idle()

    def _draw_groove_to_ax(self, ax, groove: GrooveDesign, thickness: float) -> None:
        """在预览 axes 上直接绘制坡口剖面（复用 renderer 的几何函数）。

        为避免 render_groove 的文件IO 与 Agg/QtAgg 后端冲突，这里复用底层
        _draw_* 函数直接画到传入的 axes。
        """
        import math as _m
        from matplotlib.patches import Polygon, Rectangle

        t = max(thickness, 2.0)
        angle = groove.angle if groove.angle and groove.angle > 0 else 60.0
        root_face = groove.root_face if groove.root_face and groove.root_face >= 0 else 2.0
        root_gap = groove.root_gap if groove.root_gap and groove.root_gap >= 0 else 2.0
        gtype = (groove.type or "V").upper().strip()

        ax.set_aspect("equal")
        ax.axis("off")
        plate_half_w = max(t * 1.5, 15.0)
        half_gap = root_gap / 2
        half_angle = _m.radians(angle / 2)

        def add_left(pts):
            ax.add_patch(Polygon(pts, closed=True, facecolor="#d0d0d0",
                                 edgecolor="k", linewidth=1.0))

        def mirror(pts):
            return [(2 * half_gap - x, y) for (x, y) in pts]

        if gtype == "I":
            ax.add_patch(Rectangle((-plate_half_w - half_gap, 0), plate_half_w, t,
                                   facecolor="#d0d0d0", edgecolor="k", linewidth=1.0))
            ax.add_patch(Rectangle((half_gap, 0), plate_half_w, t,
                                   facecolor="#d0d0d0", edgecolor="k", linewidth=1.0))
        elif gtype in ("V", "Y"):
            bevel = max(t - root_face, 0)
            off = bevel * _m.tan(half_angle)
            lp = [(-plate_half_w, 0), (-plate_half_w, t),
                  (-half_gap - off, t), (-half_gap, root_face), (-half_gap, 0)]
            add_left(lp); add_left(mirror(lp))
        elif gtype == "X":
            half_bevel = max(t / 2 - root_face / 2, 0)
            off = half_bevel * _m.tan(half_angle)
            lp = [(-plate_half_w, 0), (-plate_half_w, t),
                  (-half_gap - off, t), (-half_gap, t / 2 + root_face / 2),
                  (-half_gap, t / 2 - root_face / 2), (-half_gap - off, 0)]
            add_left(lp); add_left(mirror(lp))
            ax.axhline(t / 2, color="#aaa", linestyle=":", linewidth=0.5)
        elif gtype == "U":
            radius = max((t - root_face) * 0.3, 3.0)
            straight_h = t - root_face - radius
            cx, cy = -(half_gap + radius), root_face + radius
            arc = [(cx + radius * _m.cos(_m.pi / 2 - _m.pi / 2 * (i / 12)),
                    cy + radius * _m.sin(_m.pi / 2 - _m.pi / 2 * (i / 12)))
                   for i in range(13)]
            lp = [(-half_gap, 0), (-half_gap, root_face)] + arc + \
                 [(-half_gap - radius, root_face + radius + straight_h),
                  (-plate_half_w, t), (-plate_half_w, 0)]
            add_left(lp); add_left(mirror(lp))
        else:
            bevel = max(t - root_face, 0)
            off = bevel * _m.tan(half_angle)
            lp = [(-plate_half_w, 0), (-plate_half_w, t),
                  (-half_gap - off, t), (-half_gap, root_face), (-half_gap, 0)]
            add_left(lp); add_left(mirror(lp))

        if groove.has_backing:
            bw = root_gap + 8
            ax.add_patch(Rectangle((-bw / 2, -3), bw, 2.5, facecolor="#888",
                                   edgecolor="k", linewidth=0.8, hatch="//"))

        ax.set_xlim(-plate_half_w - 4, plate_half_w + 4)
        ax.set_ylim(-6 if groove.has_backing else -2, t + 2)
        ax.set_title(f"{gtype}形  t={t:g}  {angle:g}°  钝边{root_face:g}  间隙{root_gap:g}",
                     fontsize=9)

    def _on_accept(self) -> None:
        groove, t = self._current_groove()
        self.result_groove = groove
        self.result_thickness = t
        self.result_area = groove_cross_area(groove, t)
        self.accept()
