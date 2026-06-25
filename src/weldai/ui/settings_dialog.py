"""设置对话框：配置 LLM API key 和服务商。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..services.config_service import (
    PROVIDER_PRESETS,
    AppConfig,
    LLMConfig,
    load_config,
    save_config,
)


class SettingsDialog(QDialog):
    """LLM 配置对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 · LLM 焊接专家")
        self.resize(560, 420)
        self._config = load_config()
        self._build_ui()
        self._load_config()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self._build_llm_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_llm_group(self) -> QGroupBox:
        gb = QGroupBox("大语言模型（LLM）配置 · 焊接专家问答")
        form = QFormLayout(gb)

        self.provider = QComboBox()
        for key, info in PROVIDER_PRESETS.items():
            self.provider.addItem(info["label"], key)
        self.provider.currentIndexChanged.connect(self._on_provider_change)
        form.addRow("服务商：", self.provider)

        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("OpenAI 兼容 API 地址，如 https://api.xxx.com/v1")
        form.addRow("API 地址：", self.base_url)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("在此粘贴你的 API Key（从服务商控制台获取）")
        form.addRow("API Key：", self.api_key)

        show_btn = QPushButton("显示/隐藏 Key")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self._toggle_key_visible)
        form.addRow("", show_btn)

        self.model = QLineEdit()
        self.model.setPlaceholderText("模型名称，如 glm-4-flash / deepseek-chat")
        form.addRow("模型：", self.model)

        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2); self.temperature.setSingleStep(0.1)
        self.temperature.setValue(0.3)
        form.addRow("Temperature：", self.temperature)

        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(100, 8000); self.max_tokens.setSingleStep(500)
        self.max_tokens.setValue(2000)
        form.addRow("Max Tokens：", self.max_tokens)

        form.addRow(QLabel(
            "<span style='color:#888;font-size:11px'>"
            "key 保存在本地 ~/.weldai/config.json（已混淆），不会上传。"
            "调用费用由你的 API 账户承担。</span>"
        ))
        return gb

    def _toggle_key_visible(self, checked: bool) -> None:
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _on_provider_change(self) -> None:
        """切换服务商时自动填充预设地址和模型。"""
        key = self.provider.currentData()
        preset = PROVIDER_PRESETS.get(key, {})
        if key != "custom":
            self.base_url.setText(preset.get("base_url", ""))
            default_model = preset.get("model", "")
            if default_model:
                self.model.setText(default_model)

    def _load_config(self) -> None:
        llm = self._config.llm
        idx = self.provider.findData(llm.provider)
        if idx >= 0:
            self.provider.setCurrentIndex(idx)
        self.base_url.setText(llm.base_url)
        self.api_key.setText(llm.api_key)
        self.model.setText(llm.model)
        self.temperature.setValue(llm.temperature)
        self.max_tokens.setValue(llm.max_tokens)

    def _on_save(self) -> None:
        self._config.llm = LLMConfig(
            provider=self.provider.currentData(),
            base_url=self.base_url.text().strip(),
            api_key=self.api_key.text().strip(),
            model=self.model.text().strip() or "gpt-3.5-turbo",
            temperature=self.temperature.value(),
            max_tokens=self.max_tokens.value(),
        )
        save_config(self._config)
        self.accept()

    def get_config(self) -> AppConfig:
        return self._config
