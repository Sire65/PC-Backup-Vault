from __future__ import annotations

import threading
import time
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, BooleanVar, DoubleVar, StringVar, filedialog, messagebox, ttk

from .decision_engine import classify_inventory, export_inventory_csv, export_inventory_json, inventory_summary
from .git_handoff import create_git_handoff
from .github_compare import compare_inventory, export_compare_report
from .recovery_branch import create_recovery_branches, validate_recovery_preview
from .recovery_preview import build_recovery_preview, export_recovery_preview
from .recovery_upload import build_recovery_upload_plan, upload_recovery_files
from .scanner import cleanup_candidates, count_scan_files, quarantine, scan


class ProjectFinderTab(ttk.Frame):
    """Produktiver Inventurmodus. Riskante Schreibvorgänge brauchen explizite Freigaben."""

    def __init__(self, master, *, quarantine_root: str | None = None):
        super().__init__(master)
        self.roots: list[str] = []
        self.items = []
        self.github_report: dict | None = None
        self.github_by_path: dict[str, dict] = {}
        self.recovery_preview: dict | None = None
        self.recovery_branch_result: dict | None = None
        self.recovery_upload_plan: dict | None = None
        self.stop_flag = False
        self.scan_total = 0
        self.scan_started = 0.0
        self.quarantine_root = quarantine_root or str(Path.home() / 'PC-Backup-Vault-Quarantaene')
        self.status_var = StringVar(value='Bereit · Inventur verändert keine Quelldateien.')
        self.progress_var = DoubleVar(value=0.0)
        self.progress_text = StringVar(value='0 % · 0 / 0 Dateien · Rest 0 · Restzeit —')
        self.only_kc = BooleanVar(value=True)
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill=X, padx=12, pady=(12, 6))
        ttk.Label(top, text='Festplatten-Inventur / Projekt-Finder', font=('Segoe UI', 13, 'bold')).pack(side=LEFT)
        ttk.Label(top, textvariable=self.status_var).pack(side=RIGHT)

        source = ttk.LabelFrame(self, text='1 · Suchbereiche')
        source.pack(fill=X, padx=12, pady=6)
        btns = ttk.Frame(source)
        btns.pack(fill=X, padx=8, pady=8)
        ttk.Button(btns, text='Ordner hinzufügen…', command=self.add_folder).pack(side=LEFT, padx=(0, 6))
        ttk.Button(btns, text='Laufwerk/Ordner entfernen', command=self.remove_selected_root).pack(side=LEFT)
        self.root_list = ttk.Treeview(source, columns=('path',), show='headings', height=4)
        self.root_list.heading('path', text='Ausgewählte Laufwerke / Verzeichnisse')
        self.root_list.column('path', width=900, anchor='w')
        self.root_list.pack(fill=X, padx=8, pady=(0, 8))

        scanbox = ttk.LabelFrame(self, text='2 · Read-only Inventur')
        scanbox.pack(fill=X, padx=12, pady=6)
        bar = ttk.Frame(scanbox)
        bar.pack(fill=X, padx=8, pady=(8, 4))
        ttk.Button(bar, text='Inventur starten', command=self.start_scan).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bar, text='Abbrechen', command=self.stop_scan).pack(side=LEFT, padx=(0, 12))
        ttk.Checkbutton(bar, text='Nur relevante Projekt-/Git-/Prüffunde anzeigen', variable=self.only_kc).pack(side=LEFT)
        progress_row = ttk.Frame(scanbox)
        progress_row.pack(fill=X, padx=8, pady=(2, 8))
        self.progress = ttk.Progressbar(progress_row, orient='horizontal', mode='determinate', maximum=100.0, variable=self.progress_var)
        self.progress.pack(fill=X, expand=True, side=LEFT, padx=(0, 10))
        ttk.Label(progress_row, textvariable=self.progress_text, width=52, anchor='e').pack(side=RIGHT)

        results = ttk.LabelFrame(self, text='3 · Entscheidung: Git / Behalten / Prüfen / Quarantäne')
        results.pack(fill=BOTH, expand=True, padx=12, pady=6)
        cols = ('ampel', 'name', 'version', 'typ', 'groesse', 'datum', 'git', 'github', 'inventur', 'sicherheit', 'pfad')
        self.tree = ttk.Treeview(results, columns=cols, show='headings', selectmode='extended')
        titles = {
            'ampel': 'Status', 'name': 'Datei', 'version': 'Version', 'typ': 'Typ', 'groesse': 'Größe',
            'datum': 'Geändert', 'git': 'Git', 'github': 'GitHub-Vergleich', 'inventur': 'Inventur',
            'sicherheit': 'Sicherheit', 'pfad': 'Pfad',
        }
        widths = {
            'ampel': 65, 'name': 190, 'version': 80, 'typ': 100, 'groesse': 80, 'datum': 125,
            'git': 90, 'github': 145, 'inventur': 140, 'sicherheit': 75, 'pfad': 430,
        }
        for c in cols:
            self.tree.heading(c, text=titles[c])
            self.tree.column(c, width=widths[c], anchor='w')
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

        actions = ttk.Frame(self)
        actions.pack(fill=X, padx=12, pady=(0, 4))
        ttk.Button(actions, text='Zusammenfassung kopieren', command=self.copy_summary).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text='Inventur JSON', command=lambda: self.export('json')).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text='Inventur CSV', command=lambda: self.export('csv')).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text='Git-Übergabepaket erstellen…', command=self.create_git_package).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text='Mit GitHub vergleichen (read-only)…', command=self.start_github_compare).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text='Vergleichsbericht JSON…', command=self.export_github_report).pack(side=LEFT)

        recovery = ttk.Frame(self)
        recovery.pack(fill=X, padx=12, pady=(0, 12))
        ttk.Button(recovery, text='Recovery-Branch Vorschau…', command=self.create_recovery_preview).pack(side=LEFT, padx=(0, 6))
        ttk.Button(recovery, text='Recovery-Branches anlegen…', command=self.create_recovery_branches_ui).pack(side=LEFT, padx=(0, 6))
        ttk.Button(recovery, text='Recovery-Upload planen…', command=self.plan_recovery_upload).pack(side=LEFT, padx=(0, 6))
        ttk.Button(recovery, text='Dateien auf Recovery-Branches übertragen…', command=self.upload_recovery_files_ui).pack(side=LEFT, padx=(0, 12))
        ttk.Button(recovery, text='Sichere Dubletten in Quarantäne…', command=self.quarantine_selected).pack(side=RIGHT)

    def _reset_recovery_state(self):
        self.recovery_preview = None
        self.recovery_branch_result = None
        self.recovery_upload_plan = None

    def add_folder(self):
        p = filedialog.askdirectory(title='Laufwerk oder Verzeichnis für Inventur wählen')
        if p and p not in self.roots:
            self.roots.append(p)
            self.root_list.insert('', END, values=(p,))

    def remove_selected_root(self):
        for iid in self.root_list.selection():
            vals = self.root_list.item(iid, 'values')
            if vals and vals[0] in self.roots:
                self.roots.remove(vals[0])
            self.root_list.delete(iid)

    @staticmethod
    def _fmt_eta(seconds: float | None) -> str:
        if seconds is None or seconds < 0 or seconds == float('inf'):
            return '—'
        sec = int(round(seconds))
        if sec < 60:
            return f'{sec} s'
        minutes, sec = divmod(sec, 60)
        if minutes < 60:
            return f'{minutes} min {sec:02d} s'
        hours, minutes = divmod(minutes, 60)
        return f'{hours} h {minutes:02d} min'

    def _set_progress(self, done: int, path: str = ''):
        total = max(0, int(self.scan_total))
        done = max(0, int(done))
        pct = min(100.0, (done / total * 100.0) if total else 0.0)
        rest = max(0, total - done)
        elapsed = max(0.0, time.monotonic() - self.scan_started) if self.scan_started else 0.0
        eta = None
        if done > 0 and elapsed > 0 and rest > 0:
            eta = elapsed / done * rest
        elif total and rest == 0:
            eta = 0.0
        self.progress_var.set(pct)
        self.progress_text.set(f'{pct:5.1f} % · {done:,} / {total:,} Dateien · Rest {rest:,} · Restzeit {self._fmt_eta(eta)}')
        if path:
            self.status_var.set(f'Inventur läuft · {done:,}/{total:,} · {path}')

    def start_scan(self):
        if not self.roots:
            messagebox.showinfo('Projekt-Finder', 'Bitte zuerst mindestens ein Laufwerk oder Verzeichnis auswählen.')
            return
        self.stop_flag = False
        self.items = []
        self.github_report = None
        self.github_by_path = {}
        self._reset_recovery_state()
        self.tree.delete(*self.tree.get_children())
        self.scan_total = 0
        self.scan_started = 0.0
        self.progress_var.set(0.0)
        self.progress_text.set('Vorprüfung · Dateien werden gezählt…')
        self.status_var.set('Vorprüfung läuft · Nur Lesen · Dateianzahl wird ermittelt')
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            total = count_scan_files(
                self.roots,
                progress=lambda n, p: self.after(0, lambda n=n, p=p: self.status_var.set(f'Vorprüfung · mindestens {n:,} Dateien gefunden · {p}')),
                stop_requested=lambda: self.stop_flag,
            )
            if self.stop_flag:
                self.after(0, lambda: self.status_var.set('Inventur abgebrochen · keine Quelldatei verändert'))
                return
            self.scan_total = total
            self.scan_started = time.monotonic()
            self.after(0, lambda: self._set_progress(0))
            self.items = scan(
                self.roots,
                hash_only_interesting=False,
                progress=lambda n, p: self.after(0, lambda n=n, p=p: self._set_progress(n, p)),
                stop_requested=lambda: self.stop_flag,
            )
            self.after(0, self._render)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror('Projekt-Finder', str(e)))
            self.after(0, lambda: self.status_var.set('Fehler bei Inventur'))

    def stop_scan(self):
        self.stop_flag = True
        self.status_var.set('Abbruch angefordert…')

    @staticmethod
    def _fmt_size(n: int) -> str:
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        x = float(n)
        for u in units:
            if x < 1024 or u == units[-1]:
                return f'{x:.1f} {u}'
            x /= 1024
        return f'{x:.1f} TB'

    @staticmethod
    def _github_label(state: str) -> str:
        return {
            'IDENTICAL': '✅ identisch', 'LOCAL_ONLY': '⬆ nur lokal', 'DIVERGENT': '⚠ abweichend',
            'POSSIBLE_MATCH': '◐ wahrscheinlich', 'REPO_UNAVAILABLE': '⛔ Repo nicht erreichbar',
            'UNASSIGNED': '— nicht zugeordnet',
        }.get(state, '— noch nicht geprüft')

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        rows = classify_inventory(self.items)
        shown = 0
        by_path = {row['path']: row for row in rows}
        for i in self.items:
            row = by_path[i.path]
            relevant = i.duplicate_of or row['git_action'] in {'TO_GIT', 'REVIEW', 'NEVER'} or row['inventory_action'] == 'REVIEW' or i.score >= 40
            if self.only_kc.get() and not relevant:
                continue
            lamp = {'GREEN': '🟢', 'YELLOW': '🟡', 'BLUE': '🔵', 'WHITE': '⚪', 'RED': '🔴'}.get(i.status, '⚪')
            git_label = {'TO_GIT': 'Zu Git', 'REVIEW': 'Git prüfen', 'NO': 'Nein', 'NEVER': 'NIE Git'}.get(row['git_action'], row['git_action'])
            inv_label = {'KEEP': 'Behalten', 'KEEP_LOCAL': 'Lokal behalten', 'REVIEW': 'Prüfen', 'QUARANTINE_CANDIDATE': 'Quarantäne-Kandidat'}.get(row['inventory_action'], row['inventory_action'])
            github_state = self.github_by_path.get(i.path, {}).get('state', '')
            self.tree.insert('', END, values=(lamp, i.name, i.version_hint, i.category, self._fmt_size(i.size), i.modified_iso, git_label, self._github_label(github_state), inv_label, f"{row['confidence']} %", i.path))
            shown += 1
        summary = inventory_summary(self.items)['counts']
        done = len(self.items)
        if self.stop_flag and self.scan_total and done < self.scan_total:
            self._set_progress(done)
            self.status_var.set(f'Abgebrochen · {done:,} von {self.scan_total:,} Dateien erfasst · keine Quelldatei verändert')
        else:
            self.scan_total = max(self.scan_total, done)
            self._set_progress(self.scan_total)
            self.status_var.set(f"Fertig · {summary['files']:,} Dateien · {summary['to_git']:,} zu Git · {summary['quarantine_candidates']:,} sichere Dubletten · {shown:,} angezeigt")

    def selected_paths(self):
        return [self.tree.item(x, 'values')[-1] for x in self.tree.selection() if self.tree.item(x, 'values')]

    def _approved_quarantine_paths(self, paths):
        proposals = {x['path']: x for x in cleanup_candidates(self.items)}
        return [p for p in paths if proposals.get(p, {}).get('proposed_action') == 'QUARANTINE']

    def create_git_package(self):
        if not self.items:
            messagebox.showinfo('Git-Übergabepaket', 'Bitte zuerst eine Inventur durchführen.')
            return
        stamp = time.strftime('%Y%m%d-%H%M%S')
        p = filedialog.asksaveasfilename(title='Sicheres Git-Übergabepaket speichern', defaultextension='.zip', initialfile=f'PC-Backup-Vault_Git-Uebergabe_{stamp}.zip', filetypes=[('ZIP-Paket', '*.zip')])
        if not p:
            return
        self.status_var.set('Git-Übergabepaket wird erstellt · keine GitHub-Änderung…')
        try:
            result = create_git_handoff(self.items, p)
        except Exception as e:
            messagebox.showerror('Git-Übergabepaket', f'Paket konnte nicht erstellt werden:\n{e}')
            self.status_var.set('Git-Übergabepaket: Fehler')
            return
        self.status_var.set(f"Git-Übergabepaket fertig · {result['included']:,} Dateien · {result['excluded']:,} ausgeschlossen")
        messagebox.showinfo('Git-Übergabepaket', f"Paket sicher erstellt.\n\nEnthalten: {result['included']:,} Datei(en)\nAusgeschlossen: {result['excluded']:,}\n\nSecrets, Build-/Runtime-Dateien und erkannte Dubletten werden nicht übernommen.\nEs wurde NICHTS nach GitHub geschrieben und main wurde NICHT verändert.\n\n{p}")

    def start_github_compare(self):
        if not self.items:
            messagebox.showinfo('GitHub-Vergleich', 'Bitte zuerst eine Inventur durchführen.')
            return
        self._reset_recovery_state()
        self.status_var.set('GitHub-Vergleich läuft · ausschließlich Lesen · keine Änderung an GitHub…')
        threading.Thread(target=self._github_compare_worker, daemon=True).start()

    def _github_compare_worker(self):
        try:
            report = compare_inventory(self.items, verify_content=True)
            self.github_report = report
            self.github_by_path = {row['path']: row for row in report.get('items', [])}
            self.after(0, self._render_github_compare)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror('GitHub-Vergleich', f'Vergleich konnte nicht abgeschlossen werden:\n{e}'))
            self.after(0, lambda: self.status_var.set('GitHub-Vergleich: Fehler · keine Änderungen durchgeführt'))

    def _render_github_compare(self):
        self._render()
        counts = (self.github_report or {}).get('counts', {})
        identical, local_only = counts.get('IDENTICAL', 0), counts.get('LOCAL_ONLY', 0)
        divergent, possible = counts.get('DIVERGENT', 0), counts.get('POSSIBLE_MATCH', 0)
        unavailable, unassigned = counts.get('REPO_UNAVAILABLE', 0), counts.get('UNASSIGNED', 0)
        self.status_var.set(f'GitHub-Vergleich fertig · identisch {identical:,} · nur lokal {local_only:,} · abweichend {divergent:,} · wahrscheinlich {possible:,} · nicht erreichbar {unavailable:,} · nicht zugeordnet {unassigned:,}')
        messagebox.showinfo('GitHub-Vergleich · read-only', f'Identisch: {identical:,}\nNur lokal: {local_only:,}\nAbweichend: {divergent:,}\nWahrscheinlich identisch: {possible:,}\nRepo nicht erreichbar: {unavailable:,}\nNicht zugeordnet: {unassigned:,}\n\nEs wurde ausschließlich gelesen. Keine Datei wurde zu GitHub geschrieben, überschrieben oder gelöscht.')

    def create_recovery_preview(self):
        if not self.github_report:
            messagebox.showinfo('Recovery-Branch Vorschau', 'Bitte zuerst den read-only GitHub-Vergleich durchführen.')
            return
        preview = build_recovery_preview(self.items, self.github_report)
        self.recovery_preview = preview
        self.recovery_branch_result = None
        self.recovery_upload_plan = None
        candidates, blocked = preview.get('candidate_count', 0), preview.get('blocked_count', 0)
        groups = preview.get('groups', [])
        self.status_var.set(f'Recovery-Vorschau · {candidates:,} Kandidaten · {blocked:,} blockiert · {len(groups):,} Repository(s) · keine GitHub-Änderung')
        stamp = time.strftime('%Y%m%d-%H%M%S')
        p = filedialog.asksaveasfilename(title='Recovery-Branch Vorschau speichern', defaultextension='.json', initialfile=f'Recovery-Branch-Vorschau_{stamp}.json', filetypes=[('JSON', '*.json')])
        if p:
            export_recovery_preview(preview, p)
        branches = '\n'.join(f"{g['repo']}: {g['proposed_branch']} ({g['file_count']} Datei(en))" for g in groups[:8]) or 'Keine freigegebenen Recovery-Kandidaten.'
        messagebox.showinfo('Recovery-Branch Vorschau · read-only', f'Freigegebene Kandidaten: {candidates:,}\nBlockiert: {blocked:,}\nRepositories: {len(groups):,}\n\n{branches}\n\nEs wurde KEIN Branch erstellt und NICHTS nach GitHub geschrieben. main blieb unverändert.')

    def create_recovery_branches_ui(self):
        if not self.recovery_preview:
            messagebox.showinfo('Recovery-Branches', 'Bitte zuerst eine Recovery-Branch Vorschau erzeugen.')
            return
        errors = validate_recovery_preview(self.recovery_preview)
        if errors:
            messagebox.showerror('Recovery-Branches', 'Die Vorschau ist nicht mehr sicher freigabefähig:\n' + '\n'.join(errors[:8]))
            return
        groups = self.recovery_preview.get('groups', [])
        if not groups:
            messagebox.showinfo('Recovery-Branches', 'Keine freigegebenen Recovery-Kandidaten vorhanden.')
            return
        branches = '\n'.join(f"{g['repo']}\n  {g['proposed_branch']}" for g in groups[:8])
        if not messagebox.askyesno('Recovery-Branches wirklich anlegen?', f'Es werden ausschließlich neue Recovery-Branches angelegt:\n\n{branches}\n\nEs werden noch KEINE Dateien hochgeladen. main/master werden NICHT verändert.\n\nFortfahren?'):
            return
        self.status_var.set('Recovery-Branches werden angelegt · keine Datei wird hochgeladen…')
        try:
            result = create_recovery_branches(self.recovery_preview)
        except Exception as e:
            messagebox.showerror('Recovery-Branches', str(e))
            self.status_var.set('Recovery-Branches: Fehler')
            return
        self.recovery_branch_result = result
        self.recovery_upload_plan = None
        self.status_var.set(f"Recovery-Branches · {result.get('branch_refs_created', 0):,} angelegt · 0 Dateien geschrieben")
        messagebox.showinfo('Recovery-Branches', f"Angelegt: {result.get('branch_refs_created', 0):,}\nFehler: {len(result.get('failed', [])):,}\nDateien geschrieben: 0\nmain verändert: NEIN")

    def plan_recovery_upload(self):
        if not self.recovery_preview or not self.recovery_branch_result:
            messagebox.showinfo('Recovery-Upload', 'Bitte zuerst Vorschau erzeugen und Recovery-Branches erfolgreich anlegen.')
            return
        plan = build_recovery_upload_plan(self.recovery_preview, self.recovery_branch_result)
        self.recovery_upload_plan = plan
        ready, blocked = plan.get('ready_count', 0), plan.get('blocked_count', 0)
        preview_lines = '\n'.join(f"{r['repo']}:{r['branch']} → {r['repo_path']}" for r in plan.get('ready', [])[:10]) or 'Keine Datei freigegeben.'
        self.status_var.set(f'Recovery-Upload-Plan · {ready:,} bereit · {blocked:,} blockiert · noch kein Datei-Upload')
        messagebox.showinfo('Recovery-Upload-Plan · read-only', f'Bereit: {ready:,}\nBlockiert: {blocked:,}\n\n{preview_lines}\n\nEs wurde noch KEINE Datei hochgeladen.')

    def upload_recovery_files_ui(self):
        plan = self.recovery_upload_plan
        if not plan:
            messagebox.showinfo('Recovery-Upload', 'Bitte zuerst „Recovery-Upload planen…“ ausführen.')
            return
        ready, blocked = plan.get('ready_count', 0), plan.get('blocked_count', 0)
        if blocked:
            messagebox.showerror('Recovery-Upload blockiert', f'Der Plan enthält {blocked:,} blockierte Datei(en). Es wird nichts hochgeladen. Bitte Vorschau/Plan neu erzeugen.')
            return
        if not ready:
            messagebox.showinfo('Recovery-Upload', 'Keine Datei zum Hochladen freigegeben.')
            return
        targets = '\n'.join(f"{r['repo']}:{r['branch']} → {r['repo_path']}" for r in plan.get('ready', [])[:10])
        if not messagebox.askyesno('Dateien wirklich übertragen?', f'{ready:,} neue Datei(en) werden ausschließlich auf Recovery-Branches angelegt.\n\n{targets}\n\nVorhandene GitHub-Dateien werden NICHT überschrieben. main/master bleiben unverändert.\n\nJetzt übertragen?'):
            return
        self.status_var.set(f'Recovery-Upload läuft · {ready:,} Datei(en) · nur neue Dateien auf Recovery-Branches…')
        try:
            result = upload_recovery_files(plan, approved=True)
        except Exception as e:
            messagebox.showerror('Recovery-Upload', str(e))
            self.status_var.set('Recovery-Upload: Fehler')
            return
        uploaded, failed = result.get('uploaded_count', 0), len(result.get('failed', []))
        self.status_var.set(f'Recovery-Upload fertig · {uploaded:,} hochgeladen · {failed:,} Fehler · main unverändert')
        messagebox.showinfo('Recovery-Upload', f'Hochgeladen: {uploaded:,}\nFehler: {failed:,}\nÜberschrieben: 0\nmain/master verändert: NEIN')

    def export_github_report(self):
        if not self.github_report:
            messagebox.showinfo('GitHub-Vergleich', 'Noch kein GitHub-Vergleich vorhanden.')
            return
        stamp = time.strftime('%Y%m%d-%H%M%S')
        p = filedialog.asksaveasfilename(title='GitHub-Vergleichsbericht speichern', defaultextension='.json', initialfile=f'GitHub-Vergleich_{stamp}.json', filetypes=[('JSON', '*.json')])
        if not p:
            return
        export_compare_report(self.github_report, p)
        self.status_var.set(f'GitHub-Vergleichsbericht gespeichert: {p}')

    def quarantine_selected(self):
        paths = self.selected_paths()
        if not paths:
            messagebox.showinfo('Projekt-Finder', 'Bitte zuerst Dateien markieren.')
            return
        approved = self._approved_quarantine_paths(paths)
        blocked = len(paths) - len(approved)
        if not approved:
            messagebox.showwarning('Sichere Bereinigung', 'Keine markierte Datei ist als bit-identische SHA-256-Dublette freigegeben. Es wird nichts verschoben.')
            return
        msg = f'{len(approved)} bit-identische Dublette(n) werden in eine wiederherstellbare Quarantäne verschoben.\n{blocked} andere Datei(en) bleiben unverändert.\n\nEs wird NICHT endgültig gelöscht. Fortfahren?'
        if not messagebox.askyesno('Sichere Bereinigung', msg):
            return
        manifest = quarantine(approved, self.quarantine_root, reason='user-approved-safe-duplicate')
        messagebox.showinfo('Sichere Bereinigung', f'{len(manifest)} Datei(en) wurden reversibel quarantänisiert.\nAlle anderen Dateien blieben unverändert.')
        self.status_var.set(f'Quarantäne: {len(manifest)} sichere Dublette(n) · {blocked} nicht verändert')

    def export(self, kind: str):
        if not self.items:
            messagebox.showinfo('Projekt-Finder', 'Noch keine Inventur vorhanden.')
            return
        ext = '.json' if kind == 'json' else '.csv'
        p = filedialog.asksaveasfilename(defaultextension=ext, filetypes=[('JSON', '*.json')] if kind == 'json' else [('CSV', '*.csv')])
        if not p:
            return
        (export_inventory_json if kind == 'json' else export_inventory_csv)(self.items, p)
        self.status_var.set(f'Inventur gespeichert: {p}')

    def copy_summary(self):
        if not self.items:
            return
        s = inventory_summary(self.items)
        c, z = s['counts'], s['sizes']
        text = ('PC Backup Vault · Produktive Inventur\n' f"Dateien: {c['files']:,}\nGesamtgröße: {self._fmt_size(z['total'])}\n" f"Zu Git: {c['to_git']:,}\nGit prüfen: {c['git_review']:,}\n" f"Lokal behalten: {c['keep_local']:,}\nWeitere Prüffälle: {c['review']:,}\n" f"Niemals Git (Secret-Verdacht): {c['never_git']:,}\n" f"Sichere SHA-256-Dubletten: {c['quarantine_candidates']:,}\n" f"Potentiell durch Quarantäne freigebbar: {self._fmt_size(z['quarantine_candidates'])}\n" 'Hinweis: Keine endgültige Löschung erfolgt automatisch.')
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set('Inventur-Zusammenfassung kopiert')