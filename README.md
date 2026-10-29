# 🎙️ Kâtip

**Kâtip**, **Linux**, **Windows** ve **macOS** için geliştirilmiş, **Wispr Flow** ve **SuperWhisper** alternatifi, ultra hızlı ve akıllı bir sesli dikte masaüstü asistanıdır.

Mikrofonunuzdan konuşmanızı dinler; seçtiğiniz moda göre yazım ve biçimi düzenler. Doğrulanabilen hedef pencereye yapıştırma girdisi gönderir; hedef değişmişse veya doğrulanamıyorsa metni Son Sonuç menüsünde hazır tutar.

Bu geliştirme dalındaki güvenilirlik değişiklikleri ve henüz doğrulanmamış kabul adımları [uygulama durumunda](docs/reliability.md) açıklanmıştır. İndirilebilir yayımlanmış paketler bu dalın değişikliklerini otomatik içermez.

---

## 📥 Hazır Paketleri İndir

Kâtip tamamen bağımsız (**standalone**) paketler olarak yayınlanmaktadır; bilgisayarınıza Python veya harici kütüphane yüklemenize gerek yoktur.

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
- **Odak Kaybetmeyen Yüzen Kapsül (Floating Pill):** Ekranın üstünde beliren, ses dalgası animasyonlu modern arayüz. Yazdığınız pencerenin **odak almaması için platformun desteklediği önlemleri kullanır**.
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
   - İndirdiğiniz uygulamayı çalıştırın. Görev çubuğunda (sistem tepsisinde) Kâtip mikrofon simgesi belirecektir.
2. **API Anahtarını Girin:**
   - Görev çubuğundaki Kâtip simgesine **sol tıklayın**; Ayarlar penceresi doğrudan açılacaktır.
   - Kullanmak istediğiniz sağlayıcıyı seçin ve API anahtarınızı girip **Kaydet**'e basın.
3. **Dikteyi Başlatın:**
   - Herhangi bir uygulamadaki metin kutusuna (VS Code, Not Defteri, Word, tarayıcı, Slack vb.) tıklayın.
   - Klavyenizden **`Ctrl + Alt + Space`** tuşlarına basın.
   - Ekranın üstünde şık bir kapsül belirecek ve siz konuştukça dinleyecektir (yazı imleciniz kaybolmaz).
4. **Dikteyi Bitirin:**
   - Konuşmanız bittiğinde tekrar **`Ctrl + Alt + Space`** tuşlarına basın.
   - Hedef doğrulanabiliyorsa yapıştırma girdisi gönderilir. Hedef değişmişse veya Wayland gibi ortamlarda kimliği doğrulanamıyorsa metni **Son Sonuç** menüsünden kopyalayın.
5. **Hata veya İptal Sonrasında:**
   - Son Sonuç menüsünden ham metni alın, yalnız metni yeniden düzenleyin, sesi filtreli/filtresiz yeniden işleyin veya ham WAV dosyasını kaydedin.
   - Tek kayıt sınırı **10 dakika veya 64 MiB ham PCM**; sınıra ulaşınca alınan ses korunur. Önceki sesi kopyalayarak, kaydederek veya açıkça temizleyerek yeni kayda geçebilirsiniz.
   - Ses ve sonuç uygulama belleğindedir; işletim sisteminin uygulamayı öldürmesi veya süreç çökmesi durumunda kalıcı kurtarma garantisi yoktur.

---

## 🛠️ Geliştiriciler İçin (Kaynak Koddan Çalıştırma)

Kâtip üzerinde geliştirme yapmak veya kaynak koddan çalıştırmak isterseniz:

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/fat1h-ozturk/Katip.git
cd Katip
```

### 2. Sistem Ön Koşulları

Kaynak kurulumunda Python 3.10+ ve PortAudio gerekir. Linux'ta `portaudio19-dev` (Debian/Ubuntu) veya `portaudio-devel` (Fedora), macOS'ta `brew install portaudio` kullanın. PyAudio derlenirken C derleyicisi ve Python geliştirme başlıkları gerekir. Hazır paketin sistem mikrofonu, masaüstü oturumu ve ilgili izinlere erişmesi yine gereklidir.

### 3. Kilitli Ortamı Kurun ve Ayrı Profilde Çalıştırın

```bash
uv sync --locked --group dev
# Linux / macOS: üretim ayarları ve IPC'den ayrı aday profil
KATIP_PROFILE=reliability uv run --no-sync python -m katip
```

Windows PowerShell'de önce `$env:KATIP_PROFILE = "reliability"`, sonra `uv run --no-sync python -m katip` çalıştırın. Profil ilk açılışta kendi ayarlarını ister; üretim anahtarlarını otomatik kopyalamaz. Aday profilde menüye kurulum ve autostart değişikliği kapalıdır. Profil adı küçük harf, rakam ve tire içerebilir; en fazla 32 karakterdir.

`uv` kullanmadan: sanal ortamda `python -m pip install -r requirements-dev.lock`, ardından `python -m pip install --no-deps -e .` çalıştırın. `requirements-dev.lock`, `uv.lock` üzerinden dışa aktarılmış platform işaretli bağımlılıkları içerir.

### 4. Kontroller ve Paketleme

```bash
uv run --no-sync ruff check katip
uv run --no-sync mypy
uv run --no-sync pytest -q
uv run --no-sync pyinstaller katip.spec --clean --noconfirm
```

Testler gerçek API, mikrofon ve panoyu varsayılan olarak engeller. Uzun DSP ölçümleri isteğe bağlıdır: `KATIP_RUN_PERFORMANCE=1 uv run --no-sync pytest tests/test_audio_performance.py -q -s`. Kaynak kontrolleri, gerçek masaüstü ve canlı sağlayıcı kabulünün yerini tutmaz.

### Anahtarlar ve Teşhis

Masaüstü uygulaması API anahtarlarını işletim sistemi kasasına yazar (Linux Secret Service, Windows Credential Manager, macOS Keychain). Mevcut JSON anahtarları, başarılı kasa yazma/geri okuma sonrasında yapılan ayar kaydında referanslara dönüşür. Kasa kullanılamazsa kayıt başarısız olur ve eski ayarlar korunur; yeni anahtarı düz metne dönüştüren gizli geri dönüş yoktur. İlk göçün `config.previous.json` yedeği eski düz metin anahtarları içerebilir; bunu hassas bir geri dönüş yedeği olarak tutun. Eski sürüme dönmek için uygulamalar kapalıyken bu yedeği kullanın.

Ayar dizinindeki `diagnostics.jsonl` en fazla beş adet 1 MiB dosyaya döner. İçerik oturum kimliği, sıra, geçen süre, aşama, boyut ve kısa hata kodlarıdır; ses, transkript veya API anahtarı yazılmaz. Son Sonuç → Ayrıntılar/Teşhis alanı dışarıya kopyalanmadan önce görülebilir. Normal kullanım otomatik WAV/transkript geçmişi oluşturmaz. Elle kaydettiğiniz dosya ve sistem panosu bu bellek politikasından ayrıdır.

---

## ⌨️ Özel Kısayol Tuşu Entegrasyonu (`--toggle`)

Her işletim sisteminde `katip --toggle` komutu çalışır durumda olan uygulamayı anında tetikler:

- **Linux (KDE / GNOME):** Sistem Ayarları -> Kısayollar -> Yeni Komut: `katip --toggle`
- **Windows:** AutoHotkey veya Başlat Menüsü kısayolu ile: `Katip.exe --toggle`
- **macOS:** Kısayollar (Shortcuts) veya Raycast / Alfred üzerinden: `katip --toggle`

---

## 🐧 Linux: Kısayol, Yapıştırma ve Pencere Odağı

KDE Plasma **Wayland** oturumunda Qt kayıt göstergesi, odak almama ipuçlarına
rağmen terminalin veya metin alanının odağını alabilir. Kâtip, Qt göstergesini
kullanırken kullanıcı hesabında yalnızca `Katip Recording Overlay` penceresine
uygulanan bir KWin kuralını otomatik kaydeder. Gösterge görünür kalır, klavye
odağını alamaz; ayarlar ve sonuç pencereleri bu kuralın dışındadır. Başlığa eklenen
`— Kâtip` uygulama adı da eşleştirilir. Mevcut kişisel pencere kuralları korunur.
Bu entegrasyon KDE'nin `kreadconfig6` / `kwriteconfig6` (veya Plasma 5 araçlarını)
gerektirir; yönetici yetkisi istemez. Diğer masaüstleri bu KWin kuralını kullanmaz.

Wayland'da önce GlobalShortcuts portalı denenir; izin reddi görünür bildirilir. Portal kullanılamıyorsa evdev/IPC yolu kullanılır. Kısayol hiç algılanmıyorsa, Linux'taki doğrudan klavye dinleyicisinin giriş
aygıtlarını okuma izni olmayabilir. `input` grubuna genel erişim vermek yerine,
Sistem Ayarları → Kısayollar bölümünde `katip --toggle` komutuna bir kısayol
atayabilirsiniz. Bu yöntem açık olan Kâtip örneğini tetikler ve klavyeye doğrudan
erişim gerektirmez. Aynı tuş birleşimini iki dinleyicide birden kullanmayın.

Wayland'da genel bir aktif pencere kimliği API'si olmadığı için bu aday otomatik teslimi doğrulayamaz ve sonucu kopyalamaya hazır tutar. Ayarlardaki açık hedefli yapıştırma testinde `wl-copy` ve çalışan bir `ydotoold` gerekir.
Fedora'da paketleri `sudo dnf install wl-clipboard ydotool` ile kurabilirsiniz.
`ydotool` paketinin kurulu olması servisin çalıştığı anlamına gelmez; ayrıca
istemcinin daemon soketine erişebilmesi gerekir. Fedora'da durumunu
`systemctl status ydotool` ile kontrol edin. Soket yolu, sahipliği ve servis
kurulumu dağıtıma göre değişebilir; uygulamayı root olarak çalıştırmayın.

Pano geri yükleme, yalnız sürüm/sahiplik takibi olan Windows ve macOS arka uçlarında desteklenir. Linux'ta bu seçenek açıkken işlem mevcut panoyu koruyarak durur; sonucu elle kopyalayabilir veya seçeneği kapatabilirsiniz.

Terminalde Ctrl+Shift+V göndermek için **Terminal Uyumluluk Modu**nu açın.
Normal metin alanları Ctrl+V bekliyorsa bu modu kapatın; Kâtip şu anda hedef
uygulamaya göre yapıştırma tuşunu otomatik seçmez.

---

## 🗑️ Nasıl Kaldırılır (Uninstall)

Uygulamayı sistemden ve menülerden tamamen kaldırmak isterseniz:

1. **Önce Sistem Kayıtlarını Temizleyin:**
   Kısayolları, otomatik başlatma ayarlarını ve (API anahtarlarınız dahil) tüm yapılandırmaları silmek için terminalde (veya Komut İsteminde) uygulamanın dizininde şu komutu çalıştırın:
   ```bash
   katip --purge
   ```

2. **Uygulama Dosyasını Silin:**
   * **Fedora:** `sudo dnf remove katip`
   * **Arch Linux:** `sudo pacman -R katip`
   * **Windows / macOS / Diğer:** İndirmiş olduğunuz `Katip.exe`, `Katip.app` veya çalıştırılabilir dosyayı doğrudan silebilirsiniz.


