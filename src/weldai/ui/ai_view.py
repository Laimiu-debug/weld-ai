"""AI 辅助视图：PQR→WPS 自动派生 + 焊接参数智能推荐。

标签页内容：
  上半部：PQR→WPS 派生（选 PQR + 目标位置/厚度比例 → 生成合法 WPS + 派生报告）
  下半部：参数推荐（选母材 + 方法 + 厚度 → 推荐焊材与参数）
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..domain.enums import Position, ProcedureType, WeldingProcess
from ..engine import ParameterAdvisor, WPSDeriver
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
]


class AIView(QWidget):
    """AI 辅助视图（嵌入主窗口标签页）。"""

    def __init__(self):
        super().__init__()
        self._standard = get_default_standard()
        self._deriver = WPSDeriver(self._standard)
        self._advisor = ParameterAdvisor(self._standard)
        self._build_ui()

    def update_standard(self, standard):
        self._standard = standard
        self._deriver = WPSDeriver(standard)
        self._advisor = ParameterAdvisor(standard)

    def refresh(self):
        """刷新 PQR 下拉（标准切换或新增 PQR 后调用）。"""
        self._refresh_pqr_combo()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        sp = QSplitter(Qt.Orientation.Vertical)
        sp.addWidget(self._build_derive_group())
        sp.addWidget(self._build_advice_group())
        sp.addWidget(self._build_chat_group())
        sp.setSizes([280, 260, 300])
        root.addWidget(sp, stretch=1)

    # ------------------------------------------------------------------
    # PQR → WPS 派生
    # ------------------------------------------------------------------

    def _build_derive_group(self) -> QGroupBox:
        gb = QGroupBox("🤖 PQR → WPS 自动派生（保证派生的 WPS 通过评定校验）")
        lay = QVBoxLayout(gb)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("依据 PQR："))
        self.derive_pqr_combo = QComboBox()
        row1.addWidget(self.derive_pqr_combo, stretch=1)
        row1.addWidget(QLabel("目标位置："))
        self.derive_pos = QComboBox()
        for p in _POSITION_ITEMS:
            self.derive_pos.addItem(p.value, p)
        row1.addWidget(self.derive_pos)
        row1.addWidget(QLabel("厚度比例："))
        self.derive_ratio = QDoubleSpinBox()
        self.derive_ratio.setRange(0.1, 1.0); self.derive_ratio.setSingleStep(0.1)
        self.derive_ratio.setValue(0.5)
        row1.addWidget(self.derive_ratio)
        self.btn_derive = QPushButton("⚡ 派生 WPS")
        self.btn_derive.clicked.connect(self._on_derive)
        row1.addWidget(self.btn_derive)
        lay.addLayout(row1)

        self.derive_result = QTextEdit()
        self.derive_result.setReadOnly(True)
        self.derive_result.setPlaceholderText(
            "选择一个 PQR，设定目标焊接位置和厚度比例，"
            "点击「派生 WPS」将自动生成一个保证通过评定校验的 WPS，"
            "并给出各项参数的依据说明。"
        )
        lay.addWidget(self.derive_result)
        return gb

    def _refresh_pqr_combo(self) -> None:
        repo = ProcedureRepository(get_session(), self._standard)
        pqrs = repo.list_all(ProcedureType.PQR)
        self.derive_pqr_combo.clear()
        for p in pqrs:
            self.derive_pqr_combo.addItem(
                f"{p.doc_no} ({p.process.value})", p.doc_no
            )

    def _on_derive(self) -> None:
        doc_no = self.derive_pqr_combo.currentData()
        if not doc_no:
            QMessageBox.information(self, "提示", "请先选择一个 PQR（在工艺评定页新建）")
            return
        repo = ProcedureRepository(get_session(), self._standard)
        pqr = repo.get(doc_no)
        if not pqr:
            return

        target_pos = [self.derive_pos.currentData()]
        report = self._deriver.derive(
            pqr, wps_no=f"WPS-派生自{pqr.doc_no}",
            target_positions=target_pos,
            target_thickness_ratio=self.derive_ratio.value(),
        )

        # 把派生的 WPS 存入数据库
        save_error = ""
        try:
            repo.save(report.wps)
        except Exception as e:
            save_error = f"WPS 保存失败: {e}（派生结果仍可查看，可手动新建）"

        # 渲染报告
        lines = [
            f"<h3>✦ 已派生 WPS：<b>{report.wps.doc_no}</b></h3>",
            f"<p>依据 PQR：{pqr.doc_no} | 方法：{pqr.process.value} | "
            f"标准：{self._standard.standard_code}</p>",
            "<p><b>派生依据（可追溯）：</b></p>",
            "<div style='font-size:12px'>",
        ]
        for n in report.notes:
            lines.append(f"• {n}<br>")
        lines.append("</div>")
        if report.warnings:
            lines.append("<p style='color:#ef6c00'><b>⚠ 注意：</b></p>")
            for w in report.warnings:
                lines.append(f"<div style='color:#ef6c00;margin-left:12px'>• {w}</div>")
        if save_error:
            lines.append(
                f"<p style='color:#c62828;font-size:11px'>⚠ {save_error}</p>"
            )
        else:
            lines.append(
                "<p style='color:#2e7d32;font-size:11px'>"
                "派生的 WPS 已保存至工艺文件库，可在「工艺评定」标签页查看/编辑。</p>"
            )
        self.derive_result.setHtml("\n".join(lines))

    # ------------------------------------------------------------------
    # 参数推荐
    # ------------------------------------------------------------------

    def _build_advice_group(self) -> QGroupBox:
        gb = QGroupBox("💡 焊接参数智能推荐（焊材匹配 + 经验参数）")
        lay = QVBoxLayout(gb)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("母材牌号："))
        self.adv_material = QComboBox()
        self.adv_material.setEditable(True)
        for m in sorted(self._standard.all_base_metals(), key=lambda x: str(x.grade)):
            self.adv_material.addItem(str(m.grade))
        row1.addWidget(self.adv_material, stretch=1)
        row1.addWidget(QLabel("焊接方法："))
        self.adv_process = QComboBox()
        for p, lab in _PROCESS_ITEMS:
            self.adv_process.addItem(lab, p)
        row1.addWidget(self.adv_process)
        row1.addWidget(QLabel("板厚(mm)："))
        self.adv_thickness = QDoubleSpinBox()
        self.adv_thickness.setRange(0.5, 200); self.adv_thickness.setValue(12.0)
        self.adv_thickness.setDecimals(1)
        row1.addWidget(self.adv_thickness)
        self.btn_advise = QPushButton("🔍 推荐")
        self.btn_advise.clicked.connect(self._on_advice)
        row1.addWidget(self.btn_advise)
        lay.addLayout(row1)

        self.adv_result = QTextEdit()
        self.adv_result.setReadOnly(True)
        self.adv_result.setPlaceholderText(
            "选择母材和焊接方法，点击「推荐」获取匹配焊材与经验焊接参数范围。"
            "参数为初拟参考值，须经工艺评定(PQR)验证后方可用于生产。"
        )
        lay.addWidget(self.adv_result)
        return gb

    def _on_advice(self) -> None:
        grade = self.adv_material.currentText()
        process = self.adv_process.currentData()
        thickness = self.adv_thickness.value()

        rec = self._advisor.recommend(grade, process, thickness)

        lines = [
            f"<h3>推荐结果：{grade} / {process.value} / {thickness:g}mm</h3>",
        ]
        if rec.consumables:
            lines.append("<p><b>匹配焊材：</b></p>")
            lines.append("<table border='1' cellspacing='0' cellpadding='3'"
                         " style='border-collapse:collapse;font-size:12px;width:100%'>")
            lines.append("<tr style='background:#f0f0f0'><th>牌号</th><th>型号</th>"
                         "<th>分类栏位</th><th>标准</th></tr>")
            for c in rec.consumables:
                lines.append(
                    f"<tr><td>{c.brand}</td><td>{c.model}</td>"
                    f"<td>{c.classification_slot}</td><td>{c.standard}</td></tr>"
                )
            lines.append("</table>")

        if rec.recommended_diameter > 0:
            lines.append(
                f"<p><b>推荐焊接参数（φ{rec.recommended_diameter:g}mm焊材）：</b></p>"
                f"<div style='font-size:12px'>"
                f"电流：{rec.current_range[0]:g} ~ {rec.current_range[1]:g} A<br>"
                f"电压：{rec.voltage_range[0]:g} ~ {rec.voltage_range[1]:g} V<br>"
                f"熔敷速度：{rec.deposition_rate:g} kg/h<br>"
                f"熔敷效率：{rec.efficiency:.0%}<br>"
                + (f"保护气体：{rec.gas_type} ({rec.gas_flow_range[0]:g}"
                   f"~{rec.gas_flow_range[1]:g} L/min)<br>" if rec.gas_type else "")
                + "</div>"
            )

        for n in rec.notes:
            lines.append(f"<div style='font-size:11px;color:#666'>• {n}</div>")
        self.adv_result.setHtml("\n".join(lines))

    # ------------------------------------------------------------------
    # 焊接专家问答（LLM）
    # ------------------------------------------------------------------

    def _build_chat_group(self) -> "QGroupBox":
        from ..services import QUESTION_TYPES, LLMService
        from ..services.config_service import load_config
        gb = QGroupBox("🤖 焊接专家问答（大语言模型 · 需在「设置」配置API Key）")
        lay = QVBoxLayout(gb)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("问题类型："))
        self.chat_type = QComboBox()
        for key, label in QUESTION_TYPES:
            self.chat_type.addItem(label, key)
        row1.addWidget(self.chat_type)
        row1.addStretch()
        self._llm = LLMService(load_config().llm)
        lay.addLayout(row1)

        self.chat_input = QTextEdit()
        self.chat_input.setMaximumHeight(70)
        self.chat_input.setPlaceholderText(
            "输入焊接相关问题，如：Q345R和06Cr19Ni10异种钢焊接该用什么焊材和工艺？"
        )
        lay.addWidget(self.chat_input)

        row2 = QHBoxLayout()
        self.btn_ask = QPushButton("🚀 提问")
        self.btn_ask.clicked.connect(self._on_ask)
        row2.addStretch()
        row2.addWidget(self.btn_ask)
        lay.addLayout(row2)

        self.chat_result = QTextEdit()
        self.chat_result.setReadOnly(True)
        self.chat_result.setPlaceholderText(
            "专家回复将显示在此。未配置 API Key 时请先点击菜单「设置」。"
        )
        lay.addWidget(self.chat_result)
        return gb

    def refresh_llm_config(self):
        """重新加载 LLM 配置（设置保存后调用）。"""
        from ..services import LLMService
        from ..services.config_service import load_config
        self._llm = LLMService(load_config().llm)

    def _on_ask(self):
        from PySide6.QtWidgets import QApplication
        question = self.chat_input.toPlainText().strip()
        if not question:
            return
        qtype = self.chat_type.currentData()
        self.btn_ask.setEnabled(False)
        self.chat_result.setHtml("<p style='color:#888'>正在思考中...</p>")
        QApplication.processEvents()

        resp = self._llm.ask(question, question_type=qtype)
        self.btn_ask.setEnabled(True)

        if not resp.success:
            self.chat_result.setHtml(
                f"<p style='color:#c62828'>❌ {resp.error}</p>"
                "<p style='font-size:11px;color:#666'>请检查菜单「设置」中的 API 配置。</p>"
            )
            return

        # 渲染回复 + 免责声明
        import html
        content = html.escape(resp.answer).replace("\n", "<br>")
        self.chat_result.setHtml(
            f"<div style='font-size:13px'>{content}</div>"
            f"<hr style='border:0;border-top:1px dashed #ccc;margin-top:8px'>"
            f"<p style='color:#ef6c00;font-size:11px'>{resp.disclaimer}</p>"
        )
