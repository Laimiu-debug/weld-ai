"""焊缝追溯模块单测。"""
from __future__ import annotations

from datetime import date

import pytest

from weldai.domain.enums import JointType, Position
from weldai.domain.weld_seam import Product, WeldSeam
from weldai.persistence import ProductRepository, get_session, init_db


@pytest.fixture
def repo():
    init_db(":memory:")
    return ProductRepository(get_session())


def _sample_product() -> Product:
    return Product(
        product_no="R2026-001",
        name="分离器",
        drawing_no="DWG-001",
        seams=[
            WeldSeam(seam_no="A1", wps_no="WPS-001", welder_stamp="A001",
                     joint_type=JointType.BUTT, position=Position.PLATE_1G,
                     length=3000, thickness=16, weld_date=date.today()),
            WeldSeam(seam_no="B2", wps_no="WPS-001", welder_stamp="A002",
                     joint_type=JointType.BUTT, position=Position.PIPE_2G,
                     length=5000, thickness=16, weld_date=date.today()),
            WeldSeam(seam_no="C1", wps_no="WPS-002", welder_stamp="A001",
                     joint_type=JointType.FILLET, position=Position.PLATE_2G,
                     length=500, thickness=16),
        ],
    )


# ---------------------------------------------------------------------------
# 领域模型
# ---------------------------------------------------------------------------

class TestWeldSeamModel:
    def test_main_seam_classification(self):
        """A/B类焊缝为主焊缝，C/D类为次要。"""
        p = _sample_product()
        assert p.seams[0].is_main_seam   # A1
        assert p.seams[1].is_main_seam   # B2
        assert not p.seams[2].is_main_seam  # C1

    def test_product_aggregate_stats(self):
        p = _sample_product()
        assert p.main_seam_count == 2
        assert p.welder_count == 2     # A001, A002
        assert p.wps_count == 2        # WPS-001, WPS-002

    def test_seam_by_no_lookup(self):
        p = _sample_product()
        assert p.seam_by_no("B2") is not None
        assert p.seam_by_no("B2").welder_stamp == "A002"
        assert p.seam_by_no("X9") is None


# ---------------------------------------------------------------------------
# 仓储 CRUD + 往返
# ---------------------------------------------------------------------------

class TestProductRepository:
    def test_save_and_get_roundtrip(self, repo):
        repo.save(_sample_product())
        loaded = repo.get("R2026-001")
        assert loaded is not None
        assert loaded.name == "分离器"
        assert len(loaded.seams) == 3
        assert loaded.seams[0].welder_stamp == "A001"
        assert loaded.seams[0].joint_type == JointType.BUTT
        assert loaded.main_seam_count == 2

    def test_add_seam(self, repo):
        repo.save(_sample_product())
        ok = repo.add_seam("R2026-001", WeldSeam(
            seam_no="D1", wps_no="WPS-003", welder_stamp="A003",
            joint_type=JointType.NOZZLE, position=Position.PIPE_6G,
            length=800, thickness=16,
        ))
        assert ok
        loaded = repo.get("R2026-001")
        assert len(loaded.seams) == 4
        assert loaded.seam_by_no("D1") is not None
        # 追加的焊缝应继承产品信息
        assert loaded.seams[3].product_no == "R2026-001"
        assert loaded.seams[3].drawing_no == "DWG-001"

    def test_add_seam_nonexistent_product(self, repo):
        ok = repo.add_seam("不存在", WeldSeam(seam_no="A1"))
        assert not ok

    def test_list_all(self, repo):
        repo.save(_sample_product())
        repo.save(Product(product_no="R2026-002", name="换热器"))
        products = repo.list_all()
        assert len(products) == 2

    def test_delete(self, repo):
        repo.save(_sample_product())
        assert repo.delete("R2026-001") is True
        assert repo.get("R2026-001") is None
        assert repo.delete("R2026-001") is False

    def test_update_existing(self, repo):
        repo.save(_sample_product())
        p = repo.get("R2026-001")
        p.customer = "中石化"
        repo.save(p)
        loaded = repo.get("R2026-001")
        assert loaded.customer == "中石化"
        assert len(repo.list_all()) == 1  # 未重复
