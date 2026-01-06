import os
import json
import shutil
import sys
import subprocess
from datetime import datetime

# Chemins de base
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOCS_DIR = os.path.join(DATA_DIR, "documents")
NOTES_DIR = os.path.join(DATA_DIR, "notes")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")


# ---------- INITIALISATION ----------

def init_storage():
    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(NOTES_DIR, exist_ok=True)
    if not os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({"documents": [], "notes": []}, f, indent=2)


def _load_index():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(index):
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


# ---------- CLOUD LOCAL (DOCUMENTS) ----------

def import_document(path):
    init_storage()
    if not os.path.isfile(path):
        raise FileNotFoundError("Fichier introuvable")

    filename = os.path.basename(path)
    dest = os.path.join(DOCS_DIR, filename)
    shutil.copy2(path, dest)

    index = _load_index()
    index["documents"].append({
        "name": filename,
        "imported_at": datetime.now().isoformat()
    })
    _save_index(index)


def list_documents():
    init_storage()
    return _load_index()["documents"]


def find_document_path(doc_name):
    """
    Recherche un document dans data/documents et tous ses sous-dossiers
    """
    init_storage()
    for root, dirs, files in os.walk(DOCS_DIR):
        if doc_name in files:
            return os.path.join(root, doc_name)
    return None


def open_document(name):
    path = find_document_path(name)
    if not path:
        raise FileNotFoundError("Document introuvable")

    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform.startswith("darwin"):
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path])


def delete_document(name):
    path = find_document_path(name)
    if not path:
        raise FileNotFoundError("Document introuvable")

    os.remove(path)

    index = _load_index()
    index["documents"] = [
        d for d in index["documents"] if d["name"] != name
    ]
    _save_index(index)


# ---------- DOSSIERS ----------

def create_folder(folder_name):
    init_storage()
    folder_name = folder_name.strip()
    if not folder_name:
        raise ValueError("Nom de dossier invalide")

    path = os.path.join(DOCS_DIR, folder_name)
    os.makedirs(path, exist_ok=True)


def list_folders():
    init_storage()
    return [
        d for d in os.listdir(DOCS_DIR)
        if os.path.isdir(os.path.join(DOCS_DIR, d))
    ]


def move_document_to_folder(doc_name, folder_name):
    init_storage()
    src_path = find_document_path(doc_name)
    if not src_path:
        raise FileNotFoundError("Document introuvable")

    dest_folder = os.path.join(DOCS_DIR, folder_name)
    if not os.path.isdir(dest_folder):
        raise FileNotFoundError("Dossier introuvable")

    dest_path = os.path.join(dest_folder, doc_name)
    shutil.move(src_path, dest_path)

    index = _load_index()
    for d in index["documents"]:
        if d["name"] == doc_name:
            d["folder"] = folder_name
    _save_index(index)


# ---------- NOTES ----------

def create_note(title, content):
    init_storage()
    safe_title = "".join(
        c for c in title if c.isalnum() or c in (" ", "_", "-")
    ).strip().replace(" ", "_")

    if not safe_title:
        safe_title = "note"

    filename = safe_title + ".txt"
    path = os.path.join(NOTES_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    index = _load_index()
    index["notes"].append({
        "title": title,
        "file": filename,
        "created_at": datetime.now().isoformat()
    })
    _save_index(index)


def list_notes():
    init_storage()
    return _load_index()["notes"]
def find_note_path_by_title(title):
    """
    Retrouve le fichier note associé à un titre via l'index.json.
    Retourne le chemin complet du fichier.
    """
    init_storage()
    index = _load_index()
    for n in index["notes"]:
        if n["title"] == title:
            return os.path.join(NOTES_DIR, n["file"])
    return None


def read_note(title):
    """
    Retourne le contenu d'une note (par titre).
    """
    path = find_note_path_by_title(title)
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Note introuvable")

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def edit_note(title, new_content):
    """
    Modifie le contenu d'une note existante.
    """
    path = find_note_path_by_title(title)
    if not path or not os.path.exists(path):
        raise FileNotFoundError("Note introuvable")

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)


def delete_note(title):
    """
    Supprime une note (fichier + entrée dans l'index).
    """
    init_storage()
    index = _load_index()

    # trouver la note
    note_obj = None
    for n in index["notes"]:
        if n["title"] == title:
            note_obj = n
            break

    if not note_obj:
        raise FileNotFoundError("Note introuvable")

    # supprimer le fichier
    path = os.path.join(NOTES_DIR, note_obj["file"])
    if os.path.exists(path):
        os.remove(path)

    # supprimer de l'index
    index["notes"] = [n for n in index["notes"] if n["title"] != title]
    _save_index(index)
