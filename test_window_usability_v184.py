from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox


def apply_test_window_usability_v184(AppClass):
    """Make the consolidated test window fully scrollable and readable.

    This is deliberately a UI-only wrapper around the existing test runner. It does not
    change, suppress or reinterpret any test result.
    """
    original = AppClass.run_all_tests_v180
    if getattr(original, "_pbv_test_window_usability_v184", False):
        return

    def _walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from _walk(child)

    def run_all_tests_with_scroll(self):
        result = original(self)

        def polish():
            test_win = None
            for child in self.winfo_children():
                if isinstance(child, tk.Toplevel):
                    try:
                        if child.title() == "PC Backup Vault – Alle Tests":
                            test_win = child
                            break
                    except Exception:
                        pass
            if test_win is None or not test_win.winfo_exists():
                return

            # Use the available desktop height, but leave room for taskbar/window chrome.
            try:
                sw = test_win.winfo_screenwidth()
                sh = test_win.winfo_screenheight()
                width = min(1220, max(920, sw - 90))
                height = min(880, max(600, sh - 130))
                x = max(0, (sw - width) // 2)
                y = max(0, (sh - height) // 3)
                test_win.geometry(f"{width}x{height}+{x}+{y}")
            except Exception:
                pass

            tree = next((w for w in _walk(test_win) if isinstance(w, ttk.Treeview)), None)
            if tree is None:
                return

            # Some details contain several lines (for example KC Push/E-Mail status).
            # A taller row keeps every line visible; the existing vertical scrollbar then
            # reaches every test row without clipping the final entries.
            style = ttk.Style(test_win)
            style.configure("PBV.AllTests.Treeview", rowheight=54)
            tree.configure(style="PBV.AllTests.Treeview")

            def wheel(event):
                delta = getattr(event, "delta", 0)
                if delta:
                    tree.yview_scroll(int(-delta / 120), "units")
                return "break"

            def shift_wheel(event):
                delta = getattr(event, "delta", 0)
                if delta:
                    tree.xview_scroll(int(-delta / 120), "units")
                return "break"

            tree.bind("<MouseWheel>", wheel, add="+")
            tree.bind("<Shift-MouseWheel>", shift_wheel, add="+")
            tree.bind("<Home>", lambda e: (tree.yview_moveto(0.0), "break")[1], add="+")
            tree.bind("<End>", lambda e: (tree.yview_moveto(1.0), "break")[1], add="+")

            def show_full_detail(event=None):
                sel = tree.selection()
                if not sel:
                    return
                values = tree.item(sel[0], "values")
                if not values:
                    return
                code = values[0] if len(values) > 0 else ""
                name = values[1] if len(values) > 1 else ""
                outcome = values[2] if len(values) > 2 else ""
                details = values[3] if len(values) > 3 else ""
                messagebox.showinfo(
                    f"Test {code}",
                    f"{name}\n\nErgebnis: {outcome}\n\n{details}",
                    parent=test_win,
                )

            tree.bind("<Double-1>", show_full_detail, add="+")

        self.after(80, polish)
        return result

    run_all_tests_with_scroll._pbv_test_window_usability_v184 = True
    AppClass.run_all_tests_v180 = run_all_tests_with_scroll
