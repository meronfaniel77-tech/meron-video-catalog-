import json
import urllib.request

# MERON - Recupera gli episodi da Apple Podcasts

PODCAST_ID = "INSERIRE_ID_PODCAST"

def recupera_episodi():
    url = (
        "https://itunes.apple.com/lookup"
        f"?id={PODCAST_ID}&entity=podcastEpisode&limit=200"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MerON/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)

    episodi = []

    for item in data.get("results", []):
        if item.get("kind") != "podcast-episode":
            continue

        episodi.append({
            "id": item.get("trackId"),
            "titolo": item.get("trackName", ""),
            "data": item.get("releaseDate", "")
        })

    print(f"Episodi Apple Podcasts trovati: {len(episodi)}")

    for episodio in episodi[:10]:
        print(
            f"{episodio['id']} - {episodio['titolo']}"
        )

if __name__ == "__main__":
    recupera_episodi()
