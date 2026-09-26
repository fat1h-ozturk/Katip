from katip.injector import TextInjector

def test_injector_clipboard():
    injector = TextInjector()
    test_str = "Katip Test String 123"
    assert injector.set_clipboard(test_str) is True
    assert injector.get_current_clipboard() == test_str

def test_injector_clipboard_from_worker_thread():
    import threading
    injector = TextInjector()
    test_str = "Threaded Clipboard Test 456"
    success = []

    def worker():
        success.append(injector.set_clipboard(test_str))

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert success == [True]
    assert injector.get_current_clipboard() == test_str
