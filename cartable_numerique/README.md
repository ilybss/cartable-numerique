# Cartable Numérique – Projet L2 MIASHS

Projet réalisé dans le cadre de la Licence 2 MIASHS en Algorithmique et Programmation à l’Université Paris Nanterre.

Le Cartable Numérique est une application Python avec interface graphique (Tkinter) permettant :
- de centraliser et organiser des documents (cloud local),
- de prendre des notes avec sauvegarde locale,
- de réviser via des QCM générés par IA à partir de fichiers texte,
- de préparer l’insertion professionnelle (générateur de CV + coach d’entretien).

## Fonctionnalités
- Cloud local : importer / lister / ouvrir / supprimer + dossiers
- Notes : créer / modifier / supprimer + autosave
- QCM IA : génération depuis `.txt` / `.md`, session interactive + corrigé
- Carrière : CV structuré + export PDF + coach d’entretien

## Technologies
- Python 3
- Tkinter
- Ollama (IA en local)
- Modèle conseillé : `llama3.1` 

## Prérequis
- Python 3.10+ 
- Ollama installé et accessible en ligne de commande

Installer un modèle (exemple) :
```bash
ollama pull llama3.1
```

## Installation des dépendances (si besoin)
```bash
pip install -r requirements.txt
```

## Lancer l’application
Depuis la racine du projet :
```bash
python app_gui.py
```

## Dossier rapport (LaTeX)
Les sources LaTeX du rapport sont dans `rapport/`.

## Auteurs
- Bessahraoui Ilyana – 45016037
- Khelfane Massil – 43011881
