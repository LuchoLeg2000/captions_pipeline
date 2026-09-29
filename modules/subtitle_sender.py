#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
subtitle_sender.py

Envoi des sous-titres au backend via HTTP, en remplacement (a terme) du
depot scp du fichier .srt sur le VPS (cf. tools/sync_video.py:upload).

Le backend expose POST {BACKEND_URL}/api/montage/videos/{video_id}/subtitles
et attend un corps JSON :

    {"subtitles": [{"start": <float s>, "end": <float s>, "text": <str>}, ...]}

Ce module lit le .srt genere par modules/subtitle_generator.py (horodatages
au format "HH:MM:SS,mmm --> HH:MM:SS,mmm", blocs separes par une ligne vide),
convertit chaque bloc en une entree {start, end, text} avec les temps en
secondes (float), puis effectue le POST.

Tout est tolerant aux pannes, sur le meme principe que
modules/theme_selector.py : aucune exception non geree ne remonte. En cas
d'echec (fichier absent, .srt vide, backend injoignable, reponse non-2xx,
imprevu), la fonction logge un avertissement et renvoie
{"success": False, "error": "..."} ; le .srt reste disponible localement et
le depot scp continue de servir de filet.

Fonction publique :
    send_subtitles(video_id: int, srt_path: str) -> dict
        -> {"success": True, "count": N}
        -> {"success": False, "error": "<message>"}

Configuration (fichier .env a la racine du projet) :
    BACKEND_URL   URL de base du backend (defaut : http://localhost:8000)
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

BACKEND_URL_DEFAUT = "http://localhost:8000"

# Timeout du POST : un peu large, la liste de sous-titres peut etre longue et
# le backend peut faire un traitement synchrone a la reception.
TIMEOUT_POST = 30.0

# Ligne d'horodatage SRT : "HH:MM:SS,mmm --> HH:MM:SS,mmm".
# On tolere '.' comme separateur des millisecondes et un nombre variable de
# chiffres pour l'heure et les millisecondes.
_LIGNE_TEMPS = re.compile(
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _base_url() -> str:
    """URL de base du backend (BACKEND_URL de l'environnement), sans / final.

    Identique a modules/theme_selector.py._base_url(). Suppose que le .env a
    deja ete charge (main.py:load_dotenv).
    """
    return os.environ.get("BACKEND_URL", BACKEND_URL_DEFAUT).rstrip("/")


def _temps_vers_secondes(heures: str, minutes: str, secs: str, ms: str) -> float:
    """Convertit les 4 groupes d'un horodatage SRT en secondes (float).

    `ms` peut avoir 1 a 3 chiffres ; il est complete a droite avec des zeros
    ("," + "4" designe 400 ms, pas 4 ms).
    """
    millisecondes = int(ms.ljust(3, "0"))
    return int(heures) * 3600 + int(minutes) * 60 + int(secs) + millisecondes / 1000.0


def _parser_srt(contenu: str) -> "list[dict]":
    """Transforme le texte d'un .srt en liste d'entrees {start, end, text}.

    Un bloc SRT vaut : une ligne d'index optionnelle, une ligne d'horodatage
    "debut --> fin", puis une ou plusieurs lignes de texte. Les blocs sont
    separes par une ou plusieurs lignes vides.

    Les blocs sans ligne d'horodatage valide ou sans texte sont ignores en
    silence (mieux vaut envoyer les entrees exploitables que rien). `start` et
    `end` sont des float (secondes) ; le texte multi-lignes est rejoint par
    des sauts de ligne.
    """
    entrees = []
    for bloc in re.split(r"\r?\n[ \t]*\r?\n", contenu.strip()):
        lignes = [ligne for ligne in bloc.splitlines() if ligne.strip() != ""]
        if not lignes:
            continue

        # Localise la ligne d'horodatage (elle contient "-->").
        index_temps = next(
            (i for i, ligne in enumerate(lignes) if "-->" in ligne), None
        )
        if index_temps is None:
            continue

        correspondance = _LIGNE_TEMPS.search(lignes[index_temps])
        if correspondance is None:
            continue

        groupes = correspondance.groups()
        debut = _temps_vers_secondes(*groupes[:4])
        fin = _temps_vers_secondes(*groupes[4:])

        texte = "\n".join(lignes[index_temps + 1:]).strip()
        if not texte:
            continue

        entrees.append({"start": debut, "end": fin, "text": texte})

    return entrees


def send_subtitles(video_id: int, srt_path: str) -> dict:
    """Parse `srt_path` et envoie les sous-titres au backend par HTTP POST.

    POST {BACKEND_URL}/api/montage/videos/{video_id}/subtitles avec le corps
    {"subtitles": [{"start": float, "end": float, "text": str}, ...]}.

    Ne leve jamais : toute panne (fichier introuvable, .srt vide ou illisible,
    backend injoignable, reponse non-2xx, imprevu) est logguee en warning et
    renvoyee sous la forme {"success": False, "error": "<message>"}. Le .srt
    reste disponible localement et le depot scp sert de filet.

    Retour :
        {"success": True, "count": N}   ou   {"success": False, "error": "..."}
    """
    try:
        if not os.path.isfile(srt_path):
            message = f"Fichier .srt introuvable : {srt_path}"
            logger.warning(
                "Envoi des sous-titres au backend ignore : %s", message
            )
            return {"success": False, "error": message}

        try:
            with open(srt_path, encoding="utf-8") as fichier:
                contenu = fichier.read()
        except OSError as erreur:
            message = f"Lecture du .srt impossible ({srt_path}) : {erreur}"
            logger.warning(
                "Envoi des sous-titres au backend ignore : %s -- le .srt reste "
                "disponible localement.", message
            )
            return {"success": False, "error": message}

        entrees = _parser_srt(contenu)
        if not entrees:
            message = f"Aucune entree de sous-titre exploitable dans {srt_path}"
            logger.warning(
                "Envoi des sous-titres au backend ignore : %s", message
            )
            return {"success": False, "error": message}

        url = f"{_base_url()}/api/montage/videos/{video_id}/subtitles"
        try:
            reponse = httpx.post(
                url, json={"subtitles": entrees}, timeout=TIMEOUT_POST
            )
            reponse.raise_for_status()
        except httpx.HTTPError as erreur:
            message = f"POST {url} en echec : {erreur}"
            logger.warning(
                "%s -- le .srt reste disponible localement (%s).",
                message, srt_path,
            )
            return {"success": False, "error": message}

        logger.info(
            "Sous-titres envoyes au backend : %d entree(s) -> %s",
            len(entrees), url,
        )
        return {"success": True, "count": len(entrees)}

    except Exception as erreur:  # garde-fou : ne jamais laisser filer une exception
        message = f"Erreur inattendue lors de l'envoi des sous-titres : {erreur}"
        logger.warning(
            "%s -- le .srt reste disponible localement (%s).",
            message, srt_path,
        )
        return {"success": False, "error": message}
