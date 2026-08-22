from PyQt6.QtWidgets import QMainWindow, QTabWidget
from ui.page_clock import ClockDashboardPage
from ui.hvac_page import HvacControlPage

class MainWindow(QMainWindow):
    def __init__(self, mqtt_client=None):
        super().__init__()
        self.setWindowTitle("RasPi Smart Home Panel")
        self.setMinimumSize(800, 480)
        self.tabs = QTabWidget()
        self.dashboard = ClockDashboardPage()
        self.hvac_page = HvacControlPage(mqtt_client)
        self.tabs.addTab(self.dashboard, "Dashboard Overview")
        self.tabs.addTab(self.hvac_page, "HVAC Configuration")
        self.setCentralWidget(self.tabs)
