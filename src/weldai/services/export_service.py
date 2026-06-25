"""报表/PDF 导出服务（ReportLab）—— NB/T 47015 一体化表格格式。

输出标准 NB/T 47015《压力容器焊接规程》风格的 WPS / PQR 表格：
单一一体化大表格，利用 SPAN 合并单元格，左右分区布局：
  - 标题行（类型 + 文件编号，贯通）
  - 单位/方法/位置/热处理（双栏）
  - 母材（左）↔ 焊接位置/焊后热处理（右）
  - 焊材（左）↔ 坡口详图（右，嵌入矢量图）
  - 焊接参数表（贯通全宽，含每道焊接方法——支持组合焊）
  - 签字栏（编制/审核/批准）

中文字体使用内嵌 NotoSansSC（font_provider 统一管理）。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..domain.enums import ProcedureType
from ..domain.procedure import Procedure
from .font_provider import get_font_path
from .groove_renderer import render_groove

_FONT_REGISTERED = False


def _ensure_font() -> str:
    """注册中文字体，返回字体名。回退到 Helvetica（中文会乱码但流程不中断）。"""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return "CN"
    fp = get_font_path()
    if fp is not None:
        try:
            pdfmetrics.registerFont(TTFont("CN", str(fp)))
            _FONT_REGISTERED = True
            return "CN"
        except Exception:
            pass
    return "Helvetica"  # 回退（无中文系统字体时）


def _type_title(t: ProcedureType) -> str:
    return {
        ProcedureType.WPS: "焊 接 工 艺 规 程 (WPS)",
        ProcedureType.PQR: "焊 接 工 艺 评 定 记 录 (PQR)",
        ProcedureType.PWPS: "预 焊 接 工 艺 规 程 (pWPS)",
    }.get(t, "焊接工艺文件")


def _fmt(v, unit: str = "") -> str:
    """格式化数值：None → 空，否则带单位。"""
    if v is None or v == "":
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v}{unit}"


# 表格列宽（6列布局，单位 mm；A4 可用宽 ≈ 180mm）
_COL_W = [16, 24, 36, 22, 34, 28]


class _RowData(list):
    """可携带属性（attrs/tmp_files）的表格行列表，供 TableStyle 读取。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs: dict = {}
        self.tmp_files: list = []


def export_procedure_pdf(procedure: Procedure, output_path: str | Path) -> Path:
    """导出单个工艺文件为 PDF（NB/T 47015 一体化表格），返回输出路径。"""
    font = _ensure_font()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=procedure.doc_no,
    )

    title_style = ParagraphStyle(
        "title", fontName=font, fontSize=14, alignment=1, spaceAfter=4
    )
    cell = ParagraphStyle("cell", fontName=font, fontSize=8, leading=10)
    label = ParagraphStyle(
        "label", fontName=font, fontSize=8, leading=10, textColor=colors.grey
    )

    data = _build_unified_table(procedure, font, cell, label)
    # 记录坡口图临时文件，构建完成后统一清理（ReportLab 在 build 时才读图）
    tmp_files = getattr(data, "tmp_files", [])

    t = Table(data, colWidths=[w * mm for w in _COL_W], repeatRows=1)
    t.setStyle(_grid_span_style(data))
    story = [Paragraph(_type_title(procedure.type), title_style), t]

    # PQR 覆盖范围（仅 PQR）
    if procedure.type == ProcedureType.PQR:
        story.append(Spacer(1, 4 * mm))
        story.append(_coverage_table(procedure, font, cell, label))

    try:
        doc.build(story)
    finally:
        for f in tmp_files:
            try:
                Path(f).unlink()
            except Exception:
                pass
    return out


def _p(text, style):
    """便捷构造 Paragraph，None/空转空串。"""
    if text is None or text == "":
        return Paragraph("", style)
    return Paragraph(str(text), style)


def _build_unified_table(
    procedure: Procedure, font: str, cell, label
) -> list:
    """构造一体化表格的数据矩阵（含 SPAN 标记在 TableStyle 中应用）。"""
    rows: _RowData = _RowData()

    # ---- 行0：文件编号（贯通全宽，作为表格首行表头）----
    rows.append([
        _p(f"<b>文件编号：{procedure.doc_no}</b>", cell), "", "", "", "", ""
    ])

    # ---- 行1：编制单位 / 项目编号 ----
    rows.append([
        _p("编制单位", label), _p(procedure.manufacturer or "", cell),
        _p("项目编号", label), _p(procedure.project_no or "", cell),
        _p("编制日期", label), _p(procedure.prepare_date or "", cell),
    ])
    # ---- 行2：焊接方法 / 机械化 / 依据PQR ----
    process_disp = procedure.process_display  # 组合焊列出全部方法
    rows.append([
        _p("焊接方法", label), _p(process_disp, cell),
        _p("机械化程度", label), _p(procedure.mechanization.cn, cell),
        _p("依据PQR", label), _p(procedure.supporting_pqr_no or "—", cell),
    ])
    # ---- 行3：评定标准 / 产品图号 / 冲击要求 ----
    rows.append([
        _p("评定标准", label), _p(procedure.standard_version or "—", cell),
        _p("产品图号", label), _p(procedure.drawing_no or "", cell),
        _p("冲击试验", label), _p("是" if procedure.impact_required else "否", cell),
    ])

    # ---- 母材区 + 焊接位置/焊后热处理（左右并排）----
    bm_start = len(rows)
    n_bm = max(len(procedure.base_metals), 1)
    # 母材表头（左3列）
    rows.append([
        _p("母材", label), _p("类别号/组别号", label), _p("牌号 / 厚度", label),
        _p("焊接位置", label),
        _p(", ".join(p.value for p in procedure.positions) or "—", cell),
        _p("", cell),
    ])
    for bm in procedure.base_metals:
        m = bm.metal
        rows.append([
            _p("", cell),
            _p(f"{m.category}<br/>{m.group.group}", cell),
            _p(f"{m.grade} / {_fmt(bm.thickness, 'mm')}", cell),
            "", "", "",  # 右侧占位（由 SPAN 合并）
        ])
    # 若无母材，补一行空
    if not procedure.base_metals:
        rows.append([_p("（无）", cell), "", "", "", "", ""])
    # 右侧：最低预热 / 焊后热处理（与母材区并排，跨行合并）
    bm_end = len(rows)  # 母材区结束行
    # 在母材区之后追加 预热/焊后热处理（右侧）—— 用单独行承载，避免与母材行重叠
    pwht = procedure.pwht
    pwht_desc = "无"
    if pwht.applied:
        pwht_desc = (
            f"{pwht.pwht_type} {_fmt(pwht.temp_min)}~{_fmt(pwht.temp_max, '℃')}"
            f" 保温{_fmt(pwht.hold_time, 'min')}"
        )
    rows.append([
        _p("母材厚度范围", label),
        _p(_fmt(procedure.deposited_thickness, "mm"), cell),
        _p("最低预热温度", label),
        _p(_fmt(procedure.preheat_min, "℃") or "无", cell),
        _p("焊后热处理", label), _p(pwht_desc, cell),
    ])

    # ---- 焊材区 + 坡口详图（左右并排）----
    rows.append([
        _p("焊接材料", label), _p("型号/分类栏位", label), _p("牌号 / 直径", label),
        _p("坡口形式与尺寸（详见下图）", label), "", "",
    ])
    for c in procedure.consumables:
        rows.append([
            _p("", cell),
            _p(f"{c.model}<br/>{c.classification_slot}", cell),
            _p(f"{c.brand} / {_fmt(c.diameter, 'mm')}", cell),
            "", "", "",
        ])
    if not procedure.consumables:
        rows.append([_p("（无）", cell), "", "", "", "", ""])

    # ---- 坡口图（嵌入 PNG，贯通右半区）----
    img_row = len(rows)
    img_cell = _build_groove_image_cell(procedure)
    tmp_files: list[str] = []
    if img_cell is not None:
        rows.append([_p("坡口详图", label), "", "", img_cell, "", ""])
        tmp_path = getattr(img_cell, "_weldai_tmp", None)
        if tmp_path:
            tmp_files.append(tmp_path)
    else:
        rows.append([_p("坡口详图", label), "", "",
                     _p(_groove_text(procedure), cell), "", ""])

    # ---- 焊接参数表（贯通全宽，含每道焊接方法——支持组合焊）----
    param_header_row = len(rows)
    rows.append([
        _p("焊道", label), _p("焊接方法", label), _p("层次", label),
        _p("焊材/直径", label), _p("电流(A)/极性", label),
        _p("电压(V)/速度", label),
    ])
    for pa in procedure.passes:
        p_eff = pa.effective_process(procedure.process)
        cons = pa.consumable
        cons_disp = f"{cons.brand}" if cons else ""
        if pa.diameter:
            cons_disp += f" /φ{pa.diameter:g}"
        cur = (f"{_fmt(pa.current_min)}~{_fmt(pa.current_max)}"
               if (pa.current_min or pa.current_max) else "")
        pol = pa.current_type.cn if pa.current_type else ""
        cur_disp = f"{cur}<br/>{pol}" if cur or pol else ""
        vol = (f"{_fmt(pa.voltage_min)}~{_fmt(pa.voltage_max)}"
               if (pa.voltage_min or pa.voltage_max) else "")
        spd = _fmt(pa.travel_speed)
        vol_disp = f"{vol}<br/>{spd}cm/min" if vol or spd else ""
        rows.append([
            _p(str(pa.sequence), cell),
            _p(p_eff.value, cell),
            _p(pa.layer_role, cell),
            _p(cons_disp, cell),
            _p(cur_disp, cell),
            _p(vol_disp, cell),
        ])
    if not procedure.passes:
        rows.append([_p("（无焊道参数）", cell), "", "", "", "", ""])

    # ---- 签字栏（贯通全宽）----
    sign_row = len(rows)
    rows.append([
        _p("编制", label), _p(procedure.prepared_by or "", cell),
        _p("审核", label), _p(procedure.reviewed_by or "", cell),
        _p("批准", label), _p(procedure.approved_by or "", cell),
    ])

    # 保存行索引供 TableStyle SPAN 使用
    rows.attrs = {  # type: ignore[attr-defined]
        "bm_start": bm_start, "bm_end": bm_end,
        "img_row": img_row, "param_header_row": param_header_row,
        "sign_row": sign_row,
    }
    rows.tmp_files = tmp_files  # type: ignore[attr-defined]
    return rows


def _groove_text(procedure: Procedure) -> str:
    """坡口参数文字说明。"""
    if not procedure.joints:
        return "（无接头数据）"
    j = procedure.joints[0]
    g = j.groove
    return (f"{j.type.cn} | 坡口{g.type}形 | 角度{_fmt(g.angle, '°')} | "
            f"钝边{_fmt(g.root_face, 'mm')} | 间隙{_fmt(g.root_gap, 'mm')}"
            + (" | 带衬垫" if g.has_backing else ""))


def _build_groove_image_cell(procedure: Procedure):
    """绘制坡口 PNG 并返回 (Image flowable, tmp_path)；失败返回 None。

    注意：临时文件由调用方在 doc.build() 后清理（ReportLab 构建时才读图）。
    """
    if not procedure.joints:
        return None
    joint = procedure.joints[0]
    thickness = joint.thickness or (
        procedure.base_metals[0].thickness if procedure.base_metals else 16)
    tmp = Path(tempfile.mktemp(suffix=".png"))
    try:
        render_groove(joint.groove, thickness, tmp)
        if tmp.exists() and tmp.stat().st_size > 0:
            # 宽度限制在右半区（约 80mm），等比缩放
            img = Image(str(tmp), width=80 * mm, height=60 * mm)
            img._weldai_tmp = str(tmp)  # 标记，供调用方清理
            return img
    except Exception:
        return None
    return None


def _grid_span_style(rows: list) -> TableStyle:
    """一体化表格样式：边框、背景、关键 SPAN 合并。"""
    attrs = getattr(rows, "attrs", {})
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        # 标题行（行0）贯通 + 深色背景
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        # 标签列浅灰
        ("BACKGROUND", (0, 1), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 1), (2, -1), colors.whitesmoke),
        ("BACKGROUND", (4, 1), (4, -1), colors.whitesmoke),
    ]
    bm_start = attrs.get("bm_start")
    bm_end = attrs.get("bm_end")
    img_row = attrs.get("img_row")
    param_header_row = attrs.get("param_header_row")
    sign_row = attrs.get("sign_row")
    # 焊接位置/预热 行：右侧 3 列合并显示
    if bm_start is not None:
        style.append(("SPAN", (3, bm_start), (5, bm_start)))
    # 母材各行右侧（焊接位置）跨行合并 → 由后续预热行承接
    if bm_start is not None and bm_end is not None and bm_end > bm_start + 1:
        style.append(("SPAN", (3, bm_start + 1), (5, bm_end - 1)))
    # 坡口图行：右3列合并
    if img_row is not None:
        style.append(("SPAN", (1, img_row), (2, img_row)))
        style.append(("SPAN", (3, img_row), (5, img_row)))
    # 参数表头行加深
    if param_header_row is not None:
        style.append(("BACKGROUND", (0, param_header_row),
                      (-1, param_header_row), colors.HexColor("#e3f2fd")))
    # 签字栏加深
    if sign_row is not None:
        style.append(("BACKGROUND", (0, sign_row), (-1, sign_row),
                      colors.HexColor("#fff3e0")))
    return TableStyle(style)


def _coverage_table(procedure: Procedure, font: str, cell, label):
    """PQR 评定覆盖范围表。"""
    from ..engine import CoverageEngine
    from ..standards import get_default_standard

    std = get_default_standard()
    cov = CoverageEngine(std)
    trange = cov.thickness_coverage(procedure)
    prange = cov.diameter_coverage(procedure)
    positions = [pos.value for pos in cov.position_coverage(procedure)]

    def _fmt_range(lo, hi):
        hi_str = f"{hi:g}" if hi is not None else "不限"
        return f"{lo:g} ~ {hi_str} mm"

    rows = [
        [_p("评定覆盖范围（依据 NB/T 47014）", label), _p("", cell)],
        [_p("母材厚度覆盖", label),
         _p(_fmt_range(trange.min_t, trange.max_t) if trange else "—", cell)],
        [_p("管径覆盖", label),
         _p(_fmt_range(prange.min_d, prange.max_d) if prange else "（板材）", cell)],
        [_p("焊接位置覆盖", label),
         _p(", ".join(positions) if positions else "—", cell)],
    ]
    t = Table(rows, colWidths=[40 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3f2fd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    return t
