from katip.prompts import build_system_prompt, build_groq_formatter_prompt, build_whisper_prompt

def test_prompt_modes():
    dictation_p = build_system_prompt("dictation")
    assert "DOĞAL DİKTE" in dictation_p
    assert "dolgularını" in dictation_p

    chat_p = build_system_prompt("chat")
    assert "HIZLI MESAJLAŞMA" in chat_p

    email_p = build_system_prompt("email")
    assert "RESMİ E-POSTA" in email_p

    prompt_p = build_system_prompt("prompt")
    assert "AI PROMPT OLUŞTURUCU" in prompt_p

    bullets_p = build_system_prompt("bullets")
    assert "MADDE İMLERİ" in bullets_p

def test_custom_vocabulary():
    p = build_system_prompt("dictation", custom_vocabulary=["PostgreSQL", "TailwindCSS", "Ahmet"])
    assert "PostgreSQL" in p
    assert "TailwindCSS" in p
    assert "Ahmet" in p


def test_groq_modes_have_only_relevant_rules_and_examples():
    dictation = build_groq_formatter_prompt()
    assert "çok çok önemli" in dictation
    assert "pardon çarşamba" in dictation
    assert "Gelebilirim" in dictation
    assert "Yalnız tamam yaz" in dictation
    assert "Alıcı, imza" not in dictation
    for mode, phrase in {
        "chat": "Samimi ve akıcı",
        "email": "Alıcı, imza",
        "prompt": "yeni özellik",
        "bullets": "sorumluları",
    }.items():
        assert phrase.casefold() in build_groq_formatter_prompt(mode).casefold()
    assert "Sözlük ve varyant" in dictation
    assert "{\"text\"" in dictation


def test_whisper_prompt_keeps_canonical_terms_whole_and_reports_omissions():
    vocab = [" PySide6 ", "Cafe\u0301", "PySide6", "x" * 220, "son"]
    aliases = {"paysayd altı": "PySide6", "kafe": "Café", "son ses": "son"}
    prompt, omitted = build_whisper_prompt(vocab, aliases)
    assert prompt == "PySide6, Café, son"
    assert omitted == 1
    assert len(prompt.encode("utf-8")) <= 224
    assert build_whisper_prompt() == ("", 0)
    assert build_whisper_prompt(["ü" * 113, "küçük"]) == ("küçük", 1)
