from . import youtube, soundcloud  # ajoute d'autres si besoin

EXTRACTORS = [youtube, soundcloud]

def get_extractor(url: str):
    for ext in EXTRACTORS:
        if ext.is_valid(url):
            return ext
    return None  # ou fallback si souhaité

def get_search_module(source_name: str):
    for ext in EXTRACTORS:
        if ext.__name__.endswith(source_name):
            return ext
    return None
