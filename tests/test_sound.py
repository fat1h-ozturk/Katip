from katip.sound import SoundPlayer

def test_sound_cache_initialization():
    player = SoundPlayer(enabled=False)
    assert "start" in player._cache
    assert "stop" in player._cache
    assert "success" in player._cache
    assert "error" in player._cache
    assert len(player._cache["start"]) > 100
