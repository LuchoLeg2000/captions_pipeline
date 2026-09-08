#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
subtitle_generator.py

Genere un fichier de sous-titres .srt a partir du texte d'une histoire.

Principe : on ne dispose pas (encore) d'un alignement audio mot a mot, donc
les sous-titres sont repartis *uniformement* sur toute la duree de la video.
Le texte complet (hook + corps) est decoupe en petits groupes de 3 a 5 mots,
et chaque groupe recoit une tranche de temps egale.

Fonction publique :
    generate_subtitles(story_text, video_duration, output_path) -> output_path
"""

import os

from modules.script_generator import split_hook_and_body


def _grouper_mots(mots: "list[str]", cible: int = 4) -> "list[list[str]]":
    """Repartit `mots` en groupes de taille aussi egale que possible.

    On vise `cible` mots par groupe, puis on ajuste le nombre de groupes pour
    garantir que chaque groupe contienne entre 3 et 5 mots (tant que le texte
    est assez long pour le permettre). Les mots sont ensuite distribues de
    facon equilibree : les tailles de deux groupes different d'au plus 1.
    """
    total = len(mots)
    if total == 0:
        return []
    if total <= 5:
        return [mots]

    nombre = max(1, round(total / cible))
    # Aucun groupe ne doit depasser 5 mots.
    while -(-total // nombre) > 5:  # -(-a // b) = plafond de a / b
        nombre += 1
    # Aucun groupe ne doit descendre sous 3 mots (sauf texte trop court).
    while nombre > 1 and total / nombre < 3:
        nombre -= 1

    base, reste = divmod(total, nombre)
    groupes = []
    i = 0
    for k in range(nombre):
        taille = base + (1 if k < reste else 0)
        groupes.append(mots[i:i + taille])
        i += taille
    return groupes


def _srt_timestamp(secondes: float) -> str:
    """Convertit un nombre de secondes en horodatage SRT 'HH:MM:SS,mmm'."""
    if secondes < 0:
        secondes = 0.0
    millisecondes = int(round(secondes * 1000))
    heures, millisecondes = divmod(millisecondes, 3_600_000)
    minutes, millisecondes = divmod(millisecondes, 60_000)
    secs, millisecondes = divmod(millisecondes, 1_000)
    return f"{heures:02d}:{minutes:02d}:{secs:02d},{millisecondes:03d}"


def generate_subtitles(
    story_text: str, video_duration: float, output_path: str
) -> str:
    """Genere un fichier .srt reparti uniformement sur la duree de la video.

    Etapes :
      1. separe le hook et le corps via split_hook_and_body() ;
      2. recolle les deux parties et decoupe tout le texte en groupes
         de 3 a 5 mots ;
      3. attribue a chaque groupe une tranche de temps egale
         (video_duration / nombre de groupes) ;
      4. ecrit le tout au format SRT dans output_path.

    Retourne output_path.
    """
    hook, corps = split_hook_and_body(story_text)
    texte_complet = " ".join(part for part in (hook, corps) if part).strip()

    mots = texte_complet.split()
    groupes = _grouper_mots(mots)
    if not groupes:
        raise ValueError("story_text ne contient aucun mot exploitable.")

    if video_duration <= 0:
        raise ValueError("video_duration doit etre strictement positif.")

    tranche = video_duration / len(groupes)

    blocs = []
    for index, groupe in enumerate(groupes):
        debut = index * tranche
        fin = (index + 1) * tranche
        blocs.append(
            f"{index + 1}\n"
            f"{_srt_timestamp(debut)} --> {_srt_timestamp(fin)}\n"
            f"{' '.join(groupe)}\n"
        )

    dossier = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(dossier, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as fichier:
        fichier.write("\n".join(blocs))

    return output_path
