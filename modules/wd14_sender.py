#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
wd14_sender.py

Envoi des tags WD14 distincts au backend via HTTP.

Le backend expose POST {BACKEND_URL}/api/montage/videos/{video_id}/wd14-tags
et attend un corps JSON :

    {"tags": [...]}

Tout est tolerant aux pannes, sur le meme principe que
modules/subtitle_sender.py : aucune exception non geree ne remonte. En cas
d'echec (liste vide, backend injoignable, reponse non-2xx, imprevu), la
fonction logge un avertissement et renvoie {"success": False, "error": "..."}.

Fonction publique :
    send_wd14_tags(video_id: int, tags: list[str]) -> dict
        -> {"success": True, "count": N}
        -> {"success": False, "error": "<message>"}

Configuration (fichier .env a la racine du projet) :
    BACKEND_URL   URL de base du backend (defaut : http://localhost:8000)
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BACKEND_URL_DEFAUT = "http://localhost:8000"

# Timeout du POST.
TIMEOUT_POST = 15.0


def _base_url() -> str:
    """URL de base du backend (BACKEND_URL de l'environnement), sans / final.

    Identique a modules/subtitle_sender.py._base_url(). Suppose que le .env a
    deja ete charge (main.py:load_dotenv).
    """
    return os.environ.get("BACKEND_URL", BACKEND_URL_DEFAUT).rstrip("/")


def send_wd14_tags(video_id, tags: "list[str]") -> dict:
    """Envoie les tags WD14 distincts au backend par HTTP POST.

    POST {BACKEND_URL}/api/montage/videos/{video_id}/wd14-tags avec le corps
    {"tags": [...]}. Ne leve jamais : toute panne (liste vide, backend
    injoignable, reponse non-2xx, imprevu) est logguee en warning et
    renvoyee sous la forme {"success": False, "error": "<message>"}.

    Retour :
        {"success": True, "count": N}   ou   {"success": False, "error": "..."}
    """
    try:
        if not tags:
            message = "Aucun tag WD14 a envoyer"
            logger.warning("Envoi des tags WD14 au backend ignore : %s", message)
            return {"success": False, "error": message}

        url = f"{_base_url()}/api/montage/videos/{video_id}/wd14-tags"
        try:
            reponse = httpx.post(url, json={"tags": tags}, timeout=TIMEOUT_POST)
            reponse.raise_for_status()
        except httpx.HTTPError as erreur:
            message = f"POST {url} en echec : {erreur}"
            logger.warning("%s", message)
            return {"success": False, "error": message}

        logger.info("Tags WD14 envoyes au backend : %d tag(s) -> %s", len(tags), url)
        return {"success": True, "count": len(tags)}

    except Exception as erreur:
        message = f"Erreur inattendue lors de l'envoi des tags WD14 : {erreur}"
        logger.warning("%s", message)
        return {"success": False, "error": message}
