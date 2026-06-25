"""焊缝识别追溯视图（GB/T 150 / TSG 21）。

产品容器 → 焊缝列表（图号/编号/WPS/焊工），支持追溯查询。
用于压力容器产品质量证明文件和监检追溯。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from datetime import date

from ..domain.enums import JointType, Position
from ..domain.weld_seam import Product, WeldSeam
from ..persistence import ProductRepository, ProcedureRepository, get_session


_JOINT_TYPES = [
    (JointType.BUTT, "对接(A/B类)"),
    (JointType.FILLET, "角焊(C/D类)"),
    (JointType.NOZZLE, "管板/接管"),
]
_POSITIONS = [
    Position.PLATE_1G, Position.PLATE_2G, Position.PLATE_3G, Position.PLATE_4G,
    Position.PIPE_1G, Position.PIPE_2G, Position.PIPE_5G, Position.PIPE_6G,
]


class SeamDialog(QDialog):
    """焊缝编辑对话框。"""

    def __init__(self, seam: WeldSeam | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑焊缝" if seam else "新增焊缝")
        self.resize(480, 400)
        self._build_ui()
        if seam:
            self._load(seam)

    def _build_ui(self):
        form = QFormLayout(self)
        self.seam_no = QLineEdit()
        self.seam_no.setPlaceholderText("如 A1/B2/C1（A纵缝/B环缝）")
        self.wps_no = QComboBox()
        self.wps_no.setEditable(True)
        self._refresh_wps()
        self.welder_stamp = QLineEdit()
        self.welder_stamp.setPlaceholderText("焊工钢印号")
        self.joint_type = QComboBox()
        for jt, lab in _JOINT_TYPES:
            self.joint_type.addItem(lab, jt)
        self.position = QComboBox()
        for p in _POSITIONS:
            self.position.addItem(p.value, p)
        self.length = QDoubleSpinBox()
        self.length.setRange(0, 100000); self.length.setValue(1000)
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0, 500); self.thickness.setValue(16); self.thickness.setDecimals(1)
        self.weld_date = QDateEdit()
        self.weld_date.setCalendarPopup(True)
        self.weld_date.setDate(date.today())
        self.weld_date.setDisplayFormat("yyyy-MM-dd")
        self.ndt_result = QLineEdit()
        self.ndt_result.setPlaceholderText("如 RT-II 合格 / UT-I 合格")

        form.addRow("焊缝编号 *：", self.seam_no)
        form.addRow("使用WPS：", self.wps_no)
        # 推荐可用 PQR/WPS 按钮
        self.btn_recommend = QPushButton("🎯 推荐可用PQR/WPS（按厚度/位置匹配）")
        self.btn_recommend.clicked.connect(self._on_recommend)
        form.addRow(self.btn_recommend)
        form.addRow("焊工钢印：", self.welder_stamp)
        form.addRow("焊缝形式：", self.joint_type)
        form.addRow("焊接位置：", self.position)
        form.addRow("焊缝长度(mm)：", self.length)
        form.addRow("母材厚度(mm)：", self.thickness)
        form.addRow("施焊日期：", self.weld_date)
        form.addRow("无损检测：", self.ndt_result)
        # 母材牌号（用于匹配）
        self.material_grade = QLineEdit()
        self.material_grade.setPlaceholderText("母材牌号(用于匹配，如Q345R)")
        form.addRow("母材牌号：", self.material_grade)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_check)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _refresh_wps(self):
        try:
            from ..standards import get_default_standard
            repo = ProcedureRepository(get_session(), get_default_standard())
            from ..domain.enums import ProcedureType
            for p in repo.list_all(ProcedureType.WPS):
                self.wps_no.addItem(p.doc_no)
        except Exception:
            pass

    def _load(self, s: WeldSeam):
        self.seam_no.setText(s.seam_no)
        self.wps_no.setEditText(s.wps_no)
        self.welder_stamp.setText(s.welder_stamp)
        i = self.joint_type.findData(s.joint_type)
        if i >= 0:
            self.joint_type.setCurrentIndex(i)
        i = self.position.findData(s.position)
        if i >= 0:
            self.position.setCurrentIndex(i)
        self.length.setValue(s.length)
        self.thickness.setValue(s.thickness)
        self.ndt_result.setText(s.ndt_result)

    def _accept_check(self):
        if not self.seam_no.text().strip():
            QMessageBox.warning(self, "提示", "请填写焊缝编号")
            return
        self.accept()

    def _on_recommend(self):
        """根据当前厚度/位置/母材，推荐可用的 PQR/WPS。"""
        from ..domain.enums import WeldingProcess
        from ..engine import WeldRequirement
        from ..services import BatchService
        from ..standards import get_default_standard
        from ..persistence import ProcedureRepository, get_session

        thickness = self.thickness.value()
        position = self.position.currentData()
        grade = self.material_grade.text().strip()
        if thickness <= 0:
            QMessageBox.warning(self, "提示", "请先填写母材厚度")
            return

        std = get_default_standard()
        repo = ProcedureRepository(get_session(), std)
        batch = BatchService(repo, std)
        # 焊缝需求：方法用默认 SMAW（因 PQR 库可能不全，匹配时方法维度会过滤）
        # 这里遍历常用方法找匹配
        req = WeldRequirement(
            material_grade=grade, thickness=thickness,
            position=position,
        )
        usable = batch.find_usable_for_seam(req)

        if not usable:
            QMessageBox.information(
                self, "无匹配",
                f"未找到能覆盖此焊缝(厚度{thickness:g}mm/{position.value})的 PQR。\n"
                "可能需要新建工艺评定。"
            )
            return

        # 弹出选择对话框
        from PySide6.QtWidgets import QDialog as _QD, QDialogButtonBox as _QBB
        dlg = _QD(self)
        dlg.setWindowTitle("选择可用 WPS")
        dlg.resize(520, 360)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel(
            f"找到 {len(usable)} 个 PQR 可覆盖此焊缝，"
            f"请选择要使用的 WPS："
        ))
        combo = QComboBox()
        for pqr, wpss in usable:
            if wpss:
                for w in wpss:
                    combo.addItem(
                        f"{w.doc_no} (依据 {pqr.doc_no}, 母材"
                        f"{','.join(b.metal.grade for b in pqr.base_metals)})",
                        w.doc_no,
                    )
            else:
                combo.addItem(
                    f"PQR {pqr.doc_no} 可覆盖（暂无关联WPS）",
                    pqr.doc_no,
                )
        dl.addWidget(combo)
        bb = _QBB(_QBB.StandardButton.Ok | _QBB.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)
        if dlg.exec() == _QD.DialogCode.Accepted:
            selected = combo.currentData()
            if selected:
                self.wps_no.setEditText(selected)

    def get_seam(self) -> WeldSeam:
        # 注意：QComboBox.currentData() 对 (str, Enum) 混合枚举会返回纯 str，
        # 必须显式转回枚举，否则下游 s.joint_type.value 会失败。
        jt = self.joint_type.currentData()
        pos = self.position.currentData()
        return WeldSeam(
            seam_no=self.seam_no.text().strip(),
            wps_no=self.wps_no.currentText().strip(),
            welder_stamp=self.welder_stamp.text().strip(),
            joint_type=JointType(jt) if not isinstance(jt, JointType) else jt,
            position=Position(pos) if not isinstance(pos, Position) else pos,
            length=self.length.value(),
            thickness=self.thickness.value(),
            weld_date=date(self.weld_date.date().year(),
                           self.weld_date.date().month(),
                           self.weld_date.date().day()),
            ndt_result=self.ndt_result.text().strip(),
        )


class TraceView(QWidget):
    """焊缝追溯视图（嵌入主窗口标签页）。"""

    def __init__(self):
        super().__init__()
        self._repo = ProductRepository(get_session())
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        self.btn_new_product = QPushButton("📦 新建产品")
        self.btn_new_product.clicked.connect(self._on_new_product)
        self.btn_add_seam = QPushButton("➕ 添加焊缝")
        self.btn_add_seam.clicked.connect(self._on_add_seam)
        self.btn_del_product = QPushButton("✖ 删除产品")
        self.btn_del_product.clicked.connect(self._on_del_product)
        for b in (self.btn_new_product, self.btn_add_seam, self.btn_del_product):
            toolbar.addWidget(b)
        toolbar.addStretch()
        root.addLayout(toolbar)

        sp = QSplitter(Qt.Orientation.Horizontal)

        # 左：产品列表
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("产品（容器）列表"))
        self.product_table = QTableWidget(0, 4)
        self.product_table.setHorizontalHeaderLabels(
            ["产品编号", "名称", "图号", "焊缝数"]
        )
        self.product_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.product_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.product_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.product_table.itemSelectionChanged.connect(self._on_product_select)
        ll.addWidget(self.product_table)

        # 右：焊缝追溯表
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("焊缝追溯表（图号 → 焊缝 → WPS + 焊工）"))
        self.seam_table = QTableWidget(0, 8)
        self.seam_table.setHorizontalHeaderLabels(
            ["焊缝编号", "形式", "位置", "长度(mm)", "WPS", "焊工钢印", "施焊日期", "覆盖状态"]
        )
        self.seam_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.seam_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        rl.addWidget(self.seam_table)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(120)
        rl.addWidget(self.summary)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setSizes([380, 720])
        root.addWidget(sp, stretch=1)

    def _selected_product(self) -> str | None:
        rows = self.product_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.product_table.item(rows[0].row(), 0).text()

    def _refresh(self):
        products = self._repo.list_all()
        self.product_table.setRowCount(len(products))
        for i, p in enumerate(products):
            self.product_table.setItem(i, 0, QTableWidgetItem(p.product_no))
            self.product_table.setItem(i, 1, QTableWidgetItem(p.name))
            self.product_table.setItem(i, 2, QTableWidgetItem(p.drawing_no))
            self.product_table.setItem(i, 3, QTableWidgetItem(str(len(p.seams))))

    def _on_product_select(self):
        no = self._selected_product()
        if not no:
            self.seam_table.setRowCount(0)
            self.summary.clear()
            return
        product = self._repo.get(no)
        if not product:
            return
        self._render_seams(product)

    def _render_seams(self, product: Product):
        self.seam_table.setRowCount(len(product.seams))
        # 一次性构造 repo/matcher，避免循环内 N+1 重建（M4 性能优化）
        from PySide6.QtGui import QColor
        from ..persistence import ProcedureRepository, get_session
        from ..standards import get_default_standard
        from ..engine import WeldRequirement, PQRMatcher
        std = get_default_standard()
        repo = ProcedureRepository(get_session(), std)
        matcher = PQRMatcher(repo, std)
        # 预加载本产品涉及的 WPS/PQR，避免逐条查库
        wps_cache: dict[str, object] = {}

        def get_status(seam):
            return self._seam_coverage_status(
                seam, repo=repo, matcher=matcher, wps_cache=wps_cache
            )

        covered = 0
        for i, s in enumerate(product.seams):
            self.seam_table.setItem(i, 0, QTableWidgetItem(s.seam_no))
            # 形式/位置用中文显示（枚举 cn 属性），位置用标准代号
            jt = s.joint_type
            jt_text = jt.cn if hasattr(jt, "cn") else str(jt)
            self.seam_table.setItem(i, 1, QTableWidgetItem(jt_text))
            self.seam_table.setItem(i, 2, QTableWidgetItem(s.position.value))
            self.seam_table.setItem(i, 3, QTableWidgetItem(f"{s.length:g}"))
            self.seam_table.setItem(i, 4, QTableWidgetItem(s.wps_no or "—"))
            self.seam_table.setItem(i, 5, QTableWidgetItem(s.welder_stamp or "—"))
            self.seam_table.setItem(i, 6, QTableWidgetItem(
                str(s.weld_date) if s.weld_date else "—"))
            status, color = get_status(s)
            if status.startswith("✓"):
                covered += 1
            status_item = QTableWidgetItem(status)
            status_item.setForeground(QColor(color))
            self.seam_table.setItem(i, 7, status_item)
        # 汇总（覆盖数已在循环中统计，无需重复计算）
        self.summary.setHtml(
            f"<h3>{product.name}（{product.product_no}）</h3>"
            f"<p>图号：{product.drawing_no or '—'} | "
            f"焊缝总数：{len(product.seams)} | "
            f"主焊缝(A/B类)：{product.main_seam_count} | "
            f"涉及WPS：{product.wps_count}个 | "
            f"涉及焊工：{product.welder_count}人</p>"
            f"<p>覆盖状态：<span style='color:#2e7d32'>{covered} 条已覆盖</span> | "
            f"{len(product.seams) - covered} 条待核实/无WPS</p>"
        )

    def _seam_coverage_status(
        self, s: WeldSeam, repo=None, matcher=None, wps_cache: dict | None = None,
    ) -> tuple[str, str]:
        """判断单条焊缝的覆盖状态，返回(显示文字, 颜色)。

        可注入 repo/matcher/wps_cache 以避免 N+1 重复构造（M4 优化）。
        """
        if not s.wps_no:
            return "⚠ 未指定WPS", "#999999"
        # 查 WPS（带缓存）
        if repo is None or matcher is None:
            from ..persistence import ProcedureRepository, get_session
            from ..standards import get_default_standard
            from ..engine import PQRMatcher
            std = get_default_standard()
            repo = ProcedureRepository(get_session(), std)
            matcher = PQRMatcher(repo, std)
            wps_cache = {}
        if wps_cache is not None and s.wps_no in wps_cache:
            wps = wps_cache[s.wps_no]
        else:
            wps = repo.get(s.wps_no)
            if wps_cache is not None:
                wps_cache[s.wps_no] = wps
        if wps is None:
            return f"? WPS {s.wps_no} 不存在", "#999999"
        if not wps.supporting_pqr_no:
            return "△ WPS无PQR依据", "#ef6c00"
        # 用 PQRMatcher 判断焊缝参数是否被覆盖
        req = WeldRequirement(
            process=wps.process,
            thickness=s.thickness,
            position=s.position,
        )
        # 用 WPS 的母材牌号作为匹配母材
        if wps.base_metals:
            req.material_grade = wps.base_metals[0].metal.grade
        results = {r.pqr_no: r for r in matcher.match(req)}
        pqr_result = results.get(wps.supporting_pqr_no)
        if pqr_result is None:
            return "△ PQR不存在", "#ef6c00"
        if pqr_result.fully_matched:
            return "✓ 已覆盖", "#2e7d32"
        return f"✗ {pqr_result.miss_count}项不符", "#c62828"

    def _on_new_product(self):
        no, ok = QInputDialog.getText(self, "新建产品", "产品编号：")
        if not ok or not no.strip():
            return
        if self._repo.get(no.strip()):
            QMessageBox.warning(self, "提示", f"产品 {no} 已存在")
            return
        self._repo.save(Product(product_no=no.strip(), name=no.strip()))
        self._refresh()

    def _on_add_seam(self):
        no = self._selected_product()
        if not no:
            QMessageBox.information(self, "提示", "请先选中一个产品")
            return
        dlg = SeamDialog(parent=self)
        if dlg.exec() == SeamDialog.DialogCode.Accepted:
            seam = dlg.get_seam()
            try:
                ok = self._repo.add_seam(no, seam)
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"添加焊缝时出错：\n{e}")
                return
            if not ok:
                QMessageBox.warning(self, "提示", "产品不存在，添加失败")
                return
            self._refresh()             # 刷新产品列表（含焊缝数列）
            self._select_product(no)    # 重新选中并刷新焊缝表

    def _select_product(self, product_no: str):
        """按产品编号选中左侧产品行，并刷新右侧焊缝表。"""
        for r in range(self.product_table.rowCount()):
            item = self.product_table.item(r, 0)
            if item and item.text() == product_no:
                self.product_table.selectRow(r)
                return
        # 未找到行也刷新一下右侧
        self.seam_table.setRowCount(0)
        self.summary.clear()

    def _on_del_product(self):
        no = self._selected_product()
        if not no:
            return
        if QMessageBox.question(
            self, "确认删除", f"删除产品 {no} 及其全部焊缝记录？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._repo.delete(no)
        self._refresh()
        self.seam_table.setRowCount(0)
        self.summary.clear()
