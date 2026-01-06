# =========================================================
# QCM
# =========================================================

QCM_PROMPT = """Tu es un générateur de QCM.
À partir du texte suivant, crée {n} questions de niveau {difficulty}.
Format attendu (texte lisible) :
- Q1: ...
  A) ...
  B) ...
  C) ...
  D) ...
  ANSWER: A
  EXPLANATION: ...

Texte :
{text}
"""


# =========================================================
# CV (STRUCTURÉ JSON) — IMPORTANT: accolades échappées {{ }}
# =========================================================

CV_STRUCTURED_PROMPT = """Tu es un assistant RH expert.
À partir des informations brutes ci-dessous, génère un CV structuré en JSON.
Le JSON doit être le SEUL contenu de ta réponse (pas de texte avant/après).

Règles :
- Sois professionnel, reformule et améliore le texte si nécessaire.
- Écris en français (sauf si les infos sont en anglais).
- Retourne EXACTEMENT ce schéma JSON :

{{
  "header": {{
    "full_name": "string",
    "title": "string",
    "contact": "string"
  }},
  "profile": "string",
  "education": ["string", "..."],
  "skills": ["string", "..."],
  "experience": [
    {{
      "title": "string",
      "company": "string",
      "dates": "string",
      "bullets": ["string", "..."]
    }}
  ],
  "projects": ["string", "..."],
  "languages": ["string", "..."],
  "interests": ["string", "..."]
}}

Données utilisateur :
- Nom: {name}
- Titre visé: {target_title}
- Contact: {contact}

Brut à améliorer :
- Profil: {profile}
- Formation: {education}
- Compétences: {skills}
- Expérience: {experience}
- Projets: {projects}
- Langues: {languages}
- Intérêts: {interests}
"""


# =========================================================
# COACH ENTRETIEN
# =========================================================

INTERVIEW_QUESTION_PROMPT = """Tu es un coach d'entretien.
Génère UNE question d'entretien pertinente pour le poste suivant : {job}
Donne uniquement la question, sans explication.
"""

INTERVIEW_FEEDBACK_PROMPT = """Tu es un coach d'entretien.
Poste visé : {job}

Réponse du candidat :
{answer}

Donne un feedback structuré :
1) Points forts
2) Points à améliorer
3) Proposition d'une meilleure réponse (plus concise et impactante)
"""
