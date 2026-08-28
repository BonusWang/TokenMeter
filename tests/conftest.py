import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import ownedByPython


@pytest.fixture(autouse=True)
def cleanup_qt_widgets():
    app = QApplication.instance()
    existing = set(app.topLevelWidgets()) if app is not None else set()
    yield
    app = QApplication.instance()
    if app is None:
        return

    # close() 通常只隐藏窗口；逐例销毁新建窗口，避免主题/语言刷新反复遍历历史控件。
    # 此时测试的 mock 已撤销，不再调用可能保存配置的 close()；关闭行为仍由用例验证。
    for widget in app.topLevelWidgets():
        # Qt 自建的桌面等内部窗口也出现在列表中，不能由测试删除；子控件随所属窗口释放。
        if widget not in existing and ownedByPython(widget):
            widget.deleteLater()
    # pytest 没有运行 app.exec()，必须显式处理延迟删除，才能在下个用例前释放子控件和定时器。
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
