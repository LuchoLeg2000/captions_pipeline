#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
main.py

Pipeline complet pour une video identifiee par son video_id. Enchaine, dans
l'ordre, les cinq etapes suivantes en affichant un resume apres chacune :

  1. telechargement de la video source depuis le VPS de test
     (tools.sync_video.download) ;
  2. extraction d'une frame toutes les 8 s + tagging WD14, en reutilisant la
     logique de tools/frame_tagger_test.py (import direct, pas de sous-processus) ;
  3. construction de l'outline chronologique (build_prompt) puis generation de
     l'histoire par le modele OpenRouter (generate_script) ;
  4. generation d'un .srt reparti sur la duree *reelle* de la video telechargee
     (mesuree avec ffprobe) ;
  5. envoi des sous-titres au backend en HTTP POST
     (modules.subtitle_sender.send_subtitles) *et*, en parallele pour l'instant,
     depot du .srt sur le VPS via scp (tools.sync_video.upload).

Usage :
    python main.py 6889258
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

from dotenv import load_dotenv

# Racine du projet : permet `import modules.*` et `import tools.*` quel que
# soit le repertoire courant d'ou l'on lance le script.
RACINE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RACINE)

from modules.script_generator import build_prompt, generate_script
from modules.subtitle_generator import generate_subtitles
from modules.subtitle_sender import send_subtitles
from modules.theme_selector import fetch_themes, theme_instruction
from modules.wd14_sender import send_wd14_tags
from tools import sync_video
from tools.frame_tagger_test import (
    charger_modele,
    extraire_frames,
    formater_ts,
    tagger,
)

# Charge OPENROUTER_API_KEY / OPENROUTER_MODEL depuis le .env a la racine.
load_dotenv(os.path.join(RACINE, ".env"))

DOSSIER_SORTIE = os.path.join(RACINE, "output")
NB_ETAPES = 5


# --- Affichage -----------------------------------------------------------------

def _titre_etape(numero, libelle):
    """Affiche un bandeau de debut d'etape."""
    print()
    print("=" * 70)
    print(f"ETAPE {numero}/{NB_ETAPES} : {libelle}")
    print("=" * 70)


# --- Outils video ------------------------------------------------------------

def duree_video(video_path):
    """Renvoie la duree de `video_path` en secondes (float) via ffprobe.

    ffprobe fait partie de la suite ffmpeg. -show_entries format=duration ne
    demande que la duree du conteneur ; -of ...nokey=1 la renvoie brute.
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

    Reutilise directement extraire_frames() / charger_modele() / tagger() de
    tools/frame_tagger_test.py. Renvoie une liste ordonnee
    `list[tuple[str, list[str]]]` : pour chaque frame, (horodatage "HH:MM:SS",
    liste des tags retenus sans les scores), dans l'ordre chronologique.
    C'est le format attendu par build_prompt().
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


# --- Pipeline --------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage : python main.py <video_id>\nExemple : python main.py 6889258")

    video_id = str(sys.argv[1]).strip()
    if not video_id:
        raise SystemExit("video_id vide.")

    t0_pipeline = time.perf_counter()
    print(f"Pipeline captions - video_id = {video_id}")

    # Themes narratifs : on recupere le catalogue des le demarrage ; la
    # selection effective a lieu a l'etape 3, une fois les tags WD14 connus.
    # fetch_themes() renvoie [] (avec un avertissement) si le backend est
    # injoignable ou si la liste est vide -> l'histoire est alors generee
    # sans theme, sans interrompre le pipeline.
    themes = fetch_themes(video_id)
    if themes:
        print(f"-> {len(themes)} theme(s) narratif(s) disponible(s) depuis le backend")
    else:
        print("-> Aucun theme narratif disponible : histoire generee sans theme")

    # --- Etape 1 : telechargement de la video source -----------------------
    _titre_etape(1, "Telechargement de la video source depuis le VPS")
    chemin_video = sync_video.download(video_id)
    taille_mo = os.path.getsize(chemin_video) / (1024 * 1024)
    print(f"-> Video locale : {chemin_video}  ({taille_mo:.1f} Mo)")

    # --- Etape 2 : extraction + tagging des frames ------------------------
    _titre_etape(2, "Extraction et tagging des frames")
    outline = outline_depuis_video(chemin_video)
    total_tags = sum(len(tags) for _, tags in outline)
    print(f"-> {len(outline)} frame(s) analysee(s), {total_tags} tag(s) retenu(s) au total")
    for horodatage, tags in outline:
        if tags:
            apercu = ", ".join(tags[:8])
            if len(tags) > 8:
                apercu += f"  (+{len(tags) - 8})"
        else:
            apercu = "(aucun tag au-dessus du seuil)"
        print(f"   [{horodatage}] {apercu}")

    # --- Etape 3 : outline -> histoire ----------------------------------
    _titre_etape(3, "Construction de l'outline et generation de l'histoire")
    # Selection du theme narratif a partir des tags WD14 distincts detectes.
    # theme_instruction() renvoie None (avec un avertissement) si la liste de
    # themes est vide ou si l'appel de selection echoue -> prompt par defaut.
    tags_detectes = sorted({tag for _, tags in outline for tag in tags})
    resultat_wd14 = send_wd14_tags(video_id, tags_detectes)
    if resultat_wd14.get("success"):
        print(f"-> Tags WD14 envoyes au backend : {resultat_wd14.get('count')} tag(s)")
    else:
        print(f"-> Envoi des tags WD14 au backend echoue : {resultat_wd14.get('error')}")
    instruction_theme = theme_instruction(tags_detectes, themes)
    if instruction_theme:
        print("-> Theme narratif applique a l'histoire")
    else:
        print("-> Histoire generee sans theme narratif")
    prompt = build_prompt(outline, theme_instruction=instruction_theme)
    print(f"-> Prompt construit ({len(prompt)} caracteres). Appel du modele OpenRouter ...")
    histoire = generate_script(prompt)
    histoire = histoire.strip()
    nb_mots = len(histoire.split())
    print(f"-> Histoire generee : {nb_mots} mots, {len(histoire)} caracteres")
    apercu_histoire = histoire[:400] + ("..." if len(histoire) > 400 else "")
    print("--- apercu ---")
    for ligne in apercu_histoire.splitlines():
        print(f"   {ligne}")

    # --- Etape 4 : sous-titres cales sur la duree reelle ----------------
    _titre_etape(4, "Generation des sous-titres cales sur la duree reelle")
    duree = duree_video(chemin_video)
    print(f"-> Duree reelle de la video telechargee : {duree:.2f} s ({formater_ts(duree)})")
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    chemin_srt = os.path.join(DOSSIER_SORTIE, f"{video_id}.srt")
    generate_subtitles(histoire, duree, chemin_srt)
    with open(chemin_srt, encoding="utf-8") as fichier:
        lignes_srt = fichier.read().splitlines()
    nb_blocs = sum(1 for ligne in lignes_srt if "-->" in ligne)
    print(f"-> {nb_blocs} bloc(s) de sous-titres ecrits dans {chemin_srt}")
    print("--- 6 premieres lignes ---")
    for ligne in lignes_srt[:6]:
        print(f"   {ligne}")

    # --- Etape 5 : envoi des sous-titres (backend + VPS) ---------------
    _titre_etape(5, "Envoi des sous-titres (backend HTTP + VPS scp)")

    # 5a. Nouvelle voie : POST des sous-titres au backend. send_subtitles ne
    # leve jamais ; en cas d'echec elle logge un warning et renvoie
    # {"success": False, ...}. Le .srt reste local et le depot scp ci-dessous
    # prend le relais tant que la voie HTTP n'est pas validee en conditions
    # reelles.
    resultat_backend = send_subtitles(video_id, chemin_srt)
    if resultat_backend.get("success"):
        print(
            f"-> Sous-titres envoyes au backend : "
            f"{resultat_backend.get('count')} entree(s)"
        )
    else:
        print(
            f"-> Envoi au backend echoue (on garde le scp) : "
            f"{resultat_backend.get('error')}"
        )

    # 5b. Voie historique conservee en parallele : depot du .srt sur le VPS.
    destination = sync_video.upload(video_id, chemin_srt)
    print(f"-> Sous-titres deposes sur le VPS : {destination}")

    # --- Resume final ---------------------------------------------------
    print()
    print("=" * 70)
    print(f"PIPELINE TERMINE  -  video_id = {video_id}")
    print("=" * 70)
    print(f"  Video source   : {chemin_video} ({taille_mo:.1f} Mo, {duree:.2f} s)")
    print(f"  Frames taguees : {len(outline)}  ({total_tags} tags)")
    print(f"  Histoire       : {nb_mots} mots")
    if resultat_backend.get("success"):
        etat_backend = f"OK ({resultat_backend.get('count')} entrees)"
    else:
        etat_backend = f"echec ({resultat_backend.get('error')})"
    print(f"  Sous-titres    : {chemin_srt} ({nb_blocs} blocs) -> {destination}")
    print(f"  Envoi backend  : {etat_backend}")
    print(f"  Duree totale   : {time.perf_counter() - t0_pipeline:.1f} s")
    print("=" * 70)


if __name__ == "__main__":
    main()
