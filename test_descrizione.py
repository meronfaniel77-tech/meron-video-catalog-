
import json
import subprocess
import sys

VIDEO_URL = (
    "https://www.youtube.com/watch?v=8TskZiL2mTE"
)

print("MERON - TEST DESCRIZIONE YOUTUBE")

comando = [
    sys.executable,
    "-m",
    "yt_dlp",
    "--skip-download",
    "--dump-single-json",
    "--no-warnings",
    VIDEO_URL
]

risultato = subprocess.run(
    comando,
    capture_output=True,
    text=True,
    timeout=60
)

if risultato.returncode != 0:
    print("ERRORE RECUPERO VIDEO")
    print(risultato.stderr[-1500:])
    sys.exit(1)

dati = json.loads(risultato.stdout)

print("Titolo:", dati.get("title", ""))

descrizione = dati.get("description") or ""

print("Lunghezza descrizione:", len(descrizione))
print("Descrizione:")
print(descrizione[:1500])

if descrizione:
    print("TEST RIUSCITO")
else:
    print("DESCRIZIONE NON DISPONIBILE")
