# weldAI · 国内压力容器焊接管理平台

对标 weldassistant，面向国内压力容器行业的焊接管理桌面软件。核心是多标准可切换的焊接工艺评定规则引擎。

## 技术栈

- **UI**: PySide6 (Qt6)
- **业务/规则引擎**: Python 3.11+
- **ORM**: SQLAlchemy 2.0
- **数据库**: SQLite (WAL)
- **规则数据**: YAML（标准升级只换数据包，不改代码）
- **报表**: ReportLab + QtPrinting

## 核心特性

- 📐 **WPS / pWPS / PQR** 编制与管理（依据 NB/T 47015）
- ⚙️ **规则引擎**：自动判断因素变更等级、计算覆盖范围（依据 NB/T 47014）
- 🔀 **多标准可切换**：NB/T 47014-2023 / 2011 / 预留 ASME IX
- 👷 **焊工资格管理**（依据 TSG Z6002-2026）
- 📚 **基础数据库**：母材(GB牌号+类组) / 焊材(牌号+型号) / 气体 / 接头

## 安装

```bash
pip install -e ".[dev]"
```

## 运行

```bash
weldai
# 或
python -m weldai.main
```

## 测试

```bash
pytest
```

## 项目结构

```
src/weldai/
├── domain/      领域模型（纯实体）
├── standards/   多标准规则包（StandardProfile + YAML 数据）
├── engine/      规则引擎（因素判定/覆盖计算/焊工覆盖）
├── persistence/ 数据访问（SQLAlchemy ORM + SQLite）
├── services/    应用服务
└── ui/          PySide6 界面
```

## 三级变更因素（NB/T 47014）

| 等级 | 中文 | 变更后果 |
|------|------|---------|
| ESSENTIAL | 重要因素 | 必须重新评定 |
| SUPPLEMENTAL | 补加因素 | 有冲击要求→补做冲击；否则仅改 WPS |
| NONESSENTIAL | 次要因素 | 仅改 WPS，无需重新评定 |

## 标准数据来源

详见 [docs/standards_sources.md](docs/standards_sources.md)
