#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_story.py

Banc de test bout-en-bout :
  1. extrait + tague les frames d'une video en reutilisant la logique de
     tools/frame_tagger_test.py (import direct, pas de sous-processus) ;
  2. transforme ces tags en outline chronologique et le passe a build_prompt() ;
  3. envoie le prompt a generate_script() et affiche l'histoire generee.

Usage :
    python tools/test_story.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

from dotenv import load_dotenv

# Rendre la racine du projet importable quel que soit le repertoire courant
# (permet `import modules.*` et `import tools.*`).
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from modules.script_generator import build_prompt, generate_script
from modules.subtitle_generator import generate_subtitles
from tools.frame_tagger_test import (
    charger_modele,
    extraire_frames,
    formater_ts,
    tagger,
)

# Charge OPENROUTER_API_KEY / OPENROUTER_MODEL depuis le .env a la racine.
load_dotenv(os.path.join(RACINE, ".env"))

VIDEO = r"C:\Users\lucho\Downloads\8219115.mp4"
SOUS_TITRES = os.path.join(RACINE, "output", "test_subs.srt")


def duree_video(video_path):
    """Renvoie la duree de `video_path` en secondes (float) via ffprobe.

    ffprobe fait partie de la suite ffmpeg, deja requise par ce banc de test.
    L'option -show_entries format=duration ne demande que la duree du
    conteneur ; -of ...nokey=1 la renvoie brute, sans etiquette.
    """
    if shutil.which("ffprobe") is None:
        raise SystemExit("ffprobe introuvable sur le PATH (fourni avec ffmpeg).")

    sortie = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(sortie.stdout.strip())


def outline_depuis_video(video_path):
    """Extrait puis tague les frames de `video_path`.

    Renvoie une liste ordonnee `list[tuple[str, list[str]]]` : pour chaque
    frame, (horodatage "HH:MM:SS", liste des tags retenus, sans les scores),
    dans l'ordre chronologique. C'est le format attendu par build_prompt().
    """
    if not os.path.isfile(video_path):
        raise SystemExit(f"Fichier introuvable : {video_path}")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg introuvable sur le PATH.")

    dossier_tmp = tempfile.mkdtemp(prefix="frame_tagger_")
    try:
        frames = extraire_frames(video_path, dossier_tmp)
        if not frames:
            raise SystemExit("Aucune frame extraite, arret.")

        session, noms_tags, idx_general, idx_personnage, taille = charger_modele()
        resultats, _durees, _total = tagger(
            session, frames, noms_tags, idx_general, idx_personnage, taille
        )
    finally:
        shutil.rmtree(dossier_tmp, ignore_errors=True)

    # resultats : list[(timestamp_secondes, list[(nom_tag, score)])]
    return [
        (formater_ts(timestamp), [nom for nom, _score in tags])
        for timestamp, tags in resultats
    ]


def main():
    outline = outline_depuis_video(VIDEO)

    print("=" * 70)
    print("OUTLINE (tags par frame)")
    print("=" * 70)
    for horodatage, tags in outline:
        print(f"[{horodatage}]  {', '.join(tags) if tags else '(aucun tag)'}")

    prompt = build_prompt(outline)

    print("=" * 70)
    print("PROMPT ENVOYE")
    print("=" * 70)
    print(prompt)

    print("=" * 70)
    print("HISTOIRE GENEREE")
    print("=" * 70)
    histoire = generate_script(prompt)
    print(histoire)

    print("=" * 70)
    print("SOUS-TITRES (.srt)")
    print("=" * 70)
    duree = duree_video(VIDEO)
    print(f"Duree video : {duree:.2f} s")
    chemin = generate_subtitles(histoire, duree, SOUS_TITRES)
    print(f"Fichier genere : {chemin}")

    print("--- 5 premieres lignes ---")
    with open(chemin, encoding="utf-8") as fichier:
        for _ in range(5):
            ligne = fichier.readline()
            if not ligne:
                break
            print(ligne.rstrip("\n"))


if __name__ == "__main__":
    main()
