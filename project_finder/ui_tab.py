from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, BooleanVar, StringVar, filedialog, messagebox, ttk

from .scanner import cleanup_candidates, export_csv, export_json, quarantine, scan


class ProjectFinderTab(ttk.Frame):
    """Embeddable Project-Finder tab; scanning is read-only until explicit quarantine approval."""

    def __init__(self, master, *, quarantine_root: str | None = None):
        super().__init__(master)
        self.roots: list[str] = []
        self.items = []
        self.stop_flag = False
        self.quarantine_root = quarantine_root or str(Path.home() / 'PC-Backup-Vault-Quarantaene')
        self.status_var = StringVar(value='Bereit · Es wird noch nichts verändert.')
        self.only_kc = BooleanVar(value=True)
        self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill=X, padx=12, pady=(12, 6))
        ttk.Label(top, text='Festplatten-Analyse / Projekt-Finder', font=('Segoe UI', 13, 'bold')).pack(side=LEFT)
        ttk.Label(top, textvariable=self.status_var).pack(side=RIGHT)
        source = ttk.LabelFrame(self, text='1 · Suchbereiche'); source.pack(fill=X, padx=12, pady=6)
        btns = ttk.Frame(source); btns.pack(fill=X, padx=8, pady=8)
        ttk.Button(btns, text='Ordner hinzufügen…', command=self.add_folder).pack(side=LEFT, padx=(0, 6))
        ttk.Button(btns, text='Laufwerk/Ordner entfernen', command=self.remove_selected_root).pack(side=LEFT)
        self.root_list = ttk.Treeview(source, columns=('path',), show='headings', height=4)
        self.root_list.heading('path', text='Ausgewählte Laufwerke / Verzeichnisse'); self.root_list.column('path', width=900, anchor='w')
        self.root_list.pack(fill=X, padx=8, pady=(0, 8))
        scanbox = ttk.LabelFrame(self, text='2 · Analyse'); scanbox.pack(fill=X, padx=12, pady=6)
        bar = ttk.Frame(scanbox); bar.pack(fill=X, padx=8, pady=8)
        ttk.Button(bar, text='Analyse starten', command=self.start_scan).pack(side=LEFT, padx=(0, 6))
        ttk.Button(bar, text='Abbrechen', command=self.stop_scan).pack(side=LEFT, padx=(0, 12))
        ttk.Checkbutton(bar, text='Nur relevante KC-/Entwicklungsfunde hervorheben', variable=self.only_kc).pack(side=LEFT)
        results = ttk.LabelFrame(self, text='3 · Ergebnisse und sichere Bereinigung'); results.pack(fill=BOTH, expand=True, padx=12, pady=6)
        cols = ('ampel','name','version','typ','groesse','datum','aktion','pfad')
        self.tree = ttk.Treeview(results, columns=cols, show='headings', selectmode='extended')
        titles = {'ampel':'Status','name':'Datei','version':'Version','typ':'Typ','groesse':'Größe','datum':'Geändert','aktion':'Vorschlag','pfad':'Pfad'}
        widths = {'ampel':65,'name':220,'version':90,'typ':110,'groesse':90,'datum':135,'aktion':135,'pfad':520}
        for c in cols: self.tree.heading(c,text=titles[c]); self.tree.column(c,width=widths[c],anchor='w')
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=8)
        actions = ttk.Frame(self); actions.pack(fill=X, padx=12, pady=(0,12))
        ttk.Button(actions, text='Zusammenfassung kopieren', command=self.copy_summary).pack(side=LEFT, padx=(0,6))
        ttk.Button(actions, text='JSON für ChatGPT', command=lambda:self.export('json')).pack(side=LEFT, padx=(0,6))
        ttk.Button(actions, text='CSV exportieren', command=lambda:self.export('csv')).pack(side=LEFT, padx=(0,16))
        ttk.Button(actions, text='Markierte sicher in Quarantäne verschieben…', command=self.quarantine_selected).pack(side=RIGHT)

    def add_folder(self):
        p = filedialog.askdirectory(title='Laufwerk oder Verzeichnis für Analyse wählen')
        if p and p not in self.roots: self.roots.append(p); self.root_list.insert('',END,values=(p,))

    def remove_selected_root(self):
        for iid in self.root_list.selection():
            vals=self.root_list.item(iid,'values')
            if vals and vals[0] in self.roots:self.roots.remove(vals[0])
            self.root_list.delete(iid)

    def start_scan(self):
        if not self.roots: messagebox.showinfo('Projekt-Finder','Bitte zuerst mindestens ein Laufwerk oder Verzeichnis auswählen.'); return
        self.stop_flag=False; self.items=[]; self.tree.delete(*self.tree.get_children()); self.status_var.set('Analyse läuft · Nur Lesen')
        threading.Thread(target=self._scan_worker,daemon=True).start()

    def _scan_worker(self):
        try:
            self.items=scan(self.roots,progress=lambda n,p:self.after(0,lambda:self.status_var.set(f'Analyse läuft · {n:,} Dateien · {p}')),stop_requested=lambda:self.stop_flag)
            self.after(0,self._render)
        except Exception as e:
            self.after(0,lambda:messagebox.showerror('Projekt-Finder',str(e))); self.after(0,lambda:self.status_var.set('Fehler bei Analyse'))

    def stop_scan(self): self.stop_flag=True; self.status_var.set('Abbruch angefordert…')

    @staticmethod
    def _fmt_size(n:int)->str:
        units=['B','KB','MB','GB','TB']; x=float(n)
        for u in units:
            if x<1024 or u==units[-1]: return f'{x:.1f} {u}'
            x/=1024

    def _render(self):
        proposals={x['path']:x for x in cleanup_candidates(self.items)}; shown=0
        for i in self.items:
            if self.only_kc.get() and i.score<40 and not i.duplicate_of: continue
            p=proposals[i.path]; lamp={'GREEN':'🟢','YELLOW':'🟡','BLUE':'🔵','WHITE':'⚪','RED':'🔴'}.get(i.status,'⚪')
            action={'KEEP':'Behalten','REVIEW':'Prüfen','QUARANTINE':'Quarantäne'}.get(p['proposed_action'],p['proposed_action'])
            self.tree.insert('',END,values=(lamp,i.name,i.version_hint,i.category,self._fmt_size(i.size),i.modified_iso,action,i.path)); shown+=1
        self.status_var.set(f'Fertig · {len(self.items):,} Dateien erfasst · {shown:,} relevante Funde angezeigt')

    def selected_paths(self): return [self.tree.item(x,'values')[-1] for x in self.tree.selection() if self.tree.item(x,'values')]

    def _approved_quarantine_paths(self, paths):
        proposals={x['path']:x for x in cleanup_candidates(self.items)}
        return [p for p in paths if proposals.get(p,{}).get('proposed_action') == 'QUARANTINE']

    def quarantine_selected(self):
        paths=self.selected_paths()
        if not paths: messagebox.showinfo('Projekt-Finder','Bitte zuerst Dateien markieren.'); return
        approved=self._approved_quarantine_paths(paths)
        blocked=len(paths)-len(approved)
        if not approved:
            messagebox.showwarning('Sichere Bereinigung','Die Auswahl enthält keine als sichere Dublette vorgeschlagene Datei. REVIEW/KEEP wird nicht automatisch verschoben.'); return
        msg=(f'{len(approved)} als sichere Dublette vorgeschlagene Datei(en) werden in eine wiederherstellbare Quarantäne verschoben.\n'
             f'{blocked} REVIEW/KEEP-Datei(en) bleiben unverändert.\n\nEs wird NICHT endgültig gelöscht. Fortfahren?')
        if not messagebox.askyesno('Sichere Bereinigung',msg): return
        manifest=quarantine(approved,self.quarantine_root,reason='user-approved-safe-duplicate')
        messagebox.showinfo('Sichere Bereinigung',f'{len(manifest)} Dateien wurden in Quarantäne verschoben.\nManifest mit Originalpfad und Hash wurde gespeichert.\nREVIEW/KEEP blieb unverändert.')
        self.status_var.set(f'Quarantäne: {len(manifest)} sichere Dublette(n) · {blocked} nicht verändert')

    def export(self,kind:str):
        if not self.items: messagebox.showinfo('Projekt-Finder','Noch keine Analyse vorhanden.'); return
        ext='.json' if kind=='json' else '.csv'; p=filedialog.asksaveasfilename(defaultextension=ext,filetypes=[('JSON','*.json')] if kind=='json' else [('CSV','*.csv')])
        if not p:return
        (export_json if kind=='json' else export_csv)(self.items,p); self.status_var.set(f'Export gespeichert: {p}')

    def copy_summary(self):
        if not self.items:return
        proposals=cleanup_candidates(self.items); dups=sum(1 for x in proposals if x['proposed_action']=='QUARANTINE'); reviews=sum(1 for x in proposals if x['proposed_action']=='REVIEW')
        total=sum(x['size'] for x in proposals); reclaim=sum(x['size'] for x in proposals if x['proposed_action']=='QUARANTINE')
        text=(f'PC Backup Vault Projekt-Finder\nDateien: {len(proposals):,}\nGesamtgröße erfasst: {self._fmt_size(total)}\nSichere Dubletten-Kandidaten: {dups:,}\nWeitere Prüfkandidaten: {reviews:,}\nPotentiell sofort rückgewinnbar durch Dubletten-Quarantäne: {self._fmt_size(reclaim)}')
        self.clipboard_clear(); self.clipboard_append(text); self.status_var.set('Zusammenfassung kopiert')
