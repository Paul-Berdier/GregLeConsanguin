import os
from playlist_manager import PlaylistManager


def test_add_skip_stop(tmp_path):
    # Utilise un fichier JSON temporaire pour ne pas polluer le repo
    pm = PlaylistManager('testguild')
    # Redirige le fichier vers un dossier temporaire
    pm.file = os.path.join(tmp_path, 'playlist_test.json')
    pm.save()
    # Ajoute une piste
    pm.add({'title': 'Chanson 1', 'url': 'https://example.com/1'})
    queue = pm.get_queue()
    assert len(queue) == 1
    assert queue[0]['title'] == 'Chanson 1'
    # Skip vide la playlist
    pm.skip()
    assert pm.get_queue() == []
    # Ajoute deux pistes puis stop vide tout
    pm.add({'title': 'Chanson 2', 'url': 'https://example.com/2'})
    pm.add({'title': 'Chanson 3', 'url': 'https://example.com/3'})
    assert len(pm.get_queue()) == 2
    pm.stop()
    assert pm.get_queue() == []