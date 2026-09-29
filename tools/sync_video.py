#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sync_video.py

Echange de fichiers avec le VPS de test (178.104.242.50) via scp :
  - download : recupere {video_id}_source.mp4 depuis
    /mnt/storagebox/yournextscene/downloads/ vers le dossier local downloads/ ;
  - upload   : envoie un fichier .srt local vers
    /mnt/storagebox/yournextscene/subtitles/{video_id}.srt sur le VPS.

scp est appele en sous-processus (subprocess). Sa sortie n'est pas
capturee : scp affiche alors lui-meme sa barre de progression dans le
terminal. On encadre l'appel de messages de debut / fin.

Usage :
    python tools/sync_video.py download 123456
    python tools/sync_video.py upload 123456 output/test_subs.srt
"""

import os
import shutil
import subprocess
import sys

# Racine du projet, pour resoudre downloads/ quel que soit le repertoire courant.
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VPS = "root@178.104.242.50"
DOSSIER_DOWNLOADS_VPS = "/mnt/storagebox/yournextscene/downloads"
DOSSIER_SUBTITLES_VPS = "/mnt/storagebox/yournextscene/subtitles"
DOSSIER_DOWNLOADS_LOCAL = os.path.join(RACINE, "downloads")


def _verifier_scp():
    """Arrete le script avec un message clair si scp est absent du PATH."""
    if shutil.which("scp") is None:
        raise SystemExit(
            "scp introuvable sur le PATH. Sur Windows, scp est fourni avec "
            "OpenSSH (Parametres > Applications > Fonctionnalites facultatives)."
        )


def _lancer_scp(source, destination):
    """Execute `scp source destination` en laissant scp ecrire dans le terminal.

    Leve subprocess.CalledProcessError si scp renvoie un code non nul.
    """
    _verifier_scp()
    # -o BatchMode=yes : echoue tout de suite au lieu de demander un mot de
    # passe si la cle SSH n'est pas acceptee (pas de blocage interactif).
    subprocess.run(
        ["scp", "-o", "BatchMode=yes", source, destination],
        check=True,
    )


def download(video_id):
    """Telecharge {video_id}_source.mp4 depuis le VPS vers downloads/.

    Renvoie le chemin local (str) du fichier telecharge.
    """
    video_id = str(video_id)
    nom_fichier = f"{video_id}_source.mp4"
    source = f"{VPS}:{DOSSIER_DOWNLOADS_VPS}/{nom_fichier}"
    destination = os.path.join(DOSSIER_DOWNLOADS_LOCAL, nom_fichier)

    os.makedirs(DOSSIER_DOWNLOADS_LOCAL, exist_ok=True)

    print(f"[download] Recuperation de {source}")
    print(f"[download] Vers {destination}")
    _lancer_scp(source, destination)
    print(f"[download] Termine : {destination}")

    return destination


def upload(video_id, chemin_srt):
    """Envoie un fichier .srt local vers /data/pipeline/subtitles/{video_id}.srt.

    Renvoie le chemin distant (str) du fichier depose sur le VPS.
    """
    video_id = str(video_id)
    if not os.path.isfile(chemin_srt):
        raise SystemExit(f"Fichier .srt introuvable : {chemin_srt}")

    destination_distante = f"{DOSSIER_SUBTITLES_VPS}/{video_id}.srt"
    destination = f"{VPS}:{destination_distante}"

    print(f"[upload] Envoi de {chemin_srt}")
    print(f"[upload] Vers {destination}")
    _lancer_scp(chemin_srt, destination)
    print(f"[upload] Termine : {destination}")

    return destination_distante


def main(argv):
    if len(argv) < 2:
        raise SystemExit(
            "Usage :\n"
            "    python tools/sync_video.py download <video_id>\n"
            "    python tools/sync_video.py upload <video_id> <chemin_srt>"
        )

    action = argv[1]

    if action == "download":
        if len(argv) != 3:
            raise SystemExit("Usage : python tools/sync_video.py download <video_id>")
        download(argv[2])
    elif action == "upload":
        if len(argv) != 4:
            raise SystemExit(
                "Usage : python tools/sync_video.py upload <video_id> <chemin_srt>"
            )
        upload(argv[2], argv[3])
    else:
        raise SystemExit(f"Action inconnue : {action!r} (attendu : download ou upload)")


if __name__ == "__main__":
    main(sys.argv)
