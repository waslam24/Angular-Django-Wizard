#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Angular → Django Wizard (UI refaite : scrolls, chemins en haut + auto-hide, JSON config)
- GUI Tkinter, stdlib only
- Modes: Installation | Mise à jour
- Edits idempotents: settings.py, urls.py (import re_path garanti, SPA fallback excluant static/media)
- index.html: injecte {% load static %} + réécrit assets en {% static '...' %} (ne touche pas <meta> ni <base href="/">)
- Copie assets dist/browser -> static/
- Backups centralisés .bak par session: ../<projet>_backups/<timestamp>/
- Diff preview + apply
- JSON: charger/sauver chemins
- Section chemins visible au début puis repliable (auto-hide après confirmation)

Auteur: ChatGPT
"""

import os
import re
import sys
import json
import time
import shutil
import subprocess
import difflib
from pathlib import Path
from html.parser import HTMLParser

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------- Persistance ----------
DEFAULT_PROFILE = str(Path.home() / ".angular_django_wizard.json")

# ---------- Utils ----------
EXCLUDE_PREFIXES = ("http://", "https://", "//", "data:", "mailto:", "tel:")
DJ_STATIC_TAG = "{% static '"
DJ_STATIC_TAG_END = "' %}"

def nowstamp():
    return time.strftime("%Y%m%d_%H%M%S")

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore") if p and p.exists() else ""

def write_text(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

def backup_file(p: Path) -> Path | None:
    """Fallback local (rarement utilisé)"""
    if not p or not p.exists():
        return None
    bak = p.with_suffix(p.suffix + f".bak_{nowstamp()}")
    shutil.copy2(p, bak)
    return bak

def copytree_merge(src: Path, dst: Path, ignore_names=None):
    src, dst = Path(src), Path(dst)
    if not src.exists():
        return
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        if ignore_names and rel == Path("."):
            dirs[:]  = [d for d in dirs  if d not in ignore_names]
            files[:] = [f for f in files if f not in ignore_names]
        target = dst / rel
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(Path(root) / f, target / f)

def short(p: Path | str) -> str:
    p = str(p)
    home = str(Path.home())
    return p.replace(home, "~") if p.startswith(home) else p

# ---------- HTML Rewriter ----------
def is_local_asset(url: str) -> bool:
    if not url:
        return False
    u = url.strip()
    # ne pas réécrire la racine ou chemins “vides”
    if u in ("/", "./"):
        return False
    if any(u.startswith(p) for p in EXCLUDE_PREFIXES):
        return False
    if u.startswith("{%") or u.startswith("{{"):
        return False
    if u.startswith("#"):
        return False
    return True

def to_django_static(url: str) -> str:
    u = url.strip()
    u = re.sub(r"^/+", "", u).replace("\\", "/")
    return f"{DJ_STATIC_TAG}{u}{DJ_STATIC_TAG_END}"

class StaticRewriter(HTMLParser):
    # on ne cible PAS "content" (ne pas toucher <meta content="...">)
    TARGET_ATTRS = {"src", "href", "poster"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []

    def handle_decl(self, decl): self.out.append(f"<!{decl}>")
    def handle_startendtag(self, tag, attrs): self.out.append(self._rebuild(tag, attrs, True))
    def handle_starttag(self, tag, attrs): self.out.append(self._rebuild(tag, attrs, False))
    def handle_endtag(self, tag): self.out.append(f"</{tag}>")
    def handle_data(self, data): self.out.append(data)
    def handle_comment(self, data): self.out.append(f"<!--{data}-->")
    def handle_entityref(self, name): self.out.append(f"&{name};")
    def handle_charref(self, name): self.out.append(f"&#{name};")

    def _rebuild(self, tag, attrs, self_closing):
        t = tag.lower()

        # 1) ne jamais modifier <meta ...>
        if t == "meta":
            attr_str = "".join([f' {k}' if v is None else f' {k}="{v}"' for k, v in attrs])
            return f"<{tag}{attr_str}{'/' if self_closing else ''}>"

        rebuilt = []
        for k, v in attrs:
            if v is None:
                rebuilt.append((k, v))
                continue

            # 2) ne jamais toucher <base href="/">
            if t == "base" and k.lower() == "href":
                rebuilt.append((k, v))
                continue

            # 3) réécrire seulement les attrs ciblés
            if k.lower() in self.TARGET_ATTRS and is_local_asset(v):
                v = to_django_static(v)

            rebuilt.append((k, v))

        attr_str = "".join([f' {k}' if v is None else f' {k}="{v}"' for k, v in rebuilt])
        return f"<{tag}{attr_str}{'/' if self_closing else ''}>"

    def transform(self, html_text: str) -> str:
        self.feed(html_text); self.close()
        return "".join(self.out)

# ---------- Edits idempotents ----------
SETTINGS_HINT = """# --- Angular/Django wizard settings ---
# Assurez-vous que 'django.contrib.staticfiles' est dans INSTALLED_APPS.
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [ BASE_DIR / "static" ]

# WhiteNoise (optionnel en prod):
# MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
"""

def ensure_base_dir_and_static(content: str) -> str:
    txt = content or ""
    if re.search(r"^\s*BASE_DIR\s*=", txt, re.M) is None:
        txt = 'from pathlib import Path\nBASE_DIR = Path(__file__).resolve().parent.parent\n' + txt
    if re.search(r"^\s*STATIC_URL\s*=", txt, re.M) is None:
        txt += '\n' + SETTINGS_HINT
    else:
        if re.search(r"^\s*STATIC_ROOT\s*=", txt, re.M) is None:
            txt += '\nSTATIC_ROOT = BASE_DIR / "staticfiles"\n'
        if re.search(r"^\s*STATICFILES_DIRS\s*=", txt, re.M) is None:
            txt += '\nSTATICFILES_DIRS = [ BASE_DIR / "static" ]\n'
    return txt

def ensure_templates_dir_decl(content: str) -> str:
    """
    Ajoute BASE_DIR / "templates" dans TEMPLATES[0]['DIRS'] de façon idempotente,
    gère 'DIRS'/"DIRS" et formats multi-lignes.
    """
    txt = content
    if re.search(r"^\s*BASE_DIR\s*=", txt, re.M) is None:
        txt = 'from pathlib import Path\nBASE_DIR = Path(__file__).resolve().parent.parent\n' + txt

    def repl_dirs(m):
        arr = m.group(1)
        if re.search(r'BASE_DIR\s*/\s*["\']templates["\']', arr):
            return m.group(0)
        if re.match(r"^\s*$", arr):
            new_arr = ' BASE_DIR / "templates" '
        else:
            arr_stripped = arr.strip()
            if arr_stripped.endswith(","):
                new_arr = arr + ' BASE_DIR / "templates" '
            else:
                new_arr = arr + ', BASE_DIR / "templates" '
        return m.group(0).replace(arr, new_arr)

    txt = re.sub(r"""['"]DIRS['"]\s*:\s*\[\s*(.*?)\s*\]""", repl_dirs, txt, flags=re.S)
    return txt

def idempotent_add_settings(settings_text: str) -> str:
    txt = ensure_base_dir_and_static(settings_text or "")
    txt = ensure_templates_dir_decl(txt)
    return txt

def idempotent_add_urls(urls_text: str) -> str:
    """
    - Garantit imports path/re_path + TemplateView + staticfiles_urlpatterns
    - Ajoute racine + fallback SPA en excluant /static/ et /media/
    - Ajoute urlpatterns += staticfiles_urlpatterns() (DEV)
    """
    txt = urls_text or ""

    # 1) Import path, re_path
    if re.search(r"^from\s+django\.urls\s+import\s+.+$", txt, flags=re.M):
        def _inject_re_path(m):
            items = [i.strip() for i in m.group(1).split(",")]
            if "path" not in items:
                items.insert(0, "path")
            if "re_path" not in items:
                items.append("re_path")
            seen, ordered = set(), []
            for i in items:
                if i and i not in seen:
                    ordered.append(i); seen.add(i)
            return f"from django.urls import {', '.join(ordered)}"
        txt = re.sub(r"^from\s+django\.urls\s+import\s+(.+)$", _inject_re_path, txt, count=1, flags=re.M)
    else:
        txt = "from django.urls import path, re_path\n" + txt

    # 2) Import TemplateView
    if "from django.views.generic import TemplateView" not in txt:
        txt = "from django.views.generic import TemplateView\n" + txt

    # 3) Import staticfiles_urlpatterns (dev)
    if "from django.contrib.staticfiles.urls import staticfiles_urlpatterns" not in txt:
        txt = "from django.contrib.staticfiles.urls import staticfiles_urlpatterns\n" + txt

    # 4) S'assurer d'avoir urlpatterns
    if re.search(r"^\s*urlpatterns\s*=", txt, flags=re.M) is None:
        txt += "\nurlpatterns = []\n"

    # 5) Ajouter (idempotent) racine et fallback excluant /static/ et /media/
    has_root = re.search(r'TemplateView\.as_view\(\s*template_name\s*=\s*["\']index\.html["\']\s*\)', txt)
    has_re_fallback = re.search(
        r're_path\(\s*r["\']\^\(\?!static/|media/\)\(\?:\.\*\)/\?\$["\']\s*,\s*TemplateView\.as_view\(\s*template_name\s*=\s*["\']index\.html["\']\s*\)\s*\)',
        txt
    )

    if not (has_root and has_re_fallback):
        def _inject(m):
            head = m.group(0)
            lines = []
            if not has_root:
                lines.append('    path("", TemplateView.as_view(template_name="index.html")),')
            if not has_re_fallback:
                # Negative lookahead pour NE PAS matcher /static/ ni /media/
                lines.append('    re_path(r"^(?!static/|media/)(?:.*)/?$", TemplateView.as_view(template_name="index.html")),')
            return head + ("\n" + "\n".join(lines) if lines else "")
        txt = re.sub(r"urlpatterns\s*=\s*\[", _inject, txt, count=1)

    # 6) Ajouter (idempotent) les patterns statics pour le DEV
    if re.search(r"urlpatterns\s*\+=\s*staticfiles_urlpatterns\(\s*\)", txt) is None:
        txt += "\nurlpatterns += staticfiles_urlpatterns()\n"

    return txt

# ---------- Déploiement ----------
def transform_index_html(dist_browser: Path) -> str:
    """
    Transforme index.html → injecte {% static %} et ajoute {% load static %} s'il manque.
    """
    src_html = read_text(dist_browser / "index.html")
    if not src_html:
        raise RuntimeError("index.html introuvable dans le dossier sélectionné.")
    out_html = StaticRewriter().transform(src_html)
    if "{% load static %}" not in out_html:
        if out_html.lstrip().upper().startswith("<!DOCTYPE"):
            lines = out_html.splitlines(True)
            inserted = False
            for i, line in enumerate(lines):
                if "<!DOCTYPE" in line or "<!doctype" in line:
                    lines.insert(i+1, "{% load static %}\n"); inserted = True; break
            if not inserted:
                lines.insert(0, "{% load static %}\n")
            out_html = "".join(lines)
        else:
            out_html = "{% load static %}\n" + out_html
    return out_html

def deploy_front(dist_browser: Path, templates_dir: Path, static_dir: Path, log_fn, backup_fn=None):
    out_html = transform_index_html(dist_browser)
    templates_dir.mkdir(parents=True, exist_ok=True)
    dest_index = templates_dir / "index.html"
    if dest_index.exists():
        if backup_fn:
            bak = backup_fn(dest_index)
            log_fn(f"Backup: {short(bak)}")
        else:
            bak = backup_file(dest_index)
            log_fn(f"Backup: {short(bak)}")
    write_text(dest_index, out_html)
    log_fn(f"index.html transformé → {short(dest_index)}")
    static_dir.mkdir(parents=True, exist_ok=True)
    copytree_merge(dist_browser, static_dir, ignore_names={"index.html"})
    log_fn(f"Assets copiés vers {short(static_dir)}")

# ---------- Widgets helper ----------
class ScrollText(tk.Frame):
    """Text + scrollbar verticale, simple."""
    def __init__(self, master, **kwargs):
        super().__init__(master)
        self.text = tk.Text(self, **kwargs)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def insert(self, *a, **k): self.text.insert(*a, **k)
    def delete(self, *a, **k): self.text.delete(*a, **k)
    def see(self, *a, **k): self.text.see(*a, **k)
    def get(self, *a, **k): return self.text.get(*a, **k)
    def widget(self): return self.text

class CollapsibleSection(ttk.Frame):
    """Section repliable : header avec bouton, body scrollable optionnel."""
    def __init__(self, master, title="Section", initially_open=True):
        super().__init__(master)
        self._open = initially_open
        self.header = ttk.Frame(self)
        self.header.pack(fill="x")
        self.btn = ttk.Button(self.header, text=f"{title} ⯆" if self._open else f"{title} ⯈", command=self.toggle)
        self.btn.pack(side="left", padx=(0,6))
        self.body = ttk.Frame(self)
        if self._open:
            self.body.pack(fill="x")

    def toggle(self):
        self._open = not self._open
        self.btn.configure(text=self.btn.cget("text").replace("⯆","⯈") if not self._open else self.btn.cget("text").replace("⯈","⯆"))
        if self._open:
            self.body.pack(fill="x")
        else:
            self.body.forget()

    def open(self):
        if not self._open:
            self.toggle()

    def close(self):
        if self._open:
            self.toggle()

# ---------- UI principale ----------
class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Angular → Django Wizard")
        self.geometry("1120x760")

        # Mode
        self.mode = tk.StringVar(value="install")

        # State (paths)
        self.project_root = tk.StringVar()
        self.manage_py    = tk.StringVar()
        self.dist_folder  = tk.StringVar()
        self.templates_dir= tk.StringVar()
        self.static_dir   = tk.StringVar()

        # Refs UI
        self.logs = None
        self.settings_diff = None
        self.urls_diff = None
        self.collect_out = None
        self.paths_section = None
        self.status_var = tk.StringVar(value="Prêt.")

        # Backups session
        self.run_stamp = nowstamp()
        self.backup_dir = None  # set après confirmation des chemins

        self._build_menu()
        self._build_layout()

        # Charger profil local (si dispo) et décider visibilité chemins
        self._load_state(DEFAULT_PROFILE, quiet=True)
        self._auto_paths_visibility()

    # ----- Menu -----
    def _build_menu(self):
        menubar = tk.Menu(self); self.config(menu=menubar)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Quitter", command=self.destroy)
        menubar.add_cascade(label="Fichier", menu=m_file)

        m_cfg = tk.Menu(menubar, tearoff=0)
        m_cfg.add_command(label="Charger depuis JSON…", command=self.menu_load_json)
        m_cfg.add_command(label="Sauver vers JSON…", command=self.menu_save_json)
        m_cfg.add_separator()
        m_cfg.add_command(label="Basculer Chemins (afficher/masquer)", command=self.toggle_paths)
        menubar.add_cascade(label="Config", menu=m_cfg)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="À propos", command=lambda: messagebox.showinfo(
            "À propos",
            "Angular → Django Wizard\nUI compacte, chemins auto-hide, JSON config.\nStdlib only."
        ))
        menubar.add_cascade(label="Aide", menu=m_help)

    # ----- Layout -----
    def _build_layout(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # topbar
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        ttk.Label(bar, text="Mode :", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Radiobutton(bar, text="Installation", variable=self.mode, value="install").pack(side="left", padx=8)
        ttk.Radiobutton(bar, text="Mise à jour", variable=self.mode, value="update").pack(side="left", padx=8)
        ttk.Button(bar, text="Chemins ⯈/⯆", command=self.toggle_paths).pack(side="right")

        # Chemins (collapsible)
        self.paths_section = CollapsibleSection(root, title="Chemins", initially_open=True)
        self.paths_section.pack(fill="x", pady=(8,0))
        self._build_paths_body(self.paths_section.body)

        # Notebook
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, pady=(8,0))

        # settings
        p1 = ttk.Frame(nb, padding=8)
        nb.add(p1, text="1) settings.py")
        self._build_settings_page(p1)

        # urls
        p2 = ttk.Frame(nb, padding=8)
        nb.add(p2, text="2) urls.py")
        self._build_urls_page(p2)

        # deploy
        p3 = ttk.Frame(nb, padding=8)
        nb.add(p3, text="3) Déploiement Angular")
        self._build_deploy_page(p3)

        # collectstatic
        p4 = ttk.Frame(nb, padding=8)
        nb.add(p4, text="4) collectstatic (optionnel)")
        self._build_collectstatic_page(p4)

        # logs
        p5 = ttk.Frame(nb, padding=8)
        nb.add(p5, text="Logs")
        self._build_logs_page(p5)

        # status bar
        status = ttk.Frame(root)
        status.pack(fill="x", pady=(6,0))
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(fill="x")

    def _build_paths_body(self, parent):
        def row(lbl, var, pick_cmd, hint=None):
            fr = ttk.Frame(parent); fr.pack(fill="x", pady=4)
            ttk.Label(fr, text=lbl).pack(anchor="w")
            ed = ttk.Entry(fr, textvariable=var)
            ed.pack(side="left", fill="x", expand=True, padx=(0,8))
            ttk.Button(fr, text="Parcourir…", command=pick_cmd).pack(side="left")
            if hint:
                ttk.Label(parent, text=hint).pack(anchor="w", padx=(4,0))

        row("Projet Django (sélectionne un fichier DANS le dossier) :", self.project_root, self.pick_project_root)
        row("manage.py :", self.manage_py, self.pick_manage)
        row("dist Angular (sélectionne un fichier DANS dist/<app>/browser) :", self.dist_folder, self.pick_dist,
            hint="Astuce: choisis index.html pour être sûr d’être au bon endroit.")
        row("templates/ :", self.templates_dir, lambda: self.pick_dir_into_var(self.templates_dir))
        row("static/ :", self.static_dir, lambda: self.pick_dir_into_var(self.static_dir))

        act = ttk.Frame(parent); act.pack(fill="x", pady=(6,0))
        ttk.Button(act, text="Charger JSON…", command=self.menu_load_json).pack(side="left")
        ttk.Button(act, text="Sauver JSON…", command=self.menu_save_json).pack(side="left", padx=6)
        ttk.Button(act, text="Confirmer les chemins", command=self.confirm_paths).pack(side="right")

    # ----- Pages -----
    def _build_settings_page(self, parent):
        ttk.Label(parent, text="Prévisualiser et appliquer les modifications idempotentes à settings.py").pack(anchor="w")
        controls = ttk.Frame(parent); controls.pack(fill="x", pady=6)
        ttk.Button(controls, text="Prévisualiser diff", command=self.preview_settings_diff).pack(side="left")
        ttk.Button(controls, text="Appliquer", command=self.apply_settings).pack(side="left", padx=6)
        st = ScrollText(parent, height=22, wrap="none"); st.pack(fill="both", expand=True)
        self.settings_diff = st

    def _build_urls_page(self, parent):
        ttk.Label(parent, text="Prévisualiser et appliquer les modifications idempotentes à urls.py").pack(anchor="w")
        controls = ttk.Frame(parent); controls.pack(fill="x", pady=6)
        ttk.Button(controls, text="Prévisualiser diff", command=self.preview_urls_diff).pack(side="left")
        ttk.Button(controls, text="Appliquer", command=self.apply_urls).pack(side="left", padx=6)
        st = ScrollText(parent, height=22, wrap="none"); st.pack(fill="both", expand=True)
        self.urls_diff = st

    def _build_deploy_page(self, parent):
        ttk.Label(parent, text="Transformer index.html et copier les assets vers static/").pack(anchor="w")
        ttk.Button(parent, text="Exécuter le déploiement", command=self.do_deploy).pack(anchor="w", pady=6)
        ttk.Label(parent, text="Assure-toi d’avoir buildé Angular (ng build --configuration production).").pack(anchor="w")

    def _build_collectstatic_page(self, parent):
        ttk.Label(parent, text="Lancer python manage.py collectstatic --noinput").pack(anchor="w")
        ttk.Button(parent, text="Lancer collectstatic", command=self.do_collectstatic).pack(anchor="w", pady=6)
        st = ScrollText(parent, height=22, wrap="word"); st.pack(fill="both", expand=True)
        self.collect_out = st

    def _build_logs_page(self, parent):
        ttk.Label(parent, text="Journal d’exécution").pack(anchor="w")
        st = ScrollText(parent, height=24, wrap="word"); st.pack(fill="both", expand=True)
        self.logs = st

    # ----- Status & logs -----
    def set_status(self, msg: str):
        self.status_var.set(msg)
        self.update_idletasks()

    def log(self, msg: str):
        if self.logs:
            self.logs.insert("end", msg + "\n")
            self.logs.see("end")
        self.set_status(msg)

    # ----- Backups centralisés -----
    def backup(self, file_path: Path) -> Path | None:
        """
        Sauvegarde file_path dans le dossier centralisé de la session:
        <parent>/<projectname>_backups/<timestamp>/<relative_to_project_root>.bak
        """
        try:
            if not file_path or not file_path.exists():
                return None
            if not self.backup_dir:
                proj_root = Path(self.project_root.get() or "").resolve()
                backup_root = proj_root.parent / f"{proj_root.name}_backups"
                self.backup_dir = (backup_root / self.run_stamp)
                self.backup_dir.mkdir(parents=True, exist_ok=True)

            proj_root = Path(self.project_root.get()).resolve()
            try:
                rel = file_path.resolve().relative_to(proj_root)
            except Exception:
                rel = Path(file_path.name)

            dest = (self.backup_dir / rel).with_suffix(rel.suffix + ".bak")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)
            return dest
        except Exception:
            return None

    # ----- JSON -----
    def _load_state(self, path: str, quiet=False):
        p = Path(path)
        if not p.exists():
            if not quiet:
                messagebox.showwarning("Info", f"Aucun fichier trouvé: {short(path)}")
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self.project_root.set(data.get("project_root",""))
            self.dist_folder.set(data.get("dist_folder",""))
            self.manage_py.set(data.get("manage_py",""))
            self.static_dir.set(data.get("static_dir",""))
            self.templates_dir.set(data.get("templates_dir",""))
            if not quiet:
                messagebox.showinfo("OK", f"Config chargée depuis {short(path)}")
            self.log(f"Config chargée: {short(path)}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de charger {short(path)}:\n{e}")
            self.set_status("Erreur de chargement JSON.")

    def _save_state(self, path: str):
        data = {
            "project_root": self.project_root.get(),
            "dist_folder": self.dist_folder.get(),
            "manage_py": self.manage_py.get(),
            "static_dir": self.static_dir.get(),
            "templates_dir": self.templates_dir.get()
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("OK", f"Config sauvegardée dans {short(path)}")
        self.log(f"Config sauvegardée: {short(path)}")

    def menu_load_json(self):
        p = filedialog.askopenfilename(title="Charger config JSON",
                                       filetypes=[("JSON","*.json"),("Tous fichiers","*.*")])
        if p:
            self._load_state(p)
            self._auto_paths_visibility()

    def menu_save_json(self):
        p = filedialog.asksaveasfilename(title="Sauver config JSON",
                                         defaultextension=".json",
                                         filetypes=[("JSON","*.json")])
        if p:
            self._save_state(p)

    # ----- Chemins -----
    def _paths_complete(self) -> bool:
        try:
            pr = Path(self.project_root.get() or "")
            mp = Path(self.manage_py.get() or "")
            df = Path(self.dist_folder.get() or "")
            ok = pr.exists() and mp.exists() and df.exists()
            return ok
        except Exception:
            return False

    def _auto_paths_visibility(self):
        # Si profil local chargeable et chemins plausibles -> replier
        if self._paths_complete():
            self.paths_section.close()
            self.set_status("Chemins OK (profil).")
        else:
            self.paths_section.open()
            self.set_status("Veuillez renseigner les chemins puis confirmer.")

    def confirm_paths(self):
        # corrections & validations douces
        try:
            # project_root à partir d'un fichier choisi
            pr = Path(self.project_root.get() or "")
            if pr.is_file():
                pr = pr.parent
            self.project_root.set(str(pr))

            # dist_folder à partir d'un fichier choisi
            df = Path(self.dist_folder.get() or "")
            if df.is_file():
                df = df.parent
            self.dist_folder.set(str(df))

            # vérifier manage.py
            mp = Path(self.manage_py.get() or (pr / "manage.py"))
            if mp.exists():
                self.manage_py.set(str(mp))

            # templates/static
            tdir = Path(self.templates_dir.get() or (pr / "templates"))
            sdir = Path(self.static_dir.get() or (pr / "static"))
            tdir.mkdir(parents=True, exist_ok=True)
            sdir.mkdir(parents=True, exist_ok=True)
            self.templates_dir.set(str(tdir))
            self.static_dir.set(str(sdir))

            # checks essentiels
            problems = []
            if not mp.exists():
                problems.append("manage.py introuvable.")
            if not (df / "index.html").exists():
                problems.append("dist/browser/index.html introuvable.")
            if problems:
                messagebox.showwarning("Chemins à vérifier", "\n".join(problems))
                self.set_status("Chemins incomplets. Corrige puis reconfirme.")
                return

            # auto-save profil local
            try:
                self._save_state(DEFAULT_PROFILE)
            except Exception:
                pass

            # Préparer le dossier de backups centralisé: <parent>/<projectname>_backups/<timestamp>/
            proj_root = Path(self.project_root.get())
            backup_root = proj_root.parent / f"{proj_root.name}_backups"
            session_dir = backup_root / self.run_stamp
            session_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir = session_dir
            self.log(f"Backups: {short(self.backup_dir)}")

            # auto-hide
            self.paths_section.close()
            self.set_status("Chemins confirmés.")
            self.log("Chemins confirmés (section repliée).")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            self.set_status("Erreur lors de la confirmation des chemins.")

    def toggle_paths(self):
        self.paths_section.toggle()

    # Selectors
    def pick_project_root(self):
        p = filedialog.askopenfilename(title="Choisir un fichier DANS le dossier du projet Django",
                                       filetypes=[("Tous fichiers", "*.*")])
        if p:
            folder = str(Path(p).parent)
            self.project_root.set(folder)
            mp = Path(folder) / "manage.py"
            if mp.exists():
                self.manage_py.set(str(mp))

    def pick_manage(self):
        p = filedialog.askopenfilename(title="Sélectionner manage.py",
                                       filetypes=[("Python", "*.py"), ("Tous fichiers", "*.*")])
        if p:
            if Path(p).name != "manage.py":
                messagebox.showwarning("Attention", "Ce fichier n'est pas 'manage.py'.")
            self.manage_py.set(p)

    def pick_dist(self):
        p = filedialog.askopenfilename(title="Choisir un fichier DANS dist/<app>/browser (ex: index.html)",
                                       filetypes=[("Tous fichiers", "*.*")])
        if p:
            self.dist_folder.set(str(Path(p).parent))

    def pick_dir_into_var(self, var: tk.StringVar):
        d = filedialog.askdirectory(title="Choisir un dossier")
        if d:
            var.set(d)

    # ----- settings.py -----
    def project_settings_py(self) -> Path | None:
        root = Path(self.project_root.get() or "")
        if not root.exists():
            return None
        for p in root.glob("*/settings.py"):
            return p
        cand = root / "project" / "settings.py"
        return cand if cand.exists() else None

    def preview_settings_diff(self):
        p = self.project_settings_py()
        if not p:
            messagebox.showerror("Erreur", "settings.py introuvable dans le projet Django.")
            return
        current = read_text(p).splitlines(keepends=True)
        proposed = idempotent_add_settings(read_text(p)).splitlines(keepends=True)
        diff = difflib.unified_diff(current, proposed, fromfile=short(p), tofile=f"{short(p)} (proposé)")
        self.settings_diff.delete("1.0", "end")
        self.settings_diff.insert("1.0", "".join(diff) or "Aucune modification requise.")
        self.settings_diff.see("end")

    def apply_settings(self):
        p = self.project_settings_py()
        if not p:
            messagebox.showerror("Erreur", "settings.py introuvable.")
            return
        src = read_text(p)
        new = idempotent_add_settings(src)
        if src == new:
            messagebox.showinfo("OK", "Aucune modification à appliquer.")
            self.set_status("settings.py déjà conforme.")
            return
        bak = self.backup(p)
        self.log(f"Backup settings.py → {short(bak)}")
        write_text(p, new)
        messagebox.showinfo("OK", f"settings.py mis à jour: {short(p)}")
        self.set_status("settings.py mis à jour.")

    # ----- urls.py -----
    def project_urls_py(self) -> Path | None:
        root = Path(self.project_root.get() or "")
        if not root.exists():
            return None
        for p in root.glob("*/urls.py"):
            return p
        cand = root / "project" / "urls.py"
        return cand if cand.exists() else None

    def preview_urls_diff(self):
        p = self.project_urls_py()
        if not p:
            current_text = "from django.urls import path\n\nurlpatterns = []\n"
            current = current_text.splitlines(keepends=True)
            proposed = idempotent_add_urls(current_text).splitlines(keepends=True)
            diff = difflib.unified_diff(current, proposed, fromfile="(nouveau urls.py)", tofile="(proposé)")
        else:
            current = read_text(p).splitlines(keepends=True)
            proposed = idempotent_add_urls(read_text(p)).splitlines(keepends=True)
            diff = difflib.unified_diff(current, proposed, fromfile=short(p), tofile=f"{short(p)} (proposé)")
        self.urls_diff.delete("1.0", "end")
        self.urls_diff.insert("1.0", "".join(diff) or "Aucune modification requise.")
        self.urls_diff.see("end")

    def apply_urls(self):
        p = self.project_urls_py()
        if not p:
            root = Path(self.project_root.get() or "")
            if not root.exists():
                messagebox.showerror("Erreur", "Projet Django invalide.")
                return
            proj_dir = None
            for cand in root.iterdir():
                if cand.is_dir() and (cand / "settings.py").exists():
                    proj_dir = cand
                    break
            if not proj_dir:
                proj_dir = root / "project"
                proj_dir.mkdir(parents=True, exist_ok=True)
            p = proj_dir / "urls.py"
            current = "from django.urls import path\n\nurlpatterns = []\n"
            proposed = idempotent_add_urls(current)
            write_text(p, proposed)
            messagebox.showinfo("OK", f"urls.py créé et mis à jour: {short(p)}")
            self.log(f"Créé urls.py → {short(p)}")
            self.set_status("urls.py créé.")
            return

        src = read_text(p)
        new = idempotent_add_urls(src)
        if src == new:
            messagebox.showinfo("OK", "Aucune modification à appliquer.")
            self.set_status("urls.py déjà conforme.")
            return
        bak = self.backup(p)
        self.log(f"Backup urls.py → {short(bak)}")
        write_text(p, new)
        messagebox.showinfo("OK", f"urls.py mis à jour: {short(p)}")
        self.set_status("urls.py mis à jour.")

    # ----- Déploiement -----
    def do_deploy(self):
        try:
            dist = Path(self.dist_folder.get() or "")
            if dist.is_file():
                dist = dist.parent
            if not dist.exists() or not (dist / "index.html").exists():
                raise RuntimeError("Le dossier dist sélectionné n'est pas valide (index.html introuvable).")
            tpls = Path(self.templates_dir.get() or "")
            sttc = Path(self.static_dir.get() or "")
            if not tpls:
                root = Path(self.project_root.get() or "")
                tpls = root / "templates"; self.templates_dir.set(str(tpls))
            if not sttc:
                root = Path(self.project_root.get() or "")
                sttc = root / "static"; self.static_dir.set(str(sttc))

            deploy_front(dist, tpls, sttc, self.log, backup_fn=self.backup)
            messagebox.showinfo("OK", "Déploiement frontend terminé.")
            self.set_status("Déploiement OK.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            self.set_status("Échec du déploiement.")
            self.log(f"ERREUR: {e}")

    # ----- collectstatic -----
    def do_collectstatic(self):
        manage = Path(self.manage_py.get() or "")
        if not manage.exists():
            messagebox.showerror("Erreur", "manage.py introuvable.")
            self.set_status("manage.py manquant.")
            return
        cmd = [sys.executable, str(manage), "collectstatic", "--noinput"]
        self.collect_out.insert("end", f"$ {' '.join(cmd)}\n"); self.collect_out.see("end")
        proc = subprocess.run(cmd, cwd=manage.parent, capture_output=True, text=True)
        self.collect_out.insert("end", proc.stdout + "\n" + proc.stderr); self.collect_out.see("end")
        if proc.returncode == 0:
            messagebox.showinfo("OK", "collectstatic terminé.")
            self.set_status("collectstatic OK.")
            self.log("collectstatic OK")
        else:
            messagebox.showerror("Erreur", "collectstatic a échoué.")
            self.set_status("collectstatic KO.")
            self.log("collectstatic a échoué")

# ---------- main ----------
def main():
    app = Wizard()
    app.mainloop()

if __name__ == "__main__":
    main()
