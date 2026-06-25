"""工艺文件批量管理服务。

功能：
  - 批量校验：对多个 WPS 一次性校验（相对各自支撑 PQR）
  - 关联查询：按 PQR 查找其支撑的所有 WPS
  - 克隆：复制工艺文件生成新编号（用于基于现有文件快速创建）
  - Excel 导入导出：批量录入/导出工艺文件清单

Excel 用 openpyxl（python-docx 的生态伙伴，已是间接依赖），
若未安装则导出 CSV 作为回退。
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from ..domain.enums import ProcedureType
from ..domain.procedure import Procedure
from ..engine import FactorEngine, QualificationResult
from ..persistence import ProcedureRepository
from ..standards.base import StandardProfile


@dataclass
class BatchVerifyItem:
    """批量校验单项结果。"""

    wps_no: str
    pqr_no: str
    verdict: str                  # 简短结论
    success: bool                 # 是否通过（无需重新评定且覆盖OK）
    changes_count: int            # 变更项数
    needs_requalify: bool
    error: str = ""               # 无法校验时的错误（如缺PQR）


class BatchService:
    """工艺文件批量管理服务。"""

    def __init__(self, repo: ProcedureRepository, standard: StandardProfile):
        self.repo = repo
        self.engine = FactorEngine(standard)

    # ------------------------------------------------------------------
    # 批量校验
    # ------------------------------------------------------------------

    def verify_all_wps(self) -> list[BatchVerifyItem]:
        """校验库中所有 WPS（各自相对支撑 PQR）。"""
        wps_list = self.repo.list_all(ProcedureType.WPS)
        results: list[BatchVerifyItem] = []
        for wps in wps_list:
            results.append(self._verify_one(wps))
        return results

    def _verify_one(self, wps: Procedure) -> BatchVerifyItem:
        if not wps.supporting_pqr_no:
            return BatchVerifyItem(
                wps_no=wps.doc_no, pqr_no="—",
                verdict="未关联PQR", success=False, changes_count=0,
                needs_requalify=False, error="未填写依据PQR编号",
            )
        pqr = self.repo.get(wps.supporting_pqr_no)
        if pqr is None:
            return BatchVerifyItem(
                wps_no=wps.doc_no, pqr_no=wps.supporting_pqr_no,
                verdict="PQR不存在", success=False, changes_count=0,
                needs_requalify=False, error=f"找不到PQR {wps.supporting_pqr_no}",
            )
        result = self.engine.compare(pqr, wps)
        success = (not result.needs_requalify) and result.hard_coverage_ok
        return BatchVerifyItem(
            wps_no=wps.doc_no, pqr_no=wps.supporting_pqr_no,
            verdict=result.verdict_cn, success=success,
            changes_count=len(result.changes),
            needs_requalify=result.needs_requalify,
        )

    # ------------------------------------------------------------------
    # 关联查询：PQR → 关联的 WPS
    # ------------------------------------------------------------------

    def find_wps_by_pqr(self, pqr_no: str) -> list[Procedure]:
        """查找某 PQR 支撑的所有 WPS。"""
        all_wps = self.repo.list_all(ProcedureType.WPS)
        return [w for w in all_wps if w.supporting_pqr_no == pqr_no]

    def find_usable_for_seam(
        self, req: "WeldRequirement"
    ) -> list[tuple[Procedure, list[Procedure]]]:
        """焊缝需求 → 可用的 (PQR, [关联WPS]) 列表。

        返回完全覆盖该焊缝的 PQR 及其支撑的 WPS。
        用于焊缝追溯页：录入焊缝参数后推荐可用工艺文件。
        """
        from ..engine import PQRMatcher
        matcher = PQRMatcher(self.repo, self.engine.standard)
        matched_pqrs = matcher.find_matched(req)
        result: list[tuple[Procedure, list[Procedure]]] = []
        for pqr in matched_pqrs:
            wpss = self.find_wps_by_pqr(pqr.doc_no)
            result.append((pqr, wpss))
        return result

    # ------------------------------------------------------------------
    # 克隆
    # ------------------------------------------------------------------

    def clone(
        self, source_doc_no: str, new_doc_no: str,
        new_type: ProcedureType | None = None,
    ) -> Procedure | None:
        """克隆工艺文件，生成新编号。

        new_type: 不指定则沿用源文件类型
        """
        source = self.repo.get(source_doc_no)
        if source is None:
            return None
        new = copy.deepcopy(source)
        new.doc_no = new_doc_no
        if new_type is not None:
            new.type = new_type
        # 克隆时清空支撑关系（避免误关联）
        if new.type == ProcedureType.PQR:
            new.supporting_pqr_no = ""
        self.repo.save(new)
        return new

    # ------------------------------------------------------------------
    # Excel 导出（工艺文件清单）
    # ------------------------------------------------------------------

    def export_to_excel(self, output_path: str) -> str:
        """导出工艺文件清单到 Excel/CSV。"""
        docs = self.repo.list_all()
        rows = [
            {
                "编号": d.doc_no, "类型": d.type.value,
                "焊接方法": d.process.cn,
                "母材": ", ".join(bm.metal.grade for bm in d.base_metals),
                "厚度": ", ".join(str(bm.thickness) for bm in d.base_metals),
                "依据PQR": d.supporting_pqr_no or "",
                "编制单位": d.manufacturer,
                "项目编号": d.project_no,
                "标准": d.standard_version,
            }
            for d in docs
        ]
        out = str(output_path)
        # 优先 Excel，回退 CSV
        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "工艺文件清单"
            if rows:
                ws.append(list(rows[0].keys()))
                for r in rows:
                    ws.append(list(r.values()))
                # 列宽自适应
                for col in ws.columns:
                    max_len = max(len(str(c.value or "")) for c in col)
                    ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)
            wb.save(out)
            return out
        except ImportError:
            # 回退 CSV
            import csv
            csv_path = out.rsplit(".", 1)[0] + ".csv"
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                if rows:
                    w = csv.DictWriter(f, fieldnames=rows[0].keys())
                    w.writeheader()
                    w.writerows(rows)
            return csv_path
