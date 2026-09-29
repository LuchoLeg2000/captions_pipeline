import time
import subprocess
import httpx

BACKEND_URL = "https://yournextscene.leger-labs.dev"

data = httpx.get(f"{BACKEND_URL}/api/montage/caption-queue", timeout=15).json()

if not data:
    print("Aucune video en attente de sous-titres.")
else:
    print(f"{len(data)} video(s) en attente. Traitement en cours...\n")
    for video in data:
        video_id = video["id"]
        titre = video.get("titre", "")
        print(f"--- Video {video_id} ({titre}) ---")
        result = subprocess.run(["python", "main.py", str(video_id)])
        if result.returncode != 0:
            print(f"/!\\ Echec pour la video {video_id}, on continue avec la suivante.\n")
        else:
            print(f"OK pour la video {video_id}.\n")
        time.sleep(2)

    print("Toutes les videos de la file ont ete traitees.")