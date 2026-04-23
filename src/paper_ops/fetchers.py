from bs4 import BeautifulSoup
import requests


def fetch_url_metadata(url: str) -> dict[str, str]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    return {"title": title or url}
