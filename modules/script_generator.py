#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
script_generator.py

Genere le script d'une micro-histoire destinee a une narration TTS.

- build_prompt(theme)    : construit le prompt final envoye au modele.
    `theme` peut etre :
      * une chaine : le sujet libre de l'histoire (comportement d'origine) ;
      * une liste ordonnee de moments `list[tuple[str, list[str]]]`, chaque
        element etant (horodatage, liste de tags) ; le prompt contient alors
        une section "outline" chronologique que l'histoire doit suivre.
- generate_script(prompt) : envoie le prompt a l'API OpenRouter, renvoie le texte.

Configuration (fichier .env a la racine du projet) :
    OPENROUTER_API_KEY   cle API OpenRouter
    OPENROUTER_MODEL     identifiant du modele (ex : moonshotai/kimi-k2:free)
"""

import os
import random

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Points de vue narratifs possibles ; un seul est tire au sort a chaque appel.
POINTS_DE_VUE = ["1st person", "2nd person", "3rd person"]


def _bloc_outline(moments: "list[tuple[str, list[str]]]") -> str:
    """Formate la section 'outline' : un moment par ligne, dans l'ordre recu.

    Chaque ligne vaut "- horodatage: tag1, tag2, ..." ; une liste de tags vide
    est rendue par "(no tags)".
    """
    lignes = ["Outline (chronological order, earliest moment first):"]
    for horodatage, tags in moments:
        tags_txt = ", ".join(tags) if tags else "(no tags)"
        lignes.append(f"- {horodatage}: {tags_txt}")
    return "\n".join(lignes) + "\n"


def build_prompt(
    theme: "str | list[tuple[str, list[str]]]",
    theme_instruction: "str | None" = None,
) -> str:
    """Construit le prompt final pour une micro-histoire destinee au TTS.

    Le prompt impose :
      - l'anglais uniquement ;
      - un point de vue narratif tire au hasard (1st / 2nd / 3rd person),
        insere explicitement dans les consignes ;
      - un format de sortie strict : hook de 15 a 25 mots, puis le separateur
        `---` seul sur sa ligne, puis le corps de l'histoire de 180 a 220 mots ;
      - un style rythme, phrases courtes, adapte a une lecture a voix haute.

    Le sujet depend du type de `theme` :
      - chaine        -> ligne "Subject of the story: <theme>".
      - liste ordonnee de (horodatage, tags) -> consigne de suivre une
        progression + section "Outline" en fin de prompt listant chaque moment
        dans l'ordre chronologique.

    `theme_instruction`, s'il est fourni, est une consigne de ton narratif
    (le `prompt_instruction` d'un theme renvoye par le backend, cf.
    modules/theme_selector.py) inseree comme une regle supplementaire du
    prompt. A None (defaut), le prompt reste identique a la version d'origine.
    """
    point_de_vue = random.choice(POINTS_DE_VUE)

    if isinstance(theme, str):
        ligne_sujet = f"- Subject of the story: {theme}.\n"
        outline = ""
    else:
        ligne_sujet = (
            "- Subject of the story: write in the style of short erotica captions commonly used "
            "for adult short-form video content. INVENT an original scenario with specific "
            "characters and a clear premise - do not just describe or caption what is shown.\n"
            "- CRITICAL sentence style: use very short, fragmented, punchy sentences, often "
            "WITHOUT a full subject or verb, like a string of quick beats rather than flowing "
            "prose. Example of the target rhythm: \"No panties. No warnings. Just her ass in the "
            "air.\" or \"The bedroom was suicide. The hallway was worse.\" Most sentences should be "
            "under 8 words. Avoid long connected sentences with multiple clauses.\n"
            "- Weave in one short line of dialogue in quotes for impact, not a full conversation.\n"
            "- Include explicit sensory and physical detail, but only details that build the "
            "fantasy and narrative - never a literal description of what is visually shown.\n"
            "- Be explicit and graphic about physical actions and sexual acts, not just "
            "suggestive or implied - describe what is actually happening in direct, unambiguous "
            "terms, while keeping sentences short and punchy.\n"
            "- Start in medias res, no slow scene-setting.\n"
            "- End on a sharp, punchy final line, ideally with a twist, irony, or a reveal.\n"
            "- The visual tags below are only a loose reference for pacing and setting - they are "
            "NOT a script to follow or describe moment by moment. Invent freely.\n"
        )
        outline = "\n" + _bloc_outline(theme)

    if theme_instruction and theme_instruction.strip():
        ligne_theme = (
            "- Narrative tone to follow, applied consistently to the whole "
            f"story without breaking any rule above: {theme_instruction.strip()}\n"
        )
    else:
        ligne_theme = ""

    return (
        "You are a short-story writer for text-to-speech (TTS) narration.\n"
        "\n"
        "Follow every rule below exactly:\n"
        "- Write in English only.\n"
        f"- Narrative point of view: {point_de_vue}. "
        "Keep this point of view consistently from the first word to the last.\n"
        f"{ligne_sujet}"
        "- Output format, exactly and in this order:\n"
        "    1. A hook of 15 to 25 words.\n"
        "    2. A line containing only the separator ---\n"
        "    3. The story body, between 180 and 220 words.\n"
        "- Do not add any title, label, word count, comment or text outside "
        "this format.\n"
        "- Style: fast-paced, short sentences, concrete images, easy to follow "
        "when read aloud by a TTS voice.\n"
        f"{ligne_theme}"
        f"{outline}"
    )


def split_hook_and_body(script_text: str) -> "tuple[str, str]":
    """Separe le hook et le corps d'un script genere par generate_script().

    Le format attendu est : le hook, puis une ligne contenant uniquement le
    separateur `---`, puis le corps de l'histoire (cf. build_prompt()).

    Renvoie le tuple (hook, corps), chaque partie nettoyee des espaces de
    debut/fin. Si aucun separateur `---` seul sur sa ligne n'est trouve, le
    hook est vide et tout le texte est renvoye comme corps.
    """
    lignes = script_text.splitlines()
    for i, ligne in enumerate(lignes):
        if ligne.strip() == "---":
            hook = "\n".join(lignes[:i]).strip()
            corps = "\n".join(lignes[i + 1:]).strip()
            return hook, corps
    return "", script_text.strip()


def openrouter_chat(messages: "list[dict]", max_tokens: int = 1000) -> str:
    """Envoie `messages` (format chat OpenRouter) au modele et renvoie le
    contenu texte de la reponse.

    Lit OPENROUTER_API_KEY et OPENROUTER_MODEL dans l'environnement ; il faut
    donc avoir charge le .env au prealable (cf. tools/test_story.py). Sert de
    brique commune a generate_script() et a modules/theme_selector.py.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY absent de l'environnement.")
    if not model:
        raise RuntimeError("OPENROUTER_MODEL absent de l'environnement.")

    reponse = httpx.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        },
        timeout=120.0,
    )
    reponse.raise_for_status()
    donnees = reponse.json()
    choix = donnees["choices"][0]
    contenu = choix["message"].get("content")
    if contenu is None:
        raison = choix.get("finish_reason", "inconnue")
        refus = choix["message"].get("refusal")
        raise RuntimeError(
            f"OpenRouter a renvoye un contenu vide (finish_reason={raison}, refusal={refus}). "
            f"Reponse brute: {donnees}"
        )
    return contenu


def generate_script(prompt: str) -> str:
    """Envoie `prompt` a l'API OpenRouter et renvoie le texte genere.

    Lit OPENROUTER_API_KEY et OPENROUTER_MODEL dans l'environnement ; il faut
    donc avoir charge le .env au prealable (cf. tools/test_story.py).
    """
    # Un hook + ~220 mots tiennent tres largement dans 1000 tokens ; borne
    # aussi le cout et evite un defaut provider hors limites.
    return openrouter_chat([{"role": "user", "content": prompt}], max_tokens=1000)
