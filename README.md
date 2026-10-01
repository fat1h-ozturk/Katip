# 🎙️ Katip

**Katip**, **Linux**, **Windows** ve **macOS** için geliştirilmiş, **Wispr Flow** ve **SuperWhisper** alternatifi, ultra hızlı ve akıllı bir sesli dikte masaüstü asistanıdır.

Mikrofonunuzdan konuşmanızı dinler; anlamı koruyarak gereksiz konuşma dolgularını ve dilbilgisi hatalarını düzenler. Aktif pencereye (kod editörü, tarayıcı, Word, sohbet uygulamaları vb.) doğrudan yazar.

---

## 📥 Hazır Paketleri İndir

Katip tamamen bağımsız (**standalone**) paketler olarak yayınlanmaktadır; bilgisayarınıza Python veya harici kütüphane yüklemenize gerek yoktur.

| İşletim Sistemi | Paket | Kurulum Yöntemi |
| :--- | :--- | :--- |
| **Fedora Linux (x86_64)** | [Katip-Fedora-x86_64.rpm](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-Fedora-x86_64.rpm) | `sudo dnf install ./Katip-Fedora-x86_64.rpm` *(veya çift tıkla kur)* |
| **Arch Linux (x86_64)** | [Katip-ArchLinux-x86_64.pkg.tar.zst](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-ArchLinux-x86_64.pkg.tar.zst) | `sudo pacman -U ./Katip-ArchLinux-x86_64.pkg.tar.zst` |
| **Windows 10/11 (x64)** | [Katip-Windows-x64.exe](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-Windows-x64.exe) | İndirin ve doğrudan çift tıklayarak çalıştırın |
| **macOS (Apple Silicon M1..M4)** | [Katip-macOS-arm64.dmg](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-macOS-arm64.dmg) | `.dmg` dosyasını açıp Applications klasörüne sürükleyin |
| **macOS (Intel)** | [Katip-macOS-x64.dmg](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-macOS-x64.dmg) | `.dmg` dosyasını açıp Applications klasörüne sürükleyin |

> [!NOTE]
> macOS'ta uygulama ilk açılışta Sistem Ayarları'ndan Mikrofon ve Erişilebilirlik izni isteyebilir.

---

## ✨ Temel Özellikler

- **Çapraz Platform Desteği:** Linux (KDE Plasma Wayland/GNOME/Hyprland), Windows (10/11) ve macOS (Apple Silicon & Intel).
- **Zengin Yapay Zeka Modeli Seçenekleri:**
  - **Google Gemini:** Çok modlu (multimodal) ses anlama ve doğrudan dikte.
  - **Groq Cloud:** Ultra hızlı Whisper ses tanıma ve Llama 3 / Qwen ile metin formatlama.
  - **ChatGPT (OpenAI):** Whisper STT ve yeni nesil dil modelleri (`gpt-4o-mini`, `gpt-5-mini`).
  - **Claude (Anthropic):** Whisper STT ve `claude-5-sonnet` modelleri ile akıllı metin biçimlendirme.
  - **Codex Desktop CLI:** Yerel kurulu Codex masaüstü uygulamasını API anahtarsız doğrudan terminal üzerinden kullanabilme.
  - **Antigravity CLI (`agy`):** Yerel Google Antigravity CLI ile sistem ve proje bağlamında modellerle metin düzenleme.
- **Düz ve Minimalist Koyu Tema (Tailwind Zinc):** Keskin hatlı (`2px` radius), yüksek kontrastlı (`#09090b` ve `#18181b`), göz yormayan modern arayüz.
- **Otomatik Güncelleme Bildirimi:** Uygulama açılışında arka planda yeni sürüm kontrolü yapılır; yeni bir sürüm çıktığında ekranın sağ üstünde şık bir bildirim kartı belirir ve tek tıkla yeni sürümü indirme imkanı sunar.
- **Bas-Başlat / Bas-Bitir (Toggle Modu):** Tek bir kısayol tuşuyla (`Ctrl+Alt+Space`) kaydı başlatıp bitirin.
- **Odak Kaybetmeyen Yüzen Kapsül (Floating Pill):** Ekranın üstünde beliren, ses dalgası animasyonlu modern arayüz. Yazdığınız pencerenin **imleç odağını asla bozmaz**.
- **Otomatik Ses Normalizasyonu (Volume Boost):** Kısık sesli mikrofonları otomatik olarak analiz eder ve en ideal seviyeye yükselterek yapay zekaya iletir.
- **5 Farklı Yazma Modu (Personas):**
  - ✍️ **Doğal Dikte (Varsayılan):** Özetlemeden yazım ve noktalamayı düzenler; anlamlı dolguları, vurguları ve belirsizliği korur.
  - 💬 **Hızlı Mesajlaşma (Chat):** Slack, WhatsApp ve Discord için samimi, akıcı ve dolaysız mesaj dili.
  - ✉️ **Resmi E-Posta:** Kurumsal, nazik ve paragraflara ayrılmış e-posta metni.
  - 🤖 **AI Prompt Oluşturucu:** Dağınık sesli düşünceleri yapılandırılmış LLM istemine çevirir.
  - 📝 **Madde İmleri (Notlar):** Konuşulanları maddeler halinde özetler.
- **Özel Kelime Dağarcığı (Custom Vocabulary):** Sık kullandığınız teknik terimler, özel isimler veya kodlama kütüphanelerini tanımlayabilme.
- **Sistem Tepsisi Entegrasyonu:** Sol tıklamayla anında Ayarlar penceresi, sağ tıklamayla mod değiştirme ve son sonuç kurtarma.

---

## 🚀 Kullanım Adımları

1. **Uygulamayı Başlatın:**
   - İndirdiğiniz uygulamayı çalıştırın. Görev çubuğunda (sistem tepsisinde) Katip mikrofon simgesi belirecektir.
2. **API Anahtarını Girin:**
   - Görev çubuğundaki Katip simgesine **sol tıklayın**; Ayarlar penceresi doğrudan açılacaktır.
   - Kullanmak istediğiniz sağlayıcıyı seçin ve API anahtarınızı girip **Kaydet**'e basın.
3. **Dikteyi Başlatın:**
   - Herhangi bir uygulamadaki metin kutusuna (VS Code, Not Defteri, Word, tarayıcı, Slack vb.) tıklayın.
   - Klavyenizden **`Ctrl + Alt + Space`** tuşlarına basın.
   - Ekranın üstünde şık bir kapsül belirecek ve siz konuştukça dinleyecektir (yazı imleciniz kaybolmaz).
4. **Dikteyi Bitirin:**
   - Konuşmanız bittiğinde tekrar **`Ctrl + Alt + Space`** tuşlarına basın.
   - Düzenlenmiş metin imlecin olduğu yere anında yapıştırılır.

---

## 🛠️ Geliştiriciler İçin (Kaynak Koddan Çalıştırma)

Katip üzerinde geliştirme yapmak veya kaynak koddan çalıştırmak isterseniz:

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/fat1h-ozturk/Katip.git
cd Katip
```

### 2. Sanal Ortamı Hazırlayın
```bash
# Linux ve macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Windows
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 3. Çalıştırın
```bash
python -m katip
```

### 4. Testleri Çalıştırın
```bash
python -m pytest -q
```

---

## ⌨️ Özel Kısayol Tuşu Entegrasyonu (`--toggle`)

Her işletim sisteminde `katip --toggle` komutu çalışır durumda olan uygulamayı anında tetikler:

- **Linux (KDE / GNOME):** Sistem Ayarları -> Kısayollar -> Yeni Komut: `katip --toggle`
- **Windows:** AutoHotkey veya Başlat Menüsü kısayolu ile: `Katip.exe --toggle`
- **macOS:** Kısayollar (Shortcuts) veya Raycast / Alfred üzerinden: `katip --toggle`

---

## 📄 Lisans

Bu proje **MIT Lisansı** ile lisanslanmıştır.
