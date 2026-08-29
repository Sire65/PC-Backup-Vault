import unittest
from unittest.mock import patch

import kc_backup_toolbar_consolidation as mod


class FakeWidget:
    def __init__(self, master=None, text="", command=None, **_kwargs):
        self.master = master
        self.text = text
        self.command = command
        self.forgotten = False
        self.pack_calls = []

    def pack(self, **kwargs):
        self.pack_calls.append(kwargs)

    def pack_forget(self):
        self.forgotten = True


class FakeApp:
    _kc_backup_central_enabled = True
    _kc_scheduler_observability_enabled = True
    _kc_source_discovery_enabled = True

    def _build(self):
        status_bar = FakeWidget(master=self)
        self._status_bar = status_bar
        self.btn_kc_programs = FakeWidget(status_bar, text="KC Programme")
        self.btn_kc_source_discovery = FakeWidget(status_bar, text="KC Quellen finden")
        self.btn_backup_calendar = FakeWidget(status_bar, text="🗓 Backup-Kalender")
        self.btn_scheduler_automation = FakeWidget(status_bar, text="Automatik: AUS")
        self.btn_scheduler_runtime = FakeWidget(status_bar, text="… Scheduler: STARTET")
        self._old_buttons = (
            self.btn_kc_programs,
            self.btn_kc_source_discovery,
            self.btn_backup_calendar,
            self.btn_scheduler_automation,
            self.btn_scheduler_runtime,
        )

    def open_kc_programs(self):
        return None

    def open_kc_source_discovery(self):
        return None

    def open_backup_calendar(self):
        return None

    def _kc_toggle_scheduler_automation(self):
        return None

    def _kc_show_scheduler_status(self):
        return None

    def _kc_refresh_scheduler_indicator(self):
        return None

    def after(self, _delay, callback):
        callback()


class BackupCentralToolbarTests(unittest.TestCase):
    def test_labels_are_unique_and_complete(self):
        labels = mod.backup_central_button_labels()
        self.assertEqual(len(labels), len(set(labels)))
        self.assertIn("KC Programme", labels)
        self.assertIn("KC Quellen finden", labels)
        self.assertIn("🗓 Backup-Kalender", labels)
        self.assertIn("Automatik: AUS", labels)
        self.assertIn("… Scheduler: STARTET", labels)

    def test_prerequisites_are_required(self):
        class Incomplete:
            pass
        with self.assertRaises(RuntimeError):
            mod.enable_backup_central_toolbar(Incomplete)

    def test_old_crowded_buttons_are_hidden_and_recreated_once(self):
        class App(FakeApp):
            pass

        with patch.object(mod.ttk, "LabelFrame", FakeWidget), \
             patch.object(mod.ttk, "Button", FakeWidget), \
             patch.object(mod.ttk, "Label", FakeWidget):
            mod.enable_backup_central_toolbar(App)
            app = App()
            app._build()

        self.assertTrue(all(button.forgotten for button in app._old_buttons))
        self.assertIsNotNone(app.backup_central_toolbar)
        self.assertIs(app.btn_kc_programs.master, app.backup_central_toolbar)
        self.assertIs(app.btn_kc_source_discovery.master, app.backup_central_toolbar)
        self.assertIs(app.btn_backup_calendar.master, app.backup_central_toolbar)
        self.assertIs(app.btn_scheduler_automation.master, app.backup_central_toolbar)
        self.assertIs(app.btn_scheduler_runtime.master, app.backup_central_toolbar)


if __name__ == "__main__":
    unittest.main()
