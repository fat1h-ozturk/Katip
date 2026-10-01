"""
Centralized UI styles for Katip.
"""

MINIMAL_DARK_STYLE = """
QWidget {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
}
QDialog {
    background-color: #09090b;
    color: #f4f4f5;
}
QGroupBox {
    border: 1px solid #27272a;
    border-radius: 2px;
    margin-top: 14px;
    padding-top: 16px;
    font-weight: 600;
    color: #e4e4e7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #a1a1aa;
}
QLabel {
    color: #a1a1aa;
    font-size: 13px;
}
QLineEdit, QComboBox, QTextEdit {
    background-color: #18181b;
    border: 1px solid #3f3f46;
    border-radius: 2px;
    padding: 6px 10px;
    color: #fafafa;
    font-size: 13px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #71717a;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23a1a1aa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M6 9l6 6 6-6'/></svg>");
    width: 16px;
    height: 16px;
}
QComboBox QAbstractItemView {
    background-color: #18181b;
    border: 1px solid #3f3f46;
    selection-background-color: #27272a;
    selection-color: #ffffff;
    outline: none;
}
QAbstractItemView::item {
    min-height: 28px;
    padding: 4px 8px;
}
QPushButton {
    background-color: #18181b;
    color: #f4f4f5;
    border: 1px solid #3f3f46;
    border-radius: 2px;
    padding: 8px 16px;
    font-weight: 500;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #27272a;
    border: 1px solid #52525b;
}
QPushButton:pressed {
    background-color: #09090b;
}
QPushButton#primaryBtn {
    background-color: #fafafa;
    color: #09090b;
    border: none;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background-color: #e4e4e7;
}
QCheckBox {
    color: #d4d4d8;
    spacing: 8px;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid #27272a;
    background: #09090b;
}
QTabBar::tab {
    background: #18181b;
    color: #a1a1aa;
    border: 1px solid #27272a;
    border-bottom: none;
    padding: 8px 16px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #09090b;
    color: #fafafa;
    font-weight: 600;
}
QScrollBar:vertical { 
    width: 8px; 
    background: transparent; 
} 
QScrollBar::handle:vertical { 
    background: #3f3f46; 
    border-radius: 4px; 
} 
QScrollBar::handle:vertical:hover { 
    background: #52525b; 
} 
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { 
    height: 0px; 
}
"""
