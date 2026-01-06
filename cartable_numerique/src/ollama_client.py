import json
import subprocess
import re


# =========================================================
# OLLAMA CORE
# =========================================================

def ask_ollama(prompt, model="llama3.1"):
    """
    Appelle Ollama via la CLI.
    """
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            text=True,
            capture_output=True,
            encoding="utf-8"
        )

        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()

        if not out:
            raise RuntimeError(f"Ollama n'a rien renvoyé. stderr={err}")

        return out

    except FileNotFoundError:
        raise RuntimeError("Commande 'ollama' introuvable. Ollama n'est pas installé ou pas dans le PATH.")
    except Exception as e:
        raise RuntimeError(f"Erreur Ollama: {e}")


# =========================================================
# JSON EXTRACTION & CLEANING
# =========================================================

def _extract_json(text: str) -> str:
    """
    Extrait le JSON le plus probable d'une réponse IA.
    Supporte :
    - ```json ... ```
    - ``` ... ```
    - fallback : plus grand bloc {...}
    """
    # ```json ... ```
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # ``` ... ```
    m = re.search(r"```\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # fallback : prendre le plus gros {...}
    blocks = re.findall(r"\{.*?\}", text, re.DOTALL)
    if not blocks:
        raise ValueError("Aucun JSON détecté dans la réponse IA")

    blocks.sort(key=len, reverse=True)
    return blocks[0].strip()


def _clean_keys(obj):
    """
    Nettoie récursivement les clés (espaces, retours ligne, guillemets).
    """
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if isinstance(k, str):
                kk = k.strip()
                kk = kk.replace("\n", "").replace("\r", "").replace("\t", "")
                kk = kk.strip('"').strip("'")
            else:
                kk = k
            clean[kk] = _clean_keys(v)
        return clean
    elif isinstance(obj, list):
        return [_clean_keys(x) for x in obj]
    else:
        return obj


def _norm_key(k: str) -> str:
    """
    Normalise une clé pour comparaison :
    - enlève espaces, retours ligne, guillemets
    - lowercase
    """
    if not isinstance(k, str):
        return str(k)
    k = k.strip()
    k = k.replace("\n", "").replace("\r", "").replace("\t", "")
    k = k.replace('"', "").replace("'", "")
    k = k.replace(" ", "")
    return k.lower()


def _pick(d: dict, wanted: str):
    """
    Récupère une valeur même si la clé est cassée.
    """
    if not isinstance(d, dict):
        return None

    wanted_n = _norm_key(wanted)

    # direct
    if wanted in d:
        return d[wanted]

    # par normalisation
    for k, v in d.items():
        if _norm_key(k) == wanted_n:
            return v

    return None


def _ensure_list(x):
    """
    Force une valeur en liste propre.
    """
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        lines = [l.strip("-• \t") for l in x.splitlines() if l.strip()]
        return lines if lines else [x]
    return [x]


# =========================================================
# QCM
# =========================================================

def generate_qcm_quiz(text, n=5, difficulty="moyen", model="llama3.1"):
    from prompts import QCM_PROMPT
    prompt = QCM_PROMPT.format(text=text, n=n, difficulty=difficulty)
    return ask_ollama(prompt, model=model)


# =========================================================
# CV STRUCTURÉ (IA) — VERSION ROBUSTE
# =========================================================

def generate_cv_structured(data, model="llama3.1"):
    from prompts import CV_STRUCTURED_PROMPT

    prompt = CV_STRUCTURED_PROMPT.format(**data)
    raw = ask_ollama(prompt, model=model)

    # DEBUG (laisse-le, utile pour le rapport aussi)
    with open("debug_cv_raw.txt", "w", encoding="utf-8") as f:
        f.write(raw)

    json_text = _extract_json(raw)

    try:
        parsed = json.loads(json_text)
    except Exception:
        with open("debug_cv_bad_json.txt", "w", encoding="utf-8") as f:
            f.write(json_text)
        raise ValueError("JSON invalide renvoyé par l'IA (voir debug_cv_bad_json.txt)")

    parsed = _clean_keys(parsed)

    # récupération SAFE des champs
    header = _pick(parsed, "header") or {}
    profile = _pick(parsed, "profile")
    education = _pick(parsed, "education")
    skills = _pick(parsed, "skills")
    experience = _pick(parsed, "experience")
    projects = _pick(parsed, "projects")
    languages = _pick(parsed, "languages")
    interests = _pick(parsed, "interests")

    # sécuriser header
    if not isinstance(header, dict):
        header = {}

    header.setdefault("full_name", data.get("name", ""))
    header.setdefault("title", data.get("target_title", ""))
    header.setdefault("contact", data.get("contact", ""))

    # sécuriser expérience
    exp_out = []
    if isinstance(experience, list):
        for e in experience:
            if isinstance(e, dict):
                exp_out.append({
                    "title": e.get("title", ""),
                    "company": e.get("company", ""),
                    "dates": e.get("dates", ""),
                    "bullets": _ensure_list(e.get("bullets")),
                })

    # STRUCTURE FINALE GARANTIE
    return {
        "header": header,
        "profile": profile if isinstance(profile, str) else "",
        "education": _ensure_list(education),
        "skills": _ensure_list(skills),
        "experience": exp_out,
        "projects": _ensure_list(projects),
        "languages": _ensure_list(languages),
        "interests": _ensure_list(interests),
    }


# =========================================================
# COACH D’ENTRETIEN
# =========================================================

def interview_question(job, model="llama3.1"):
    from prompts import INTERVIEW_QUESTION_PROMPT
    prompt = INTERVIEW_QUESTION_PROMPT.format(job=job)
    return ask_ollama(prompt, model=model)


def interview_feedback(job, answer, model="llama3.1"):
    from prompts import INTERVIEW_FEEDBACK_PROMPT
    prompt = INTERVIEW_FEEDBACK_PROMPT.format(job=job, answer=answer)
    return ask_ollama(prompt, model=model)
