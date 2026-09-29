# 🎙️ Katip

**Katip**, **Linux**, **Windows** ve **macOS** için geliştirilmiş, **Wispr Flow** ve **SuperWhisper** alternatifi, ultra hızlı ve akıllı bir sesli dikte masaüstü asistanıdır.

Mikrofonunuzdan konuşmanızı dinler; anlamı koruyarak gereksiz konuşma dolgularını ve dilbilgisi hatalarını düzenlemeyi hedefler. Aktif pencereye (kod editörü, tarayıcı, Word, sohbet uygulamaları vb.) doğrudan yazar.

## İndir

| İşletim sistemi | İndir |
| --- | --- |
| Windows 10/11 (x64) | [Katip Windows uygulamasını indir](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-Windows-x64.exe) |
| macOS (Apple Silicon) | [Katip macOS ARM64 imajını indir](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-macOS-arm64.dmg) |
| macOS (Intel) | [Katip macOS Intel imajını indir](https://github.com/fat1h-ozturk/Katip/releases/latest/download/Katip-macOS-x64.dmg) |

macOS'ta DMG'yi açıp Katip'i Applications klasörüne sürükleyin. Uygulama Apple tarafından imzalanıp notarize edilmediğinden macOS ilk açılışta ayrıca onay isteyebilir.

---

## ✨ Temel Özellikler

- **Çapraz Platform Desteği:** Linux (KDE Wayland/GNOME/Hyprland), Windows (10/11) ve macOS (Apple Silicon & Intel).
- **Bas-Başlat / Bas-Bitir (Toggle Modu):** Tek bir kısayol tuşuyla (`Ctrl+Alt+Space`) kaydı başlatıp bitirin.
- **Odak Kaybetmeyen Yüzen Kapsül (Floating Pill):** Ekranın üstünde beliren, ses dalgası animasyonlu modern arayüz. Yazdığınız pencerenin **imleç odağını asla bozmaz**.
- **Otomatik Ses Normalizasyonu (Volume Boost):** Kısık sesli veya laptop mikrofonlarını otomatik olarak analiz eder ve en ideal seviyeye yükselterek yapay zekaya iletir.
- **Yapay Zeka Destekli Düzenleme:**
  - **Groq Cloud:** Ses dökümü ve metin düzenleme.
  - **Google Gemini:** Çok modlu (multimodal) ses anlama ve doğrudan dikte.
- **5 Farklı Yazma Modu (Personas):**
  - ✍️ **Doğal Dikte (Varsayılan):** Özetlemeden yazım ve noktalamayı düzenler; anlamlı dolguları, vurguları ve belirsizliği koruması istenir.
  - 💬 **Hızlı Mesajlaşma (Chat):** Slack, WhatsApp ve Discord için samimi, akıcı ve dolaysız mesaj dili.
  - ✉️ **Resmi E-Posta:** Kurumsal, nazik ve paragraflara ayrılmış e-posta metni.
  - 🤖 **AI Prompt Oluşturucu:** Dağınık sesli düşünceleri yapılandırılmış LLM istemine çevirir.
  - 📝 **Madde İmleri (Notlar):** Konuşulanları maddeler halinde özetler.
- **Özel Kelime Dağarcığı (Custom Vocabulary):** Sık kullandığınız teknik terimler, özel isimler veya kodlama kütüphanelerini tanımlayabilme.
- **Sistem Çekmecesi (System Tray):** Arka planda sessizce çalışır, mod değiştirmeyi ve ayarlara erişmeyi sağlar.
- **Akustik Geri Bildirim:** Kayıt başlama, bitiş, başarı ve hata durumlarında hafif, zarif ses tonları.

---

## 🛠️ İşletim Sistemine Göre Kurulum

<details open>
<summary><b>🐧 Linux Kurulumu (KDE Wayland / GNOME / X11)</b></summary>

### 1. Sistem Paketlerini Yükleyin
- **Fedora / RHEL:**
  ```bash
  sudo dnf install wl-clipboard ydotool gtk4-layer-shell python3-gobject pipewire-utils portaudio-devel alsa-lib
  ```
- **Ubuntu / Debian (22.04, 24.04+):**
  ```bash
  sudo apt update
  sudo apt install wl-clipboard ydotool libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0 python3-gi python3-gi-cairo portaudio19-dev python3-pip python3-venv libasound2-dev
  ```
- **Arch Linux / Manjaro:**
  ```bash
  sudo pacman -S wl-clipboard ydotool gtk4-layer-shell python-gobject portaudio alsa-lib
  ```

### 2. İzinleri ve ydotool Servisini Ayarlayın
```bash
sudo usermod -aG input $USER
systemctl --user enable --now ydotool
```
*(Grup değişikliğinin geçerli olması için oturumu kapatıp yeniden açın).*

### 3. Tek Tıkla Kurulum ve Başlat Menüsüne Ekleme (Önerilen)
Depoyu klonlayıp tek komutla kurabilirsiniz:
```bash
git clone https://github.com/fat1h-ozturk/katip.git
cd katip
./install.sh
```
> [!NOTE]
> `install.sh` betiği sanal ortamı hazırlar, bağımlılıkları yükler, projeyi **`-e` (editable / düzenlenebilir)** modda kurar ve Katip'ı doğrudan **Başlat Menünüze (KDE Kickoff, GNOME Arama)** simgesiyle kaydeder.

*(Alternatif Manuel Kurulum)*:
```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m katip --install
```

### 4. İleride Nasıl Güncellenir?
Projeye yeni bir özellik veya hata düzeltmesi geldiğinde tek komutla güncelleyin:
```bash
./update.sh
```
> `update.sh` betiği `git pull` ile en son kodları çeker, gerekiyorsa yeni paketleri yükler ve başlat menüsü entegrasyonunu yeniler.

### 5. Başlatın
- **Başlat Menüsü / KRunner:** Süper (Windows) tuşuna basıp `Katip` veya `Dikte` yazarak açabilirsiniz.
- **Terminalden:** `./bin/katip`

### 6. Sistemden Tamamen Nasıl Kaldırılır? (Uninstall)
Uygulamayı, menü kayıtlarını, simgeleri, ayarları ve sanal ortamı temizlemek için:
```bash
./uninstall.sh
```
</details>

<details>
<summary><b>🪟 Windows Kurulumu & Güncelleme (Windows 10 / 11)</b></summary>

Windows üzerinde harici bir servis kurmanıza gerek **yoktur**; yerel Win32 API (`keybd_event` ve `OpenClipboard`) doğrudan kullanılır.

### 1. Ön Koşullar (Yalnızca İlk Kurulumda)
1. **Git for Windows**: Güncellemeleri alabilmek için [Git for Windows](https://git-scm.com/download/win) kurulu olmalıdır.
2. **Python 3.10 veya üzeri**: [python.org](https://www.python.org/downloads/) üzerinden indirip kurun.
   > [!IMPORTANT]
   > Python kurulum sihirbazının ilk ekranında yer alan **"Add python.exe to PATH"** kutucuğunu **kesinlikle işaretleyin**.

### 2. Klonlama ve Tek Tıkla Kurulum
Komut İstemi'ni (**CMD**) veya **PowerShell**'i açın:
```cmd
git clone https://github.com/fat1h-ozturk/katip.git
cd katip
install.bat
```

> [!NOTE]
> **Neden Doğrudan Güncellenebilir?**  
> `install.bat` sihirbazı, uygulamayı sanal ortama **`-e` (editable / düzenlenebilir)** modunda bağlar. Kod dosyaları kopyalanmaz, klonlanan bu klasöre canlı referans verilir. Başlat Menüsü'ne eklenen kısayol da doğrudan bu ortama bağlanır. Bu sayede klasördeki kod güncellendiğinde tüm Windows sisteminde anında güncellenmiş olur!

### 3. İleride Nasıl Güncellenir?
Projeye yeni bir özellik veya doğruluk iyileştirmesi geldiğinde:
- **Yöntem 1 (Tek Tıkla - En Pratik):**  
  `katip` klasöründeki **`update.bat`** dosyasına çift tıklayın.
- **Yöntem 2 (Komut İstemi / Terminal):**
  ```cmd
  cd katip
  update.bat
  ```

**`update.bat` arka planda ne yapar?**
1. GitHub deposundan en güncel değişiklikleri çeker (`git pull`).
2. `.venv` ortamına proje bağımlılıklarını yükler (`pip install -e .`).
3. Windows Başlat Menüsü ve masaüstü bağlantılarını yeniler.
4. Başarı bildirimini ekranda gösterir.

### 4. Başlatın
- **Windows Başlat Menüsü:** Klavyenizdeki Windows tuşuna basıp `Katip` yazarak uygulamayı açabilirsiniz.
- **Komut Satırından:** `bin\katip.bat`

### 5. Sistemden Tamamen Nasıl Kaldırılır? (Uninstall)
Uygulamayı, Başlat Menüsü/Başlangıç kısayollarını, ayarları ve sanal ortamı temizlemek için:
- **Yöntem 1 (Tek Tıkla):** Klasördeki **`uninstall.bat`** dosyasına çift tıklayın.
- **Yöntem 2 (Terminal):**
  ```cmd
  cd katip
  uninstall.bat
  ```
*(İsteğe bağlı olarak proje klasörünü de tamamen silmek isteyip istemediğinizi sorar).*

### 6. 📦 Python Olmadan Bağımsız Çalıştırma (Standalone .exe)
Eğer uygulamayı Python kurulu olmayan başka bir Windows bilgisayara taşımak veya tek bir `.exe` olarak kullanmak isterseniz:
- Klasördeki **`build_exe.bat`** dosyasına çift tıklayın.
- Derleme bittiğinde **`dist\Katip.exe`** dosyası oluşturulacaktır (~52 MB).
- Bu `.exe` dosyasını herhangi bir Windows bilgisayara kopyalayıp Python yüklemeden doğrudan çalıştırabilirsiniz!
</details>

<details>
<summary><b>🍎 macOS Kurulumu & Güncelleme (Apple Silicon M1/M2/M3/M4 & Intel)</b></summary>

macOS üzerinde ses çalma (`afplay`), pano (`pbcopy`) ve metin yapıştırma (AppleScript `Cmd+V`) işletim sisteminin yerel araçlarıyla çalışır.

### 1. Ön Koşullar
1. **Homebrew & PortAudio**: Terminal açıp PortAudio'yu kurun:
   ```bash
   brew install portaudio
   ```
2. **Git & Python 3.10+**: macOS ile gelen veya Homebrew (`brew install python git`) sürümlerini kullanabilirsiniz.

### 2. Klonlama ve Tek Tıkla Kurulum
Terminali açıp depoyu klonlayın:
```bash
git clone https://github.com/fat1h-ozturk/katip.git
cd katip
./install.sh
```
*(veya Finder üzerinden klasördeki **`install.command`** dosyasına çift tıklayabilirsiniz).*

> [!NOTE]
> `install.sh`, sanal ortamı kurar, bağımlılıkları yükler, projeyi **`-e` (editable / düzenlenebilir)** modda bağlar ve macOS **Spotlight / Launchpad** araması için `~/Applications/Katip.app` paketini otomatik oluşturur.

### 3. İleride Nasıl Güncellenir?
Yeni güncellemeleri almak için:
- **Yöntem 1 (Finder'dan Çift Tık):** Klasördeki **`update.command`** dosyasına çift tıklayın.
- **Yöntem 2 (Terminalden):**
  ```bash
  cd katip
  ./update.sh
  ```

### 4. Başlatın ve İzinleri Verin
- **Spotlight:** `Cmd+Space` tuşlarına basıp `Katip` yazarak açın.
- **Terminalden:** `./bin/katip`

> [!IMPORTANT]
> macOS güvenlik kuralları gereği, uygulamanın mikrofonu dinleyebilmesi ve aktif pencereye `Cmd+V` yapıştırma simülasyonu gönderebilmesi için **Sistem Ayarları -> Gizlilik ve Güvenlik** altından:
> 1. **Mikrofon (Microphone):** Terminal / Katip için izin verin.
> 2. **Erişilebilirlik (Accessibility):** Terminal / Katip için izin verin.

### 5. Sistemden Tamamen Nasıl Kaldırılır? (Uninstall)
Uygulamayı, `.app` paketini, Spotlight kaydını, LaunchAgent ve ayarları temizlemek için:
- **Finder'dan Çift Tık:** Klasördeki **`uninstall.command`** dosyasına çift tıklayın.
- **Terminalden:** `./uninstall.sh`

</details>

---

## 🚀 Kullanım Adımları

1. **API Anahtarını Girin:**
   - Uygulama açıldığında sağ alt (veya macOS'ta üst menü çubuğundaki) sistem çekmecesi ikonuna **sağ tıklayın** ve **⚙️ Ayarlar...** seçeneğini açın.
   - **Groq Cloud** veya **Google Gemini** API anahtarınızı girip **Kaydet**'e basın. Model erişimi ve ücretlendirme için sağlayıcınızın güncel koşullarını kontrol edin.
   *(İsteğe bağlı olarak terminalinizde `export GROQ_API_KEY="gsk_..."` veya Windows'ta `set GROQ_API_KEY=...` tanımlayabilirsiniz).*

2. **Dikteyi Başlatın:**
   - Herhangi bir uygulamadaki metin kutusuna (VS Code, Not Defteri, Word, tarayıcı, Slack vb.) tıklayın.
   - Klavyenizden **`Ctrl + Alt + Space`** tuşlarına basın.
   - Ekranın üstünde şık bir kapsül belirecek ve siz konuştukça dinleyecektir (yazı imleciniz kaybolmaz).
3. **Dikteyi Bitirin:**
   - Konuşmanız bittiğinde tekrar **`Ctrl + Alt + Space`** tuşlarına basın.
   - İşleme tamamlandığında düzenlenmiş metin imlecin olduğu yere yapıştırılır.

İşleme veya yapıştırma başarısız olursa sistem çekmecesindeki **Son Sonuç / Kaydı Kurtar...** menüsünü açın. Buradan son metni kopyalayabilir, kaydı yeniden işleyebilir veya sesi WAV dosyası olarak kaydedebilirsiniz. Yeniden işleme sonucu bu pencerede gösterilir; otomatik yapıştırılmaz. İşlenemeyen ses uygulama açıkken bellekte tutulur; yeniden kayda başlamadan veya çıkmadan önce **Sesi Kaydet** ya da **Kaydı Temizle** seçeneğini kullanın.

Korunan bir kayıt varken kısayola yeniden bastığınızda kurtarma penceresi açılır. Metin modeli bulunamıyorsa hata mesajında HTTP 404 ve ayarları düzeltme yönlendirmesi gösterilir; model kendiliğinden değiştirilmez.

### Groq: sözlük ve metin düzenleme

Ayarlardaki özel kelime listesine tercih ettiğiniz yazımları ekleyebilirsiniz. İsteğe bağlı eşleşme alanında her satır `duyulan varyant => tercih edilen yazım` biçimindedir:

```text
paysayd altı => PySide6
katıp => Katip
```

Eşleşmeler bağlama bağlı yazım ipuçlarıdır; metne körlemesine arama/değiştirme uygulanmaz. En fazla 100 eşleşme, her taraf için 200 karakter kabul edilir. Whisper'a gönderilen ipucu 224 UTF-8 byte ile sınırlanır; bu gerçek token sayımı değildir. Sığmayan terimler ayarlarda bildirilir ve kayıtlı sözlükten silinmez.

Groq akışı seçili modellerle bir ses dökümü ve bir metin düzenleme isteği kullanır. Modlara özel talimatlar isimleri, miktarları, olumsuzlukları ve ihtimal ifadelerini korumayı hedefler. Düzenleyici yanıtının JSON yapısı ve tamamlanması kontrol edilir; bozuk veya kesilmiş yanıtta ham metin korunur, otomatik yapıştırma yapılmaz. Uzun girdide çıktı bütçesi artırılır; bağlama sığmayan ham metin sessizce kırpılmaz.

**Son Sonuç** ekranında **Ham Metin** ve **Düzenlenmiş Metin** sekmeleri ayrı ayrı kopyalanabilir:

- **Metni Yeniden Düzenle:** Her seferinde özgün ham transkripti kullanır; ses göndermez, yalnız bir metin isteği yapar ve otomatik yapıştırmaz. Varsayılan olarak kaydın modunu ve sözlüğünü korur. **Güncel mod ve sözlüğü kullan** seçeneği bu ikisini günceller; kaydın model ve dil seçimi korunur. Başarısızlıkta önceki başarılı sonuç kaybolmaz.
- **Sesi Yeniden İşle:** Bellekteki sesi mevcut ayarlarla yeniden gönderir. Ses dökümü ve metin düzenleme aşamalarını tekrar çalıştırır.
- **Ayrıntılar:** Sözlük sınırlarını, mevcut segment verilerini ve belirgin URL/e-posta/kod/kimlik farklarını gösterir. Bunlar doğruluk yüzdesi veya anlam hatası kararı değildir; sonucu engellemez.

Ham ve düzenlenmiş metin yalnız bellekte tutulur; yeni kayıt, **Kaydı Temizle** veya uygulamanın kapanmasıyla silinir. Kalıcı transkript geçmişi eklenmez. Bu kontroller modelin anlamı kusursuz koruyacağını garanti etmez; Gemini'nin mevcut metin akışı korunur.

---

## ⌨️ Özel Kısayol Tuşu Entegrasyonu (`--toggle`)

Her işletim sisteminde `katip --toggle` komutu çalışır durumda olan uygulamayı anında tetikler:

- **Linux (KDE / GNOME):** Sistem Ayarları -> Kısayollar -> Yeni Komut: `katip --toggle`
- **Windows:** AutoHotkey veya Windows Görev Çubuğu kısayolu ile `bin\katip.bat --toggle`
- **macOS:** Kısayollar (Shortcuts) uygulaması veya Raycast / Alfred üzerinden `bin/katip --toggle`

---

## 🧪 Testleri Çalıştırma

Tüm platform adaptörlerini ve birim testleri doğrulamak için:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

