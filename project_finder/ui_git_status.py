from __future__ import annotations

from tkinter import BOTH, END, LEFT, RIGHT, X, StringVar, ttk

from .git_inventory import RepoSnapshot, summarize_repositories, update_readiness


class GitStatusTab(ttk.Frame):
    """Compact Git/version/update overview for the development inventory workspace."""

    def __init__(self, master, *, get_rows=None):
        super().__init__(master)
        self.get_rows = get_rows or (lambda: [])
        self.status_var = StringVar(value="Noch kein Git-Abgleich geladen")
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill=X, padx=12, pady=(12, 6))
        ttk.Label(top, text="GitHub · Versionen · Update-Status", font=("Segoe UI", 13, "bold")).pack(side=LEFT)
        ttk.Label(top, textvariable=self.status_var).pack(side=RIGHT)

        kpi = ttk.LabelFrame(self, text="Übersicht"); kpi.pack(fill=X, padx=12, pady=6)
        self.kpi_vars = {k: StringVar(value="0") for k in ("repos","tests","updates","local_newer","diverged")}
        labels = (("Repos","repos"),("Tests grün","tests"),("Updatebereit","updates"),("Lokal neuer","local_newer"),("Auseinander","diverged"))
        for i, (title, key) in enumerate(labels):
            box = ttk.Frame(kpi); box.grid(row=0, column=i, padx=12, pady=8, sticky="w")
            ttk.Label(box, text=title).pack(anchor="w")
            ttk.Label(box, textvariable=self.kpi_vars[key], font=("Segoe UI", 14, "bold")).pack(anchor="w")

        body = ttk.LabelFrame(self, text="Programme / Repositories"); body.pack(fill=BOTH, expand=True, padx=12, pady=6)
        cols=("ampel","projekt","repo","branch","version","build","test","local","update","grund")
        self.tree=ttk.Treeview(body, columns=cols, show="headings")
        titles={"ampel":"Status","projekt":"Projekt","repo":"Repository","branch":"Branch","version":"Version","build":"Build","test":"Test","local":"Lokal/Git","update":"Update","grund":"Hinweis"}
        widths={"ampel":60,"projekt":170,"repo":220,"branch":100,"version":90,"build":75,"test":85,"local":105,"update":120,"grund":390}
        for c in cols:
            self.tree.heading(c,text=titles[c]); self.tree.column(c,width=widths[c],anchor="w")
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

        actions=ttk.Frame(self); actions.pack(fill=X, padx=12, pady=(0,12))
        ttk.Button(actions,text="Ansicht aktualisieren",command=self.refresh).pack(side=LEFT)
        ttk.Label(actions,text="Automatische Updates werden nur bei eindeutig grünem, getesteten Stand freigegeben.").pack(side=RIGHT)

    @staticmethod
    def _coerce(row):
        if isinstance(row, RepoSnapshot): return row
        if isinstance(row, dict): return RepoSnapshot(**{k:v for k,v in row.items() if k in RepoSnapshot.__dataclass_fields__})
        raise TypeError("Unbekannter Repository-Datensatz")

    def refresh(self):
        rows=[]
        for raw in self.get_rows() or []:
            try: rows.append(self._coerce(raw))
            except Exception: continue
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            state, reason=update_readiness(row)
            lamp={"GREEN":"🟢","YELLOW":"🟡","RED":"🔴","BLUE":"🔵"}.get(state,"⚪")
            self.tree.insert("",END,values=(lamp,row.project,row.repository,row.default_branch,row.version or "–",row.build or "–",row.latest_test,row.local_state,row.update_mode,reason))
        s=summarize_repositories(rows)
        c=s["counts"]
        self.kpi_vars["repos"].set(str(c["total"]))
        self.kpi_vars["tests"].set(str(c["tests_pass"]))
        self.kpi_vars["updates"].set(str(c["update_ready"]))
        self.kpi_vars["local_newer"].set(str(c["local_newer"]))
        self.kpi_vars["diverged"].set(str(c["diverged"]))
        self.status_var.set(f"{c['total']} Repositories · {c['update_ready']} updatebereit")
