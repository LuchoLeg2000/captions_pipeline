#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
theme_selector.py

Choix d'un theme narratif pour l'histoire generee par le pipeline.

Le backend expose GET {BACKEND_URL}/api/themes, qui renvoie une liste de
themes au format {"id", "name", "description", "prompt_instruction"}. Ce
module :
  - recupere cette liste (fetch_themes) ;
  - demande a OpenRouter de choisir le theme le plus adapte aux tags WD14
    detectes (select_theme) ;
  - expose theme_instruction(tags, themes), qui enchaine la selection et
    renvoie directement le `prompt_instruction` a injecter dans le prompt
    d'histoire (cf. modules.script_generator.build_prompt), ou None.

Tout est tolerant aux pannes : backend injoignable, liste de themes vide,
ou appel de selection en echec -> la fonction renvoie une valeur neutre
(liste vide / None) apres avoir logge un avertissement, et le pipeline
continue avec le prompt d'histoire par defaut, sans planter.

Configuration (fichier .env a la racine du projet) :
    BACKEND_URL   URL de base du backend (defaut : http://localhost:8000)
"""

import json
import logging
import os

import httpx

from modules.script_generator import openrouter_chat

logger = logging.getLogger(__name__)

BACKEND_URL_DEFAUT = "http://localhost:8000"


def _base_url() -> str:
    """URL de base du backend (BACKEND_URL de l'environnement), sans / final."""
    return os.environ.get("BACKEND_URL", BACKEND_URL_DEFAUT).rstrip("/")


def fetch_themes() -> "list[dict]":
    """Recupere la liste des themes depuis GET {BACKEND_URL}/api/themes.

    Renvoie la liste des themes (chaque theme est un dict avec au moins les
    cles "name", "description", "prompt_instruction"). En cas d'echec reseau,
    de reponse non-2xx, de corps JSON illisible ou de liste vide : logge un
    avertissement et renvoie [] pour que le pipeline continue sans theme.
    """
    url = f"{_base_url()}/api/themes"
    try:
        reponse = httpx.get(url, timeout=10.0)
        reponse.raise_for_status()
        themes = reponse.json()
    except (httpx.HTTPError, ValueError) as erreur:
        logger.warning(
            "Backend de themes injoignable (%s) : %s -- histoire sans theme.",
            url, erreur,
        )
        return []

    if not isinstance(themes, list) or not themes:
        logger.warning(
            "Aucun theme renvoye par %s -- histoire sans theme.", url
        )
        return []

    return themes


def _extraire_nom(reponse_brute: str) -> str:
    """Extrait le champ "name" d'une reponse JSON du modele de selection.

    Tolere le texte parasite autour du JSON (blocs ```json ... ```, phrase
    d'introduction) en isolant la premiere accolade ouvrante et la derniere
    fermante. Renvoie "" si rien d'exploitable n'est trouve.
    """
    texte = reponse_brute.strip()
    debut = texte.find("{")
    fin = texte.rfind("}")
    if debut == -1 or fin == -1 or fin <= debut:
        return ""
    try:
        donnees = json.loads(texte[debut:fin + 1])
    except ValueError:
        return ""
    if not isinstance(donnees, dict):
        return ""
    nom = donnees.get("name", "")
    return nom.strip() if isinstance(nom, str) else ""


def select_theme(tags: "list[str]", themes: "list[dict]") -> "dict | None":
    """Demande a OpenRouter quel theme convient le mieux aux tags WD14.

    Envoie au modele la liste des tags detectes et le catalogue des themes
    (uniquement "name" et "description") et attend un JSON simple
    {"name": "<nom du theme choisi>"}. Renvoie le dict theme correspondant
    (issu de `themes`), ou None si `themes` est vide, si l'appel echoue, ou
    si la reponse ne designe aucun theme connu -> histoire sans theme.
    """
    if not themes:
        return None

    catalogue = [
        {
            "name": theme.get("name", ""),
            "description": theme.get("description", ""),
        }
        for theme in themes
    ]
    tags_txt = ", ".join(tags) if tags else "(no tags detected)"

    consigne = (
        "You select the single narrative theme that best matches the visual "
        "content of a video. The content is described by image tags.\n"
        f"Detected tags: {tags_txt}\n"
        "Available themes (JSON list of {name, description}):\n"
        f"{json.dumps(catalogue, ensure_ascii=False)}\n"
        "Reply with a JSON object and nothing else, exactly in this form: "
        '{"name": "<one name copied verbatim from the list above>"}'
    )

    try:
        brut = openrouter_chat(
            [{"role": "user", "content": consigne}], max_tokens=100
        )
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as erreur:
        logger.warning(
            "Appel de selection de theme en echec : %s -- histoire sans theme.",
            erreur,
        )
        return None

    nom_choisi = _extraire_nom(brut)
    if not nom_choisi:
        logger.warning(
            "Reponse de selection de theme illisible (%r) -- histoire sans "
            "theme.", brut,
        )
        return None

    for theme in themes:
        if theme.get("name", "").strip().lower() == nom_choisi.lower():
            return theme

    logger.warning(
        "Theme choisi %r absent du catalogue -- histoire sans theme.",
        nom_choisi,
    )
    return None


def theme_instruction(
    tags: "list[str]", themes: "list[dict]"
) -> "str | None":
    """Point d'entree du pipeline : renvoie le `prompt_instruction` du theme
    le mieux adapte aux `tags`, ou None.

    Ne leve jamais : toute panne (selection en echec, theme sans instruction
    exploitable) se traduit par None + un avertissement logge, et le pipeline
    enchaine sur le prompt d'histoire par defaut.
    """
    theme = select_theme(tags, themes)
    if theme is None:
        return None

    instruction = theme.get("prompt_instruction", "")
    if not isinstance(instruction, str) or not instruction.strip():
        logger.warning(
            "Theme %r sans prompt_instruction exploitable -- histoire sans "
            "theme.", theme.get("name"),
        )
        return None

    logger.info("Theme narratif retenu : %s", theme.get("name"))
    return instruction.strip()
