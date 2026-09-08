#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
frame_tagger_test.py

Banc de test : extrait une frame toutes les 8 secondes d'une video, puis
tague chaque frame avec le modele WD14 ConvNeXt v2 (ONNX) execute via
onnxruntime + DirectML (GPU) avec repli automatique sur le CPU.

Usage :
    python tools/frame_tagger_test.py chemin_vers_video.mp4

Dependances (deja presentes dans le venv du projet) :
    ffmpeg (sur le PATH), onnxruntime-directml, opencv-python,
    huggingface_hub, numpy
"""

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download

# --- Parametres --------------------------------------------------------------

INTERVAL_SECONDES = 8          # 1 frame extraite toutes les 8 s
SEUIL_CONFIANCE = 0.35         # seuil minimal pour retenir un tag
HF_REPO = "SmilingWolf/wd-v1-4-convnext-tagger-v2"
MODEL_FILE = "model.onnx"
TAGS_FILE = "selected_tags.csv"
PROVIDERS = ["DmlExecutionProvider", "CPUExecutionProvider"]


# --- Etape 1 : extraction des frames avec ffmpeg ---------------------------

def extraire_frames(video_path, dossier_sortie):
    """Extrait une image toutes les INTERVAL_SECONDES via ffmpeg.

    Retourne la liste triee des chemins de frames generees.
    Le filtre `fps=1/INTERVAL` conserve une frame par tranche de N secondes ;
    la frame i (0-indexee) correspond donc a t = i * INTERVAL secondes.
    """
    motif = os.path.join(dossier_sortie, "frame_%05d.jpg")
    cmd = [
        "ffmpeg",
        "-nostdin",              # ne pas attendre d'entree clavier
        "-loglevel", "error",    # sortie ffmpeg silencieuse (erreurs seules)
        "-y",                    # ecraser sans demander
        "-i", video_path,
        "-vf", f"fps=1/{INTERVAL_SECONDES}",
        "-qscale:v", "2",        # qualite JPEG elevee
        motif,
    ]
    print(f"[ffmpeg] extraction d'une frame toutes les {INTERVAL_SECONDES} s ...")
    subprocess.run(cmd, check=True)

    frames = sorted(
        os.path.join(dossier_sortie, f)
        for f in os.listdir(dossier_sortie)
        if f.lower().endswith(".jpg")
    )
    print(f"[ffmpeg] {len(frames)} frame(s) extraite(s).")
    return frames


# --- Etape 2 : chargement du modele WD14 ----------------------------------

def charger_modele():
    """Telecharge (au 1er lancement) et charge le modele ONNX + la liste de tags.

    hf_hub_download met les poids en cache local ; les lancements suivants
    n'entrainent aucun telechargement.
    """
    print(f"[modele] recuperation de {HF_REPO} (cache Hugging Face) ...")
    model_path = hf_hub_download(repo_id=HF_REPO, filename=MODEL_FILE)
    tags_path = hf_hub_download(repo_id=HF_REPO, filename=TAGS_FILE)

    session = ort.InferenceSession(model_path, providers=PROVIDERS)
    actifs = session.get_providers()
    print(f"[modele] providers actifs : {actifs}")
    if "DmlExecutionProvider" in actifs:
        print("[modele] -> execution sur GPU via DirectML.")
    else:
        print("[modele] -> DirectML indisponible, execution sur CPU.")

    # Lecture de selected_tags.csv : colonnes tag_id,name,category,count
    # category 0 = tags generaux, 4 = personnages, 9 = rating
    with open(tags_path, newline="", encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    noms_tags = [r["name"] for r in lignes]
    idx_general = [i for i, r in enumerate(lignes) if r["category"] == "0"]
    idx_personnage = [i for i, r in enumerate(lignes) if r["category"] == "4"]

    # Taille d'entree attendue par le modele (fallback 448)
    forme = session.get_inputs()[0].shape  # ex : [None, 448, 448, 3]
    taille = next((d for d in forme if isinstance(d, int) and d > 3), 448)

    return session, noms_tags, idx_general, idx_personnage, taille


# --- Etape 3 : pretraitement d'une frame --------------------------------

def _pad_carre(img, taille_cible):
    """Ajoute des bords blancs pour rendre l'image carree (logique SmilingWolf)."""
    h, w = img.shape[:2]
    cote = max(h, w, taille_cible)
    haut = (cote - h) // 2
    bas = cote - h - haut
    gauche = (cote - w) // 2
    droite = cote - w - gauche
    return cv2.copyMakeBorder(
        img, haut, bas, gauche, droite,
        cv2.BORDER_CONSTANT, value=(255, 255, 255),
    )


def preparer_frame(chemin, taille):
    """Charge une frame et la met au format attendu par le modele.

    Le modele WD14 v2 attend : image BGR, carree, taille x taille, NHWC,
    float32 avec des valeurs 0-255 (pas de normalisation).
    cv2.imread renvoie deja du BGR, aucune conversion de canaux necessaire.
    """
    img = cv2.imread(chemin, cv2.IMREAD_COLOR)  # BGR
    if img is None:
        raise RuntimeError(f"Frame illisible : {chemin}")
    img = _pad_carre(img, taille)
    interp = cv2.INTER_AREA if img.shape[0] > taille else cv2.INTER_CUBIC
    img = cv2.resize(img, (taille, taille), interpolation=interp)
    img = img.astype(np.float32)
    return np.expand_dims(img, axis=0)  # (1, taille, taille, 3)


# --- Etape 4 : tagging + mesures de temps ------------------------------

def formater_ts(secondes):
    h, reste = divmod(int(secondes), 3600)
    m, s = divmod(reste, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def tagger(session, frames, noms_tags, idx_general, idx_personnage, taille):
    nom_entree = session.get_inputs()[0].name
    nom_sortie = session.get_outputs()[0].name
    indices_tags = idx_general + idx_personnage

    resultats = []
    durees = []
    t0_global = time.perf_counter()

    for i, chemin in enumerate(frames):
        timestamp = i * INTERVAL_SECONDES
        entree = preparer_frame(chemin, taille)

        t0 = time.perf_counter()
        probs = session.run([nom_sortie], {nom_entree: entree})[0][0]
        durees.append(time.perf_counter() - t0)

        tags = [
            (noms_tags[j], float(probs[j]))
            for j in indices_tags
            if probs[j] >= SEUIL_CONFIANCE
        ]
        tags.sort(key=lambda x: x[1], reverse=True)
        resultats.append((timestamp, tags))

    total = time.perf_counter() - t0_global
    return resultats, durees, total


# --- Affichage final --------------------------------------------------------

def afficher(resultats, durees, total):
    print("\n" + "=" * 70)
    print("RESULTATS DU TAGGING")
    print("=" * 70)
    for timestamp, tags in resultats:
        if tags:
            details = ", ".join(f"{nom} ({score:.2f})" for nom, score in tags)
        else:
            details = "(aucun tag au-dessus du seuil)"
        print(f"\n[{formater_ts(timestamp)}]  {details}")

    n = len(durees)
    moyenne = (sum(durees) / n) if n else 0.0
    print("\n" + "=" * 70)
    print(f"Frames traitees      : {n}")
    print(f"Temps total          : {total:.2f} s")
    print(f"Temps moyen / frame  : {moyenne * 1000:.1f} ms  ({moyenne:.3f} s)")
    print("=" * 70)


# --- Point d'entree -------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print("Usage : python tools/frame_tagger_test.py chemin_vers_video.mp4")
        sys.exit(1)

    video_path = sys.argv[1]
    if not os.path.isfile(video_path):
        print(f"Fichier introuvable : {video_path}")
        sys.exit(1)
    if shutil.which("ffmpeg") is None:
        print("ffmpeg introuvable sur le PATH.")
        sys.exit(1)

    dossier_tmp = tempfile.mkdtemp(prefix="frame_tagger_")
    try:
        frames = extraire_frames(video_path, dossier_tmp)
        if not frames:
            print("Aucune frame extraite, arret.")
            sys.exit(1)

        session, noms_tags, idx_general, idx_personnage, taille = charger_modele()
        resultats, durees, total = tagger(
            session, frames, noms_tags, idx_general, idx_personnage, taille
        )
        afficher(resultats, durees, total)
    finally:
        shutil.rmtree(dossier_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
