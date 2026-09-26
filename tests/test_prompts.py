from katip.prompts import build_system_prompt

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
