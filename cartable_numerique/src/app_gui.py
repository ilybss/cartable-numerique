import os
import re
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from storage import (
    import_document,
    list_documents,
    open_document,
    delete_document,
    create_folder,
    list_folders,
    move_document_to_folder,
    create_note,
    list_notes,
    read_note,
    edit_note,
    delete_note,
)

from ollama_client import (
    generate_qcm_quiz,          # peut renvoyer JSON OU texte
    generate_cv_structured,     # renvoie un dict structuré
    interview_question,
    interview_feedback,
)

from cv_pdf import export_cv_pdf


# =========================
# Scrollable Frame
# =========================
class ScrollableFrame(ttk.Frame):
    """Frame scrollable verticalement (quand ça dépasse en bas)."""
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Molette
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")

    def _on_inner_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass


# =========================
# QCM parsing helpers
# =========================
def _extract_json_obj(text: str):
    """Essaie de récupérer un JSON même si l'IA a ajouté du texte autour."""
    if not text:
        return None
    t = text.strip()

    # 1) direct
    try:
        return json.loads(t)
    except Exception:
        pass

    # 2) premier {...}
    m = re.search(r"\{[\s\S]*\}", t)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    # 3) première [...]
    m = re.search(r"\[[\s\S]*\]", t)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    return None


def _normalize_qcm(data):
    """Normalise différents formats JSON vers: {"questions":[{question, options, answer, explanation}]}"""
    if data is None:
        return None

    if isinstance(data, list):
        data = {"questions": data}

    if not isinstance(data, dict):
        return None

    if "questions" not in data and "quiz" in data:
        data["questions"] = data["quiz"]

    qs = data.get("questions")
    if not isinstance(qs, list) or not qs:
        return None

    out = []
    for q in qs:
        if not isinstance(q, dict):
            continue
        question = (q.get("question") or q.get("q") or "").strip()
        opts = q.get("options") or q.get("choices") or q.get("answers") or []

        # options dict {"A": "..."} -> liste A) ...
        if isinstance(opts, dict):
            ordered = []
            for k in ["A", "B", "C", "D", "E", "F"]:
                if k in opts:
                    ordered.append(f"{k}) {str(opts[k]).strip()}")
            opts = ordered

        if isinstance(opts, list):
            opts = [str(x).strip() for x in opts if str(x).strip()]

        ans = q.get("answer") or q.get("correct") or q.get("correct_answer")
        exp = (q.get("explanation") or q.get("exp") or "").strip()

        if not question or len(opts) < 2:
            continue

        out.append({
            "question": question,
            "options": opts,
            "answer": ans,
            "explanation": exp
        })

    if not out:
        return None

    return {"questions": out}


def _parse_qcm_from_text(raw: str):
    """
    Fallback: parse un format texte du style :
    Q1: ...
    A) ...
    B) ...
    C) ...
    D) ...
    ANSWER: B
    EXPLANATION: ...
    """
    if not raw:
        return None

    t = raw.strip()

    # Standardiser séparateurs
    t = t.replace("\r\n", "\n")

    # Découper sur Q1:, Q2: ... (ou "Q1 -", "Q1)")
    parts = re.split(r"\n(?=Q\d+\s*[:\-\)])", "\n" + t)
    parts = [p.strip() for p in parts if p.strip()]

    questions = []
    for block in parts:
        # Qn: question...
        m = re.match(r"Q(\d+)\s*[:\-\)]\s*(.*)", block, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        rest = m.group(2).strip()

        # récupérer ANSWER / EXPLANATION si présents
        ans_letter = None
        exp = ""

        m_ans = re.search(r"(?:ANSWER|R[ÉE]PONSE)\s*[:\-]\s*([A-F])\b", rest, flags=re.IGNORECASE)
        if m_ans:
            ans_letter = m_ans.group(1).upper()

        m_exp = re.search(r"(?:EXPLANATION|EXPLICATION)\s*[:\-]\s*([\s\S]*)", rest, flags=re.IGNORECASE)
        if m_exp:
            exp = m_exp.group(1).strip()

        # enlever les sections ANSWER/EXPLANATION du "rest"
        rest_clean = re.split(r"(?:ANSWER|R[ÉE]PONSE)\s*[:\-]", rest, flags=re.IGNORECASE)[0]
        rest_clean = re.split(r"(?:EXPLANATION|EXPLICATION)\s*[:\-]", rest_clean, flags=re.IGNORECASE)[0]

        # options A) ... B) ...
        # on veut capturer question (avant la première option)
        opt_matches = list(re.finditer(r"^\s*([A-F])[\)\.\:\-]\s*(.+)$", rest_clean, flags=re.IGNORECASE | re.MULTILINE))
        if len(opt_matches) < 2:
            # parfois options sur une seule ligne "A) ... B) ..." -> on tente un split simple
            opt_inline = re.findall(r"([A-F])[\)\.\:\-]\s*([^A-F]+?)(?=(?:\s+[A-F][\)\.\:\-])|$)", rest_clean, flags=re.IGNORECASE)
            if len(opt_inline) >= 2:
                question_text = re.split(r"[A-F][\)\.\:\-]\s*", rest_clean, 1, flags=re.IGNORECASE)[0].strip()
                options = [f"{k.upper()}) {v.strip()}" for k, v in opt_inline]
            else:
                continue
        else:
            first_opt_pos = opt_matches[0].start()
            question_text = rest_clean[:first_opt_pos].strip()
            options = []
            for mm in opt_matches:
                options.append(f"{mm.group(1).upper()}) {mm.group(2).strip()}")

        if not question_text:
            question_text = "(Question)"

        questions.append({
            "question": question_text,
            "options": options,
            "answer": ans_letter,
            "explanation": exp
        })

    if not questions:
        return None

    return {"questions": questions}


def _answer_to_index(answer, options):
    """Convertit answer en index 0..n-1 (A/B/C..., ou 0/1/2..., ou '2'...)."""
    if answer is None:
        return None

    n = len(options)

    if isinstance(answer, int):
        return answer if 0 <= answer < n else None

    s = str(answer).strip()
    if not s:
        return None

    m = re.search(r"\b([A-F])\b", s.upper())
    if m:
        idx = ord(m.group(1)) - ord("A")
        return idx if 0 <= idx < n else None

    if s.isdigit():
        val = int(s)
        if 0 <= val < n:
            return val
        if 1 <= val <= n:
            return val - 1

    return None


# =========================
# App
# =========================
class CartableApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cartable Numérique")
        self.geometry("1180x720")
        self.minsize(1050, 650)

        # Couleurs
        self.bg = "#EAF2FF"
        self.panel = "#D7E8FF"
        self.white = "#FFFFFF"
        self.text = "#0F172A"
        self.muted = "#365A9C"
        self.border = "#B7C9E8"

        self.configure(bg=self.bg)
        self._setup_styles()

        # Header
        header = tk.Frame(self, bg=self.panel, bd=0)
        header.pack(fill="x")

        tk.Label(
            header,
            text="Cartable Numérique",
            bg=self.panel,
            fg=self.text,
            font=("Segoe UI", 22, "bold"),
        ).pack(side="left", padx=18, pady=12)

        tk.Label(
            header,
            text="Cloud • Notes • QCM IA • Carrière",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI", 11),
        ).pack(side="left", padx=12, pady=12)

        container = tk.Frame(self, bg=self.bg)
        container.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=12)

        self.tab_home = ttk.Frame(self.notebook)
        self.tab_cloud = ttk.Frame(self.notebook)
        self.tab_notes = ttk.Frame(self.notebook)
        self.tab_qcm = ttk.Frame(self.notebook)
        self.tab_career = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_home, text="🏠 Accueil")
        self.notebook.add(self.tab_cloud, text="📁 Cloud")
        self.notebook.add(self.tab_notes, text="📝 Notes")
        self.notebook.add(self.tab_qcm, text="🧠 QCM IA")
        self.notebook.add(self.tab_career, text="💼 Carrière IA")

        # State
        self.cv_ai = None
        self.qcm_data = None
        self.qcm_index = 0
        self.qcm_user_answers = {}

        # Build
        self._build_home_tab()
        self._build_cloud_tab()
        self._build_notes_tab()
        self._build_qcm_tab()
        self._build_career_tab()

        # Load
        self.refresh_cloud()
        self.refresh_folders()
        self.refresh_notes()

        # Notes shortcut
        self.bind_all("<Control-s>", lambda e: self.gui_update_note())

        # Autosave notes
        self._autosave_interval_ms = 20000
        self.after(self._autosave_interval_ms, self._autosave_notes)

    # =========================
    # Styles
    # =========================
    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=self.bg)
        style.configure("Panel.TFrame", background=self.panel)
        style.configure("Card.TFrame", background=self.white)

        style.configure("TLabel", background=self.bg, foreground=self.text, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.bg, foreground=self.text, font=("Segoe UI", 14, "bold"))
        style.configure("Muted.TLabel", background=self.bg, foreground=self.muted, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.white, foreground=self.text, font=("Segoe UI", 10))

        style.configure("TNotebook", background=self.bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8))

        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(10, 6))

        style.configure("TEntry", padding=(6, 6))
        style.configure("TCombobox", padding=(6, 6))
        style.configure("TLabelframe", background=self.bg)
        style.configure("TLabelframe.Label", background=self.bg, foreground=self.text, font=("Segoe UI", 10, "bold"))

    # =========================
    # HOME
    # =========================
    def _build_home_tab(self):
        root = ttk.Frame(self.tab_home, style="Panel.TFrame", padding=18)
        root.pack(fill="both", expand=True, padx=10, pady=10)

        banner = tk.Frame(root, bg=self.panel)
        banner.pack(fill="x", pady=(0, 14))

        tk.Label(
            banner,
            text="Bienvenue 👋",
            bg=self.panel,
            fg=self.text,
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", padx=12, pady=(10, 0))

        tk.Label(
            banner,
            text="Choisis un module pour commencer.",
            bg=self.panel,
            fg=self.muted,
            font=("Segoe UI", 11)
        ).pack(anchor="w", padx=12, pady=(2, 10))

        grid = tk.Frame(root, bg=self.panel)
        grid.pack(fill="both", expand=True)

        def card(parent, title, desc, emoji, tab):
            f = tk.Frame(parent, bg=self.white, bd=1, relief="solid")
            f.pack_propagate(False)

            head = tk.Label(f, text=f"{emoji}  {title}", bg=self.white, fg=self.text,
                            font=("Segoe UI", 12, "bold"))
            head.pack(anchor="w", padx=12, pady=(12, 4))

            body = tk.Label(f, text=desc, bg=self.white, fg=self.muted,
                            font=("Segoe UI", 10), justify="left", wraplength=360)
            body.pack(anchor="w", padx=12)

            btn = ttk.Button(
                f,
                text="Ouvrir",
                style="Primary.TButton",
                command=lambda: self.notebook.select(tab)
            )
            btn.pack(anchor="e", padx=12, pady=12)

            def go(_=None):
                self.notebook.select(tab)

            for w in (f, head, body):
                w.bind("<Button-1>", go)

            return f

        grid.columnconfigure(0, weight=1, uniform="a")
        grid.columnconfigure(1, weight=1, uniform="a")
        grid.rowconfigure(0, weight=1, uniform="b")
        grid.rowconfigure(1, weight=1, uniform="b")

        c1 = card(grid, "Cloud", "Importer, ouvrir, supprimer des fichiers et les ranger dans des dossiers.",
                  "📁", self.tab_cloud)
        c2 = card(grid, "Notes", "Créer/modifier des notes (autosave + Ctrl+S).",
                  "📝", self.tab_notes)
        c3 = card(grid, "QCM IA", "Générer un quiz depuis un fichier texte et répondre + corrigé.",
                  "🧠", self.tab_qcm)
        c4 = card(grid, "Carrière IA", "CV (IA + export PDF) et coach d’entretien (questions + feedback).",
                  "💼", self.tab_career)

        c1.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        c2.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        c3.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        c4.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)

        for cf in (c1, c2, c3, c4):
            cf.config(width=420, height=160)

    # =========================
    # CLOUD
    # =========================
    def _build_cloud_tab(self):
        wrap = ScrollableFrame(self.tab_cloud)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        pad = ttk.Frame(root, padding=12, style="Panel.TFrame")
        pad.pack(fill="both", expand=True)

        left = ttk.Frame(pad, padding=10, style="Card.TFrame")
        right = ttk.Frame(pad, padding=10, style="Card.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right.pack(side="right", fill="y")

        ttk.Label(left, text="Documents", style="Title.TLabel").pack(anchor="w")
        self.docs_list = tk.Listbox(left, height=18)
        self.docs_list.pack(fill="both", expand=True, pady=8)

        btn_row = ttk.Frame(left, style="Card.TFrame")
        btn_row.pack(fill="x", pady=4)

        ttk.Button(btn_row, text="Importer…", command=self.gui_import_document).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Ouvrir", command=self.gui_open_document).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Supprimer", command=self.gui_delete_document).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Rafraîchir", command=self.refresh_cloud).pack(side="left", padx=4)

        ttk.Label(right, text="Dossiers", style="Title.TLabel").pack(anchor="w")

        self.folders_combo = ttk.Combobox(right, state="readonly", width=28, values=[])
        self.folders_combo.pack(pady=6)

        folder_create_row = ttk.Frame(right, style="Card.TFrame")
        folder_create_row.pack(fill="x", pady=6)
        self.new_folder_var = tk.StringVar()
        ttk.Entry(folder_create_row, textvariable=self.new_folder_var, width=20).pack(side="left", padx=4)
        ttk.Button(folder_create_row, text="Créer", command=self.gui_create_folder).pack(side="left", padx=4)

        ttk.Button(right, text="Ranger doc → dossier", command=self.gui_move_document).pack(fill="x", pady=6)
        ttk.Button(right, text="Rafraîchir dossiers", command=self.refresh_folders).pack(fill="x", pady=6)

        ttk.Label(
            right,
            text="Astuce : sélectionne un document à gauche,\npuis choisis un dossier.",
            style="Muted.TLabel",
            justify="left",
        ).pack(pady=10, anchor="w")

    def refresh_cloud(self):
        try:
            docs = list_documents()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lister les documents:\n{e}")
            return

        self.docs_list.delete(0, tk.END)
        for d in docs:
            name = d.get("name", "")
            folder = d.get("folder")
            self.docs_list.insert(tk.END, f"{name}   [{folder}]" if folder else name)

    def refresh_folders(self):
        try:
            folders = list_folders()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lister les dossiers:\n{e}")
            return
        self.folders_combo["values"] = folders
        if folders:
            self.folders_combo.current(0)

    def _get_selected_doc_name(self):
        sel = self.docs_list.curselection()
        if not sel:
            return None
        item = self.docs_list.get(sel[0])
        return item.split("   [", 1)[0].strip()

    def gui_import_document(self):
        path = filedialog.askopenfilename(title="Choisir un fichier à importer")
        if not path:
            return
        try:
            import_document(path)
            self.refresh_cloud()
            messagebox.showinfo("OK", "Document importé.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_open_document(self):
        name = self._get_selected_doc_name()
        if not name:
            messagebox.showwarning("Attention", "Sélectionne un document.")
            return
        try:
            open_document(name)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_delete_document(self):
        name = self._get_selected_doc_name()
        if not name:
            messagebox.showwarning("Attention", "Sélectionne un document.")
            return
        if not messagebox.askyesno("Confirmer", f"Supprimer '{name}' ?"):
            return
        try:
            delete_document(name)
            self.refresh_cloud()
            messagebox.showinfo("OK", "Document supprimé.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_create_folder(self):
        folder = self.new_folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Attention", "Entre un nom de dossier.")
            return
        try:
            create_folder(folder)
            self.new_folder_var.set("")
            self.refresh_folders()
            messagebox.showinfo("OK", "Dossier créé.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_move_document(self):
        name = self._get_selected_doc_name()
        if not name:
            messagebox.showwarning("Attention", "Sélectionne un document.")
            return
        folder = self.folders_combo.get().strip()
        if not folder:
            messagebox.showwarning("Attention", "Choisis un dossier.")
            return
        try:
            move_document_to_folder(name, folder)
            self.refresh_cloud()
            messagebox.showinfo("OK", f"Document rangé dans '{folder}'.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    # =========================
    # NOTES
    # =========================
    def _build_notes_tab(self):
        wrap = ScrollableFrame(self.tab_notes)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        pad = ttk.Frame(root, padding=12, style="Panel.TFrame")
        pad.pack(fill="both", expand=True)

        left = ttk.Frame(pad, padding=10, style="Card.TFrame")
        right = ttk.Frame(pad, padding=10, style="Card.TFrame")
        left.pack(side="left", fill="y", padx=(0, 10))
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Mes notes", style="Title.TLabel").pack(anchor="w")
        self.notes_list = tk.Listbox(left, width=34, height=20)
        self.notes_list.pack(fill="y", expand=False, pady=8)
        self.notes_list.bind("<<ListboxSelect>>", lambda e: self.gui_open_note())

        top = ttk.Frame(right, style="Card.TFrame")
        top.pack(fill="x")

        ttk.Label(top, text="Titre :", style="Card.TLabel").pack(side="left", padx=(0, 6))
        self.note_title_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.note_title_var, width=40).pack(side="left", padx=6)

        ttk.Button(top, text="Créer", command=self.gui_create_note).pack(side="left", padx=4)
        ttk.Button(top, text="Enregistrer (Ctrl+S)", command=self.gui_update_note).pack(side="left", padx=4)
        ttk.Button(top, text="Supprimer", command=self.gui_delete_note).pack(side="left", padx=4)
        ttk.Button(top, text="Rafraîchir", command=self.refresh_notes).pack(side="left", padx=4)

        ttk.Label(right, text="Contenu", style="Title.TLabel").pack(anchor="w", pady=(10, 0))
        self.note_text = tk.Text(right, wrap="word", undo=True)
        self.note_text.pack(fill="both", expand=True, pady=8)

        self.note_status_var = tk.StringVar(value="Prêt.")
        ttk.Label(right, textvariable=self.note_status_var, style="Muted.TLabel").pack(anchor="w")

    def refresh_notes(self):
        try:
            notes = list_notes()
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lister les notes:\n{e}")
            return

        self.notes_list.delete(0, tk.END)
        for n in notes:
            self.notes_list.insert(tk.END, n.get("title", ""))

    def _get_selected_note_title(self):
        sel = self.notes_list.curselection()
        if not sel:
            return None
        return self.notes_list.get(sel[0])

    def gui_open_note(self):
        title = self._get_selected_note_title()
        if not title:
            return
        self.note_title_var.set(title)
        try:
            content = read_note(title)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            return

        self.note_text.delete("1.0", tk.END)
        self.note_text.insert(tk.END, content)
        self.note_status_var.set(f"Note ouverte : {title}")

    def gui_create_note(self):
        title = self.note_title_var.get().strip()
        content = self.note_text.get("1.0", tk.END).strip()
        if not title:
            messagebox.showwarning("Attention", "Entre un titre.")
            return
        try:
            create_note(title, content)
            self.refresh_notes()
            self.note_status_var.set("Note créée ✓")
            messagebox.showinfo("OK", "Note créée.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_update_note(self):
        title = self.note_title_var.get().strip()
        content = self.note_text.get("1.0", tk.END).strip()
        if not title:
            messagebox.showwarning("Attention", "Entre un titre.")
            return
        try:
            titles = [n.get("title") for n in list_notes()]
            if title in titles:
                edit_note(title, content)
                self.note_status_var.set("Enregistré ✓")
            else:
                create_note(title, content)
                self.refresh_notes()
                self.note_status_var.set("Enregistré (créée) ✓")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_delete_note(self):
        title = self.note_title_var.get().strip()
        if not title:
            messagebox.showwarning("Attention", "Entre ou sélectionne un titre.")
            return
        if not messagebox.askyesno("Confirmer", f"Supprimer la note '{title}' ?"):
            return
        try:
            delete_note(title)
            self.note_title_var.set("")
            self.note_text.delete("1.0", tk.END)
            self.refresh_notes()
            self.note_status_var.set("Note supprimée ✓")
            messagebox.showinfo("OK", "Note supprimée.")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def _autosave_notes(self):
        try:
            title = self.note_title_var.get().strip()
            content = self.note_text.get("1.0", tk.END).strip()
            if title:
                titles = [n.get("title") for n in list_notes()]
                if title in titles:
                    edit_note(title, content)
                    self.note_status_var.set("Autosave ✓")
                else:
                    create_note(title, content)
                    self.refresh_notes()
                    self.note_status_var.set("Autosave (créée) ✓")
        except Exception:
            pass
        finally:
            self.after(self._autosave_interval_ms, self._autosave_notes)

    # =========================
    # QCM IA (INTERACTIF + fallback texte)
    # =========================
    def _build_qcm_tab(self):
        wrap = ScrollableFrame(self.tab_qcm)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        pad = ttk.Frame(root, padding=12, style="Panel.TFrame")
        pad.pack(fill="both", expand=True)

        gen = ttk.LabelFrame(pad, text="Génération", padding=10)
        gen.pack(fill="x", pady=(0, 10))

        ttk.Label(gen, text="Fichier texte :", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=4, pady=6)
        self.qcm_path_var = tk.StringVar()
        ttk.Entry(gen, textvariable=self.qcm_path_var).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(gen, text="Choisir…", command=self.gui_choose_qcm_file).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(gen, text="Questions :", style="Muted.TLabel").grid(row=0, column=3, sticky="e", padx=(14, 4))
        self.qcm_n_var = tk.IntVar(value=5)
        ttk.Spinbox(gen, from_=1, to=20, textvariable=self.qcm_n_var, width=5).grid(row=0, column=4, padx=6)

        ttk.Label(gen, text="Difficulté :", style="Muted.TLabel").grid(row=0, column=5, sticky="e", padx=(14, 4))
        self.qcm_diff_var = tk.StringVar(value="moyen")
        ttk.Combobox(
            gen, state="readonly", width=10,
            values=["facile", "moyen", "difficile"],
            textvariable=self.qcm_diff_var
        ).grid(row=0, column=6, padx=6)

        ttk.Button(gen, text="Générer", style="Primary.TButton", command=self.gui_generate_qcm).grid(row=0, column=7, padx=8)
        gen.columnconfigure(1, weight=1)

        quiz = ttk.LabelFrame(pad, text="Quiz", padding=10)
        quiz.pack(fill="both", expand=True)

        self.qcm_status = tk.StringVar(value="Aucun QCM généré.")
        ttk.Label(quiz, textvariable=self.qcm_status, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        self.qcm_question_lbl = ttk.Label(quiz, text="", style="Title.TLabel", wraplength=950, justify="left")
        self.qcm_question_lbl.pack(anchor="w", pady=(0, 8))

        self.qcm_choice_var = tk.IntVar(value=-1)
        self.qcm_choices_frame = ttk.Frame(quiz)
        self.qcm_choices_frame.pack(fill="x", pady=(0, 10))

        nav = ttk.Frame(quiz)
        nav.pack(fill="x", pady=(10, 6))

        self.btn_prev = ttk.Button(nav, text="← Précédent", command=self.qcm_prev, state="disabled")
        self.btn_prev.pack(side="left", padx=4)

        self.btn_next = ttk.Button(nav, text="Suivant →", command=self.qcm_next, state="disabled")
        self.btn_next.pack(side="left", padx=4)

        self.btn_finish = ttk.Button(nav, text="Terminer & Corrigé", style="Primary.TButton",
                                     command=self.qcm_finish, state="disabled")
        self.btn_finish.pack(side="left", padx=10)

        ttk.Separator(quiz).pack(fill="x", pady=10)

        ttk.Label(quiz, text="Correction / Résultat", style="Title.TLabel").pack(anchor="w")
        self.qcm_correction = tk.Text(quiz, wrap="word", height=16)
        self.qcm_correction.pack(fill="both", expand=True, pady=6)
        self.qcm_correction.insert("1.0", "Le corrigé s'affichera ici après 'Terminer'.")
        self.qcm_correction.config(state="disabled")

    def gui_choose_qcm_file(self):
        path = filedialog.askopenfilename(
            title="Choisir un fichier texte",
            filetypes=[("Text", "*.txt *.md"), ("All files", "*.*")]
        )
        if path:
            self.qcm_path_var.set(path)

    def gui_generate_qcm(self):
        path = self.qcm_path_var.get().strip().strip('"')
        if not path:
            messagebox.showwarning("Attention", "Choisis un fichier.")
            return
        if not os.path.exists(path):
            messagebox.showerror("Erreur", "Fichier introuvable.")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                messagebox.showwarning("Attention", "Le fichier est vide.")
                return

            n = int(self.qcm_n_var.get())
            diff = self.qcm_diff_var.get().strip()

            self.qcm_status.set("⏳ Génération IA en cours…")
            self._set_qcm_enabled(False)
            self.update_idletasks()

            raw = generate_qcm_quiz(text, n=n, difficulty=diff)

            # 1) JSON
            data = _normalize_qcm(_extract_json_obj(raw))

            # 2) fallback texte (IMPORTANT pour ton cas !)
            if not data:
                data = _normalize_qcm(_parse_qcm_from_text(raw))

            if not data:
                raise ValueError("Impossible de parser le QCM (format inattendu).")

            self.qcm_data = data
            self.qcm_index = 0
            self.qcm_user_answers = {}

            self.qcm_status.set(f"QCM généré : {len(self.qcm_data['questions'])} question(s).")
            self._set_qcm_enabled(True)
            self.qcm_render_question()

            self.qcm_correction.config(state="normal")
            self.qcm_correction.delete("1.0", tk.END)
            self.qcm_correction.insert("1.0", "Le corrigé s'affichera ici après 'Terminer'.")
            self.qcm_correction.config(state="disabled")

        except Exception as e:
            self.qcm_status.set("Aucun QCM généré.")
            self._set_qcm_enabled(False)
            messagebox.showerror("Erreur QCM", str(e))

    def _set_qcm_enabled(self, enabled: bool):
        if enabled and self.qcm_data:
            self.btn_prev.config(state=("disabled" if self.qcm_index == 0 else "normal"))
            self.btn_next.config(state=("normal" if self.qcm_index < len(self.qcm_data["questions"]) - 1 else "disabled"))
            self.btn_finish.config(state="normal")
        else:
            self.btn_prev.config(state="disabled")
            self.btn_next.config(state="disabled")
            self.btn_finish.config(state="disabled")

    def qcm_render_question(self):
        if not self.qcm_data:
            return

        qs = self.qcm_data["questions"]
        q = qs[self.qcm_index]

        self.qcm_question_lbl.config(text=f"Question {self.qcm_index + 1}/{len(qs)}\n\n{q['question']}")

        for w in self.qcm_choices_frame.winfo_children():
            w.destroy()

        self.qcm_choice_var.set(self.qcm_user_answers.get(self.qcm_index, -1))

        for i, opt in enumerate(q["options"]):
            rb = ttk.Radiobutton(
                self.qcm_choices_frame,
                text=opt,
                variable=self.qcm_choice_var,
                value=i,
                command=self.qcm_save_choice
            )
            rb.pack(anchor="w", pady=2)

        self._set_qcm_enabled(True)

    def qcm_save_choice(self):
        val = self.qcm_choice_var.get()
        if val >= 0:
            self.qcm_user_answers[self.qcm_index] = val

    def qcm_prev(self):
        if not self.qcm_data:
            return
        self.qcm_save_choice()
        if self.qcm_index > 0:
            self.qcm_index -= 1
        self.qcm_render_question()

    def qcm_next(self):
        if not self.qcm_data:
            return
        self.qcm_save_choice()
        if self.qcm_index < len(self.qcm_data["questions"]) - 1:
            self.qcm_index += 1
        self.qcm_render_question()

    def qcm_finish(self):
        if not self.qcm_data:
            return
        self.qcm_save_choice()

        qs = self.qcm_data["questions"]
        total = len(qs)
        score = 0
        lines = []

        for idx, q in enumerate(qs):
            options = q["options"]
            correct_idx = _answer_to_index(q.get("answer"), options)
            user_idx = self.qcm_user_answers.get(idx)

            ok = (correct_idx is not None and user_idx == correct_idx)
            if ok:
                score += 1

            lines.append(f"Q{idx+1}: {q['question']}")
            lines.append(f"Ta réponse : {options[user_idx]}" if user_idx is not None else "Ta réponse : (aucune)")
            lines.append(f"Bonne réponse : {options[correct_idx]}" if correct_idx is not None else "Bonne réponse : (inconnue)")
            if q.get("explanation"):
                lines.append(f"Explication : {q['explanation']}")
            lines.append("-" * 60)

        self.qcm_status.set(f"Terminé — Score : {score}/{total}")

        self.qcm_correction.config(state="normal")
        self.qcm_correction.delete("1.0", tk.END)
        self.qcm_correction.insert("1.0", "\n".join(lines))
        self.qcm_correction.config(state="disabled")

    # =========================
    # CAREER
    # =========================
    def _build_career_tab(self):
        wrap = ScrollableFrame(self.tab_career)
        wrap.pack(fill="both", expand=True)
        root = wrap.inner

        pad = ttk.Frame(root, padding=12, style="Panel.TFrame")
        pad.pack(fill="both", expand=True)

        left = ttk.Frame(pad, padding=10, style="Card.TFrame")
        right = ttk.Frame(pad, padding=10, style="Card.TFrame")
        left.pack(side="left", fill="y", padx=(0, 10))
        right.pack(side="right", fill="both", expand=True)

        form = ttk.LabelFrame(left, text="Assistant CV (IA)", padding=10)
        form.pack(fill="x")

        self.cv_name = tk.StringVar()
        self.cv_target_title = tk.StringVar(value="Étudiant / Junior")
        self.cv_contact = tk.StringVar(value="email | téléphone | ville | LinkedIn")

        self.cv_profile_raw = tk.StringVar()
        self.cv_edu_raw = tk.StringVar()
        self.cv_skills_raw = tk.StringVar()
        self.cv_exp_raw = tk.StringVar()
        self.cv_projects_raw = tk.StringVar()
        self.cv_lang_raw = tk.StringVar()
        self.cv_interests_raw = tk.StringVar()

        def row(label, var):
            r = ttk.Frame(form)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=16).pack(side="left")
            ttk.Entry(r, textvariable=var, width=36).pack(side="left", fill="x", expand=True)

        row("Nom", self.cv_name)
        row("Titre visé", self.cv_target_title)
        row("Contact", self.cv_contact)

        ttk.Separator(form).pack(fill="x", pady=8)

        row("Profil (brut)", self.cv_profile_raw)
        row("Formation (brut)", self.cv_edu_raw)
        row("Compétences (brut)", self.cv_skills_raw)
        row("Expérience (brut)", self.cv_exp_raw)
        row("Projets (brut)", self.cv_projects_raw)
        row("Langues (brut)", self.cv_lang_raw)
        row("Intérêts", self.cv_interests_raw)

        style = ttk.LabelFrame(left, text="Style", padding=10)
        style.pack(fill="x", pady=10)

        self.cv_template = tk.StringVar(value="Moderne")
        self.cv_color = tk.StringVar(value="#6A7BFF")
        self.cv_photo_path = tk.StringVar(value="")

        ttk.Label(style, text="Modèle").pack(anchor="w")
        ttk.Combobox(
            style,
            state="readonly",
            values=["Moderne", "Classique"],
            textvariable=self.cv_template
        ).pack(fill="x", pady=2)

        color_row = ttk.Frame(style)
        color_row.pack(fill="x", pady=6)
        ttk.Label(color_row, text="Couleur").pack(side="left")
        self.color_preview = tk.Label(color_row, width=3, bg=self.cv_color.get())
        self.color_preview.pack(side="left", padx=6)
        ttk.Button(color_row, text="Choisir…", command=self.gui_pick_cv_color).pack(side="left")

        ttk.Button(style, text="Choisir photo…", command=self.gui_choose_cv_photo).pack(fill="x", pady=4)

        ttk.Button(style, text="Nouveau CV (réinitialiser)", command=self.gui_reset_cv).pack(fill="x", pady=(8, 4))
        ttk.Button(style, text="Générer CV (IA)", style="Primary.TButton", command=self.gui_generate_cv_ai).pack(fill="x", pady=4)
        ttk.Button(style, text="Exporter PDF", command=self.gui_export_cv_pdf_from_ai).pack(fill="x")

        preview_frame = ttk.LabelFrame(right, text="Prévisualisation", padding=10)
        preview_frame.pack(fill="both", expand=True)

        self.cv_canvas = tk.Canvas(preview_frame, bg="white", highlightthickness=1, highlightbackground=self.border)
        self.cv_canvas.pack(fill="both", expand=True)

        self.draw_cv_preview()

        interview_frame = ttk.LabelFrame(right, text="Coach d’entretien", padding=10)
        interview_frame.pack(fill="both", expand=True, pady=10)

        top = ttk.Frame(interview_frame)
        top.pack(fill="x")
        ttk.Label(top, text="Poste visé:", width=12).pack(side="left")
        self.job_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.job_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Nouvelle question", command=self.gui_new_question).pack(side="left", padx=4)

        ttk.Label(interview_frame, text="Question").pack(anchor="w", pady=(10, 0))
        self.question_box = tk.Text(interview_frame, height=4, wrap="word")
        self.question_box.pack(fill="x", pady=4)

        ttk.Label(interview_frame, text="Ta réponse").pack(anchor="w", pady=(10, 0))
        self.answer_box = tk.Text(interview_frame, height=6, wrap="word")
        self.answer_box.pack(fill="x", pady=4)

        ttk.Button(interview_frame, text="Obtenir feedback", style="Primary.TButton", command=self.gui_feedback).pack(pady=6)

        ttk.Label(interview_frame, text="Feedback").pack(anchor="w", pady=(10, 0))
        self.feedback_box = tk.Text(interview_frame, wrap="word")
        self.feedback_box.pack(fill="both", expand=True, pady=4)

    def gui_reset_cv(self):
        self.cv_ai = None
        self.draw_cv_preview()
        messagebox.showinfo("OK", "Tu peux modifier les champs puis régénérer le CV.")

    def gui_pick_cv_color(self):
        _, hex_color = colorchooser.askcolor(title="Choisir une couleur")
        if hex_color:
            self.cv_color.set(hex_color)
            self.color_preview.configure(bg=hex_color)
            self.draw_cv_preview()

    def gui_choose_cv_photo(self):
        path = filedialog.askopenfilename(
            title="Choisir une photo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")]
        )
        if path:
            self.cv_photo_path.set(path)

    def gui_generate_cv_ai(self):
        name = self.cv_name.get().strip()
        if not name:
            messagebox.showwarning("Attention", "Le nom est obligatoire.")
            return

        data = {
            "name": name,
            "target_title": self.cv_target_title.get().strip(),
            "contact": self.cv_contact.get().strip(),
            "profile": self.cv_profile_raw.get().strip(),
            "education": self.cv_edu_raw.get().strip(),
            "skills": self.cv_skills_raw.get().strip(),
            "experience": self.cv_exp_raw.get().strip(),
            "projects": self.cv_projects_raw.get().strip(),
            "languages": self.cv_lang_raw.get().strip(),
            "interests": self.cv_interests_raw.get().strip(),
        }

        try:
            self.cv_canvas.delete("all")
            self.cv_canvas.create_text(20, 20, anchor="nw", text="⏳ Génération IA en cours...", font=("Segoe UI", 14))
            self.update_idletasks()

            self.cv_ai = generate_cv_structured(data)
            self.draw_cv_preview()
            messagebox.showinfo("OK", "CV généré par l’IA ✅")
        except Exception as e:
            messagebox.showerror("Erreur IA", str(e))

    def draw_cv_preview(self):
        c = self.cv_canvas
        c.delete("all")

        w = c.winfo_width() or 900
        h = c.winfo_height() or 500

        x0, y0 = 40, 40
        page_w, page_h = w - 80, h - 80

        c.create_rectangle(x0, y0, x0 + page_w, y0 + page_h, fill="white", outline="#ccc")

        if not self.cv_ai or not isinstance(self.cv_ai, dict):
            c.create_text(
                x0 + 20, y0 + 20,
                anchor="nw",
                text="Clique sur « Générer CV (IA) » pour voir l’aperçu",
                font=("Segoe UI", 14),
                fill=self.muted
            )
            return

        header = self.cv_ai.get("header", {})
        name = header.get("full_name", self.cv_name.get().strip())
        title = header.get("title", self.cv_target_title.get().strip())
        contact = header.get("contact", self.cv_contact.get().strip())

        accent = (self.cv_color.get().strip() or "#6A7BFF")

        c.create_rectangle(x0, y0, x0 + page_w, y0 + 100, fill=accent, outline="")
        c.create_text(x0 + 20, y0 + 18, anchor="nw", text=name, fill="white", font=("Segoe UI", 20, "bold"))
        c.create_text(x0 + 20, y0 + 52, anchor="nw", text=title, fill="white", font=("Segoe UI", 12))
        c.create_text(x0 + 20, y0 + 76, anchor="nw", text=contact, fill="white", font=("Segoe UI", 10))

        y = y0 + 120
        profile = self.cv_ai.get("profile", "")
        c.create_text(x0 + 20, y, anchor="nw", text="Profil", font=("Segoe UI", 12, "bold"), fill=self.text)
        y += 22
        c.create_text(
            x0 + 20, y, anchor="nw",
            text=profile[:600] + ("..." if len(profile) > 600 else ""),
            width=page_w - 40,
            font=("Segoe UI", 10),
            fill=self.text
        )

    def gui_export_cv_pdf_from_ai(self):
        if not self.cv_ai or not isinstance(self.cv_ai, dict):
            messagebox.showwarning("Attention", "Génère d’abord le CV avec l’IA.")
            return

        header = self.cv_ai.get("header", {})
        full_name = header.get("full_name", self.cv_name.get().strip())
        title_line = header.get("title", self.cv_target_title.get().strip())
        contact = header.get("contact", self.cv_contact.get().strip())

        template = self.cv_template.get().strip()
        accent = self.cv_color.get().strip()
        photo = self.cv_photo_path.get().strip() or None

        profile = self.cv_ai.get("profile", "")
        education = "\n".join(self.cv_ai.get("education", []))
        skills = "\n".join(self.cv_ai.get("skills", []))

        exp_blocks = []
        for e in self.cv_ai.get("experience", []):
            head = f"{e.get('title','')} - {e.get('company','')} ({e.get('dates','')})".strip()
            exp_blocks.append(head)
            for b in e.get("bullets", []):
                exp_blocks.append(f"• {b}")
            exp_blocks.append("")
        experience = "\n".join(exp_blocks).strip()

        projects = "\n".join(self.cv_ai.get("projects", []))
        languages = "\n".join(self.cv_ai.get("languages", []))
        interests = "\n".join(self.cv_ai.get("interests", []))

        sections = [
            ("Profil", profile or "(non renseigné)"),
            ("Formation", education or "(non renseigné)"),
            ("Compétences", skills or "(non renseigné)"),
            ("Expérience", experience or "(non renseigné)"),
            ("Projets", projects or "(optionnel)"),
            ("Langues", languages or "(optionnel)"),
            ("Intérêts", interests or "(optionnel)"),
        ]

        path = filedialog.asksaveasfilename(
            title="Exporter CV en PDF",
            defaultextension=".pdf",
            initialfile=f"CV_{full_name.replace(' ', '_')}.pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        if not path:
            return

        try:
            export_cv_pdf(
                path,
                template=template,
                accent_hex=accent,
                photo_path=photo,   # None ok
                full_name=full_name,
                title_line=title_line,
                contact=contact,
                sections=sections
            )
            messagebox.showinfo("OK", "CV exporté en PDF ✅")
        except Exception as e:
            messagebox.showerror("Erreur export PDF", str(e))

    def gui_new_question(self):
        job = self.job_var.get().strip()
        if not job:
            messagebox.showwarning("Attention", "Entre un poste visé.")
            return
        try:
            self.question_box.delete("1.0", tk.END)
            self.question_box.insert(tk.END, "⏳ Génération...\n")
            self.update_idletasks()
            q = interview_question(job)
            self.question_box.delete("1.0", tk.END)
            self.question_box.insert(tk.END, q)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def gui_feedback(self):
        job = self.job_var.get().strip()
        answer = self.answer_box.get("1.0", tk.END).strip()
        if not job:
            messagebox.showwarning("Attention", "Entre un poste visé.")
            return
        if not answer:
            messagebox.showwarning("Attention", "Écris une réponse.")
            return
        try:
            self.feedback_box.delete("1.0", tk.END)
            self.feedback_box.insert(tk.END, "⏳ Analyse...\n")
            self.update_idletasks()
            fb = interview_feedback(job, answer)
            self.feedback_box.delete("1.0", tk.END)
            self.feedback_box.insert(tk.END, fb)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))


if __name__ == "__main__":
    app = CartableApp()
    app.mainloop()
