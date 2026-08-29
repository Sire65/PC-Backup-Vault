from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, BooleanVar, StringVar, filedialog, messagebox, ttk

from .decision_engine import classify_inventory, export_inventory_csv, export_inventory_json, inventory_summary
from .scanner import cleanup_candidates, quarantine, scan


class ProjectFinderTab(ttk.Frame):
    """Produktiver Inventurmodus. Scan bleibt read-only; Quarantäne nur nach expliziter Freigabe."""

    def __init__(self, master, *, quarantine_root: str | None = None):
        super().__init__(master)
        self.roots: list[str] = []
        self.items = []
        self.stop_flag = False
        self.quarantine_root = quarantine_root or str(Path.home() / 'PC-Backup-Vault-Quarantaene')
        self.status_var = StringVar(value='Bereit · Inventur verändert keine Quelldateien.')
        self.only_kc = BooleanVar(value=True)
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill=X, padx=12, pady=(12, 6))
        ttk.Label(top, text='Festplatten-Inventur / Projekt-Finder', font=('Segoe UI', 13, 'bold')).pack(side=LEFT)
        ttk.Label(top, textvariable=self.status_var).pack(side=RIGHT)

        source = ttk.LabelFrame(self, text='1 · Suchbereiche'); source.pack(fill=X, padx=12, pady=6)
        btns = ttk.Frame(source); btns.pack(fill=X, padx=8, pady=8)
        ttk.Button(btns, text='Ordner hinzufügen…', command=self.add_folder).pack(side=LEFT, padx=(0, 6))
        ttk.Button(btns, text='Laufwerk/Ordner entfernen', command=self.remove_selected_root).pack(side=LEFT)
        self.root_list = ttk.Treeview(source, columns=('path',), show='headings', height=4)
        self.root_list.heading('path', text='Ausgewählte Laufwerke / Verzeichnisse')
        self.root_list.column('path', width=900, anchor='w')
        self.root_list.pack(fill=X, padx=8, pady=(0, 8))

        scanbox = ttk.LabelFrame(self, text='2 · Read-only Inventur'); scanbox.pack(fill=X, padx=12, pady=6)
        bar = ttk.Frame(scanbox); bar.pack(fill=X, padx=8, pady=8)
        ttk.Button(bar, text='Inventur starten', command=self.start_scan).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bar, text='Abbrechen', command=self.stop_scan).pack(side=LEFT, padx=(0, 12))
        ttk.Checkbutton(bar, text='Nur relevante Projekt-/Git-/Prüffunde anzeigen', variable=self.only_kc).pack(side=LEFT)

        results = ttk.LabelFrame(self, text='3 · Entscheidung: Git / Behalten / Prüfen / Quarantäne'); results.pack(fill=BOTH, expand=True, padx=12, pady=6)
        cols = ('ampel','name','version','typ','groesse','datum','git','inventur','sicherheit','pfad')
        self.tree = ttk.Treeview(results, columns=cols, show='headings', selectmode='extended')
        titles = {'ampel':'Status','name':'Datei','version':'Version','typ':'Typ','groesse':'Größe','datum':'Geändert','git':'Git','inventur':'Inventur','sicherheit':'Sicherheit','pfad':'Pfad'}
        widths = {'ampel':65,'name':200,'version':85,'typ':105,'groesse':85,'datum':130,'git':95,'inventur':145,'sicherheit':80,'pfad':480}
        for c in cols:
            self.tree.heading(c,text=titles[c]); self.tree.column(c,width=widths[c],anchor='w')
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=8)

        actions = ttk.Frame(self); actions.pack(fill=X, padx=12, pady=(0,12))
        ttk.Button(actions, text='Zusammenfassung kopieren', command=self.copy_summary).pack(side=LEFT, padx=(0,6))
        ttk.Button(actions, text='Inventur JSON', command=lambda:self.export('json')).pack(side=LEFT, padx=(0,6))
        ttk.Button(actions, text='Inventur CSV', command=lambda:self.export('csv')).pack(side=LEFT, padx=(0,16))
        ttk.Button(actions, text='Sichere Dubletten in Quarantäne…', command=self.quarantine_selected).pack(side=RIGHT)

    def add_folder(self):
        p = filedialog.askdirectory(title='Laufwerk oder Verzeichnis für Inventur wählen')
        if p and p not in self.roots:
            self.roots.append(p); self.root_list.insert('',END,values=(p,))

    def remove_selected_root(self):
        for iid in self.root_list.selection():
            vals=self.root_list.item(iid,'values')
            if vals and vals[0] in self.roots: self.roots.remove(vals[0])
            self.root_list.delete(iid)

    def start_scan(self):
        if not self.roots:
            messagebox.showinfo('Projekt-Finder','Bitte zuerst mindestens ein Laufwerk oder Verzeichnis auswählen.'); return
        self.stop_flag=False; self.items=[]; self.tree.delete(*self.tree.get_children())
        self.status_var.set('Inventur läuft · Nur Lesen · SHA-256 bis 64 MB')
        threading.Thread(target=self._scan_worker,daemon=True).start()

    def _scan_worker(self):
        try:
            self.items=scan(
                self.roots,
                hash_only_interesting=False,
                progress=lambda n,p:self.after(0,lambda:self.status_var.set(f'Inventur läuft · {n:,} Dateien · {p}')),
                stop_requested=lambda:self.stop_flag,
            )
            self.after(0,self._render)
        except Exception as e:
            self.after(0,lambda:messagebox.showerror('Projekt-Finder',str(e)))
            self.after(0,lambda:self.status_var.set('Fehler bei Inventur'))

    def stop_scan(self):
        self.stop_flag=True; self.status_var.set('Abbruch angefordert…')

    @staticmethod
    def _fmt_size(n:int)->str:
        units=['B','KB','MB','GB','TB']; x=float(n)
        for u in units:
            if x<1024 or u==units[-1]: return f'{x:.1f} {u}'
            x/=1024

    def _render(self):
        rows=classify_inventory(self.items); shown=0
        by_path={row['path']: row for row in rows}
        for i in self.items:
            row=by_path[i.path]
            relevant = i.duplicate_of or row['git_action'] in {'TO_GIT','REVIEW','NEVER'} or row['inventory_action'] == 'REVIEW' or i.score >= 40
            if self.only_kc.get() and not relevant: continue
            lamp={'GREEN':'🟢','YELLOW':'🟡','BLUE':'🔵','WHITE':'⚪','RED':'🔴'}.get(i.status,'⚪')
            git_label={'TO_GIT':'Zu Git','REVIEW':'Git prüfen','NO':'Nein','NEVER':'NIE Git'}.get(row['git_action'],row['git_action'])
            inv_label={'KEEP':'Behalten','KEEP_LOCAL':'Lokal behalten','REVIEW':'Prüfen','QUARANTINE_CANDIDATE':'Quarantäne-Kandidat'}.get(row['inventory_action'],row['inventory_action'])
            self.tree.insert('',END,values=(lamp,i.name,i.version_hint,i.category,self._fmt_size(i.size),i.modified_iso,git_label,inv_label,f"{row['confidence']} %",i.path))
            shown+=1
        summary=inventory_summary(self.items)['counts']
        self.status_var.set(f"Fertig · {summary['files']:,} Dateien · {summary['to_git']:,} zu Git · {summary['quarantine_candidates']:,} sichere Dubletten · {shown:,} angezeigt")

    def selected_paths(self):
        return [self.tree.item(x,'values')[-1] for x in self.tree.selection() if self.tree.item(x,'values')]

    def _approved_quarantine_paths(self, paths):
        proposals={x['path']:x for x in cleanup_candidates(self.items)}
        return [p for p in paths if proposals.get(p,{}).get('proposed_action') == 'QUARANTINE']

    def quarantine_selected(self):
        paths=self.selected_paths()
        if not paths:
            messagebox.showinfo('Projekt-Finder','Bitte zuerst Dateien markieren.'); return
        approved=self._approved_quarantine_paths(paths); blocked=len(paths)-len(approved)
        if not approved:
            messagebox.showwarning('Sichere Bereinigung','Keine markierte Datei ist als bit-identische SHA-256-Dublette freigegeben. Es wird nichts verschoben.'); return
        msg=(f'{len(approved)} bit-identische Dublette(n) werden in eine wiederherstellbare Quarantäne verschoben.\n'
             f'{blocked} andere Datei(en) bleiben unverändert.\n\nEs wird NICHT endgültig gelöscht. Fortfahren?')
        if not messagebox.askyesno('Sichere Bereinigung',msg): return
        manifest=quarantine(approved,self.quarantine_root,reason='user-approved-safe-duplicate')
        messagebox.showinfo('Sichere Bereinigung',f'{len(manifest)} Datei(en) wurden reversibel quarantänisiert.\nAlle anderen Dateien blieben unverändert.')
        self.status_var.set(f'Quarantäne: {len(manifest)} sichere Dublette(n) · {blocked} nicht verändert')

    def export(self,kind:str):
        if not self.items:
            messagebox.showinfo('Projekt-Finder','Noch keine Inventur vorhanden.'); return
        ext='.json' if kind=='json' else '.csv'
        p=filedialog.asksaveasfilename(defaultextension=ext,filetypes=[('JSON','*.json')] if kind=='json' else [('CSV','*.csv')])
        if not p:return
        (export_inventory_json if kind=='json' else export_inventory_csv)(self.items,p)
        self.status_var.set(f'Inventur gespeichert: {p}')

    def copy_summary(self):
        if not self.items:return
        s=inventory_summary(self.items); c=s['counts']; z=s['sizes']
        text=(
            'PC Backup Vault · Produktive Inventur\n'
            f"Dateien: {c['files']:,}\nGesamtgröße: {self._fmt_size(z['total'])}\n"
            f"Zu Git: {c['to_git']:,}\nGit prüfen: {c['git_review']:,}\n"
            f"Lokal behalten: {c['keep_local']:,}\nWeitere Prüffälle: {c['review']:,}\n"
            f"Niemals Git (Secret-Verdacht): {c['never_git']:,}\n"
            f"Sichere SHA-256-Dubletten: {c['quarantine_candidates']:,}\n"
            f"Potentiell durch Quarantäne freigebbar: {self._fmt_size(z['quarantine_candidates'])}\n"
            'Hinweis: Keine endgültige Löschung erfolgt automatisch.'
        )
        self.clipboard_clear(); self.clipboard_append(text); self.status_var.set('Inventur-Zusammenfassung kopiert')
