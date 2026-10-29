# Güvenilirlik çalışması — durum

29 Ekim 2026 · Temel: v0.4.6 (`0fc304b`) · Sürüm numarası değişmedi.

Kabul çıtası: **uygulama çökmez, ses güvenilir biçimde alınır, metin güvenilir biçimde hedefe ulaşır**; ulaşamıyorsa kaybolmaz ve kullanıcı tek adımla (Ctrl+V) alabilir. Bu belge neyin **otomatik olarak doğrulandığını**, neyin **yalnız gerçek masaüstünde doğrulanabileceğini** ve sahada bir hata olursa **nasıl yakalanacağını** ayırır.

> Bu çalışma gerçek mikrofon, gerçek masaüstüne yapıştırma veya canlı sağlayıcı API'si kullanmadan yapıldı. Aşağıdaki "Manuel kabul" listesi tamamlanmadan bir platform için "çalışıyor" denmemelidir.

## Doğrulananlar (otomatik, bu makinede)

| Kontrol | Sonuç |
|---|---|
| Test paketi (Linux, Python 3.11.17, kilitli ortam `uv sync --locked`) | 386 geçti, 12 atlandı (atlananlar isteğe bağlı performans testleri) |
| Aynı paket Python 3.10 ve 3.14 | Ayrı kilitli ortamlarda 3.10.22 ve 3.14.8: her birinde 386 geçti, 12 atlandı |
| `ruff check katip`, `mypy` (çekirdek kapsam) | Temiz |
| CI kapsama kapısı (oturum, teşhis, HTTP modülleri ≥%90 satır ve dal) | Geçti: oturum %100 satır / %92,9 dal, teşhis %100 / %100, HTTP %98,4 / %97,4. Tüm paket: %71,7 satır, %54,7 dal (diğer modüller yalnız raporlanır) |
| PyInstaller paketi (Linux, `katip.spec`) | Derlendi; `--version` çalıştı; RemoteDesktop ve dbus-next modülleri pakette. Paketle gerçek masaüstü testi yapılmadı. |
| `uv lock --check` | Kilit `pyproject.toml` ile tutarlı |
| İsteğe bağlı performans paketi (`KATIP_RUN_PERFORMANCE=1`) | 12/12 geçti: 40–600 sn × 16/44,1/48 kHz, en kötü GUI p95 25,4 ms, p99 28,1 ms, ek RSS ≤57,5 MiB, 600 sn DSP ≈4,1 sn (sentetik PCM; gerçek konuşma/paket ölçümü değil) — [ayrıntılar](validation/2026-10-29-performance.json) |

Testlerdeki mikrofon, HTTP, pano, klavye, portal ve süreç sınırları sahtedir; ağ testleri yerel bir HTTP sunucusuna gerçek istek atar, CLI testleri gerçek yerel alt süreç başlatır. GitHub üzerindeki CI matrisi (Windows, iki macOS mimarisi) henüz çalışmadı; ilk push'ta çalışacaktır.

## Neler değişti

| Alan | Davranış |
|---|---|
| Ses kaydı | Ham PCM, işlenmiş sesten ayrı tutulur; VAD reddi, cihaz kopması veya işleme hatası sesi silmez. Tek kayıt 10 dakika / 64 MiB ile sınırlıdır. 44,1/48 kHz girişler filtreli olarak 16 kHz'e çevrilir. |
| Mikrofon seçimi | Seçili mikrofon adıyla da saklanır; USB tak/çıkar PortAudio sırasını değiştirse de aynı cihaz bulunur, bulunamazsa varsayılan mikrofona geçilir ve bildirilir. Açma hatasında PortAudio bir kez yeniden başlatılır (askıya alma/yeniden takma sonrası eski cihaz listesi). Tamamen sessiz giriş (izin yok, sessize alınmış) "konuşma yok" yerine `CAPTURE_SILENT` olarak bildirilir. |
| İş akışı | Kayıt durdurma, DSP, sağlayıcı çağrıları ve teslim GUI dışında tek iş kuyruğunda çalışır; sonuçları yalnız GUI uygular. Her iş kendi `job_id`, ayar kopyası ve iptal belirteciyle ilerler; eski sonuç yeni oturuma uygulanmaz. GUI tarafındaki beklenmeyen bir hata oturumu "meşgul" durumda bırakmaz; ses korunarak kurtarılabilir hataya düşülür. |
| Sağlayıcılar | Altı sağlayıcı ortak sonuç sözleşmesini kullanır; OpenAI/Claude prompt hatası (B01) giderildi. Ham transkript formatter'dan önce saklanır; yeniden düzenleme aynı sağlayıcı/modelle ve ikinci STT çağrısı olmadan yapılır. Eksik, kesik veya protokol dışı çıktı otomatik teslim edilmez. |
| Ağ | QtNetwork; aşama başına 90 sn, durdurmadan sonra toplam 180 sn, gerçek `abort`. Başlıkları gelmiş fakat gövdesi yarıda kesilmiş yanıt artık başarı sayılmaz. Otomatik ücretli tekrar veya sağlayıcı değişimi yoktur. Gemini'nin tek istek sınırını (≈7 dakika ses) aşan kayıt yüklenmeden önce açıkça reddedilir. |
| Teslim (yapıştırma) | Aşağıda ayrıntılı. Kısaca: hedef doğrulanabiliyorsa ve değişmediyse yapıştırılır; Wayland'da hedef kimliği alınamadığı için odaktaki pencereye yapıştırılır; hedef değiştiyse veya yapıştırma başarısızsa metin panoya alınır ve "Ctrl+V ile yapıştırın" denir. |
| Kısayol | Wayland'da GlobalShortcuts portalı denenir; portal hatası, zaman aşımı veya bağlantı kaybında evdev/IPC yoluna dönülür. Klavye tak/çıkar için cihazlar yeniden taranır. |
| Gösterge | Wayland GTK layer-shell yardımcısı ayrı giriş modu ve READY el sıkışmasıyla başlar; layer-shell desteklenmiyorsa veya yardımcı ölürse odak almayan Qt göstergesine dönülür. Paketlenmiş sürümler PyGObject içermediği için Qt göstergesini kullanır. |
| Ayarlar ve anahtarlar | Şema sürümü, bilinmeyen alanların korunması, tek seferlik `config.previous.json` yedeği. API anahtarları işletim sistemi anahtar kasasında tutulur. Kasa kilitli/yoksa diğer ayarlar yine kaydedilir, mevcut anahtarlar olduğu gibi kalır; yalnız yeni veya değişen anahtar açıklamalı bir mesajla reddedilir (gizli düz metin geri dönüşü yok). |
| Teşhis | İçerik taşımayan, boyutu sınırlı olay günlüğü, yerel çökme izi ve temiz olmayan çıkış tespiti (aşağıda). |
| Sürekli kontrol | `uv.lock` + dışa aktarılmış pip kilidi, push/PR CI matrisi, lint, çekirdek tip denetimi, kapsama kapısı, paket smoke testi. |

### Yapıştırma kuralları (platforma göre)

| Ortam | Hedef kontrolü | Girdi yolu (sırayla) |
|---|---|---|
| Windows | Ön plandaki pencere kaydın başında alınır, teslimden ve pano senkronizasyonundan önce karşılaştırılır. | Kısayol tuşları bırakılana kadar (≤1 sn) beklenir, sonra Ctrl+V. |
| macOS | Ön plandaki uygulama + pencere numarası. | Modifier tuşları bırakılınca System Events ile Cmd+V (Erişilebilirlik ve Otomasyon izni gerekir). |
| Linux X11 | `xdotool getactivewindow`. | `xdotool key --clearmodifiers ctrl+v`, yoksa çalışan `ydotoold`. |
| Linux Wayland (KDE, GNOME, wlroots) | Genel bir pencere kimliği API'si yok; **odaktaki pencere hedef kabul edilir** ve doğrulanmış sayılmaz. | Soketi bulunan `ydotoold` → `wtype` (yalnız wlroots: sway, Hyprland) → XDG RemoteDesktop portalı (KDE/GNOME; ilk kullanımda bir kez izin sorar, izin hatırlanır). `xdotool` Wayland'da kullanılmaz (yalnız XWayland pencerelerine ulaşır ve başarısız yapıştırmayı başarılı gösterirdi). |

Her durumda: hedef değiştiyse yazılmaz; yapıştırma yolu yoksa/başarısızsa metin panoya alınır ve bildirilir; belirsiz bir yapıştırma (ör. ydotool zaman aşımı) ikinci bir araçla tekrarlanmaz. "Panoyu geri yükle" açıkken pano yalnız hâlâ Kâtip'in yazdığı içeriği taşıyorsa geri yüklenir (Windows/macOS'ta ek olarak sürüm numarası); kullanıcı arada başka bir şey kopyaladıysa dokunulmaz. Linux'ta sürüm numarası olmadığından aynı metnin tekrar kopyalandığı durum ayırt edilemez.

Wayland'da hedef doğrulanamadığı için, işlem sürerken başka bir pencereye geçerseniz metin o pencereye gider. Sahip tercihi "yapıştıramamak" yerine bunu kabul etmektir; risk istemiyorsanız sonucu bekleyin.

## Bir hata olursa: teşhis kaydını yakalamak (U01 ve sonrası)

Bilinen olay **U01**: Groq ile ~40 saniyelik dikte sırasında ~25. saniyede bir hata görüldü; mesaj ve kayıt yok, kök neden **kanıtlanmadı**.

**Güçlü fakat kanıtlanmamış açıklama:** v0.4.6'da Groq STT ve formatter isteklerinde `timeout=25` vardı ve zaman aşımı dahil her ağ hatası "Groq Whisper bağlantı hatası" olarak gösteriliyordu. Sunucunun 25 saniye yanıt vermemesi bu mesajı üretir. Bu dalda süreler 90/180 saniyedir ve zaman aşımı ayrı bir kodla bildirilir. Bu değişiklik U01'i kapatmış sayılmaz; olay tekrar ederse aşağıdaki kayıt hangi aşamanın bozulduğunu gösterir.

### Neler kaydediliyor

Ayar klasöründeki `diagnostics.jsonl` (en fazla 5 × 1 MiB, döner): her satırda iş kimliği, sıra, UTC zaman (`ts`), işin başından geçen süre, aşama, boyut ve kısa kodlar. **Ses, transkript, API anahtarı, istek/yanıt gövdesi veya ham hata metni yazılmaz.**

| Olay | Ne anlatır |
|---|---|
| `app_started` / `app_stopped` | Sürüm ve temiz kapanış. |
| `previous_run_unclean` (`PROCESS_EXIT_UNCLEAN`) | Önceki çalışma `app_stopped` olmadan bitti: çökme, öldürülme veya güç kesintisi. `source` alanı o çalışmanın **son olayını** verir (ör. `stt_started` → STT beklerken bitti). |
| `stream_opened`, `capture_progress` (5 sn'de bir), `capture_stopped` | Örnekleme hızı ve alınan bayt; `audio_bytes / (2 × sample_rate)` = saniye. İlerleme olayları bir saniyede durup `stop_requested` gelmediyse kayıt sürücüde takılmıştır. |
| `failed` + `CAPTURE_*` | `CAPTURE_DEVICE_LOST`, `CAPTURE_READ_ERROR`, `CAPTURE_OPEN_FAILED`, `CAPTURE_DRAIN_TIMEOUT`, `CAPTURE_LIMIT`, `CAPTURE_SILENT`; o ana kadar alınan bayt ve PortAudio errno. |
| `http_started` / `http_finished` | Sunucu adı, yüklenen bayt, HTTP durumu, süre, sonuç (`OK`, `NETWORK_TIMEOUT`, `NETWORK_CONNECTION`, `CANCELLED`, `DEADLINE`, `RESPONSE_TOO_LARGE`) ve Qt hata adı (ör. `RemoteHostClosedError`, `HostNotFoundError`, `SslHandshakeFailedError`). |
| `failed` (iş) | Hata kodu ve o anki oturum aşaması (`transcribing`, `formatting`, `delivering`…). |
| `delivery_*`, `clipboard_fallback` | Hedef doğrulandı mı, girdi gönderildi mi, panoya mı alındı. |
| `unhandled_exception` | Yalnız istisna türü. |

Yerel çökmelerde (ör. ses sürücüsü) Python yığın izi aynı klasördeki `crash-traceback.log` dosyasına yazılır (dosya ve fonksiyon adları; içerik yok; 1 MiB'ı aşınca sıfırlanır).

Ayar klasörü: Linux `~/.config/katip/` · Windows `%APPDATA%\katip\` · macOS `~/Library/Application Support/katip/` (`KATIP_PROFILE=ad` ile çalıştırınca klasör adı `katip-ad`).

### Olay tekrar ederse yapılacaklar

1. Saati not edin (dakika yeterli).
2. Uygulama açıksa: tepsi → **Son Sonuç** → **Ayrıntılar** (veya **Teşhis**) sekmesi → **Gösterilen Metni Kopyala**. Ses korunuyorsa **Sesi Kaydet** ile WAV'ı da alın (isteğe bağlı; ses içerir).
3. Uygulama kapandıysa: yeniden açın (bu açılış `previous_run_unclean` satırını yazar), sonra `diagnostics.jsonl` ve varsa `crash-traceback.log` dosyalarını paylaşın.
4. Linux'ta ek olarak: `coredumpctl list | grep -i katip` ve `journalctl --user -b --since "<saat>" | grep -i katip`.
5. Linux/macOS'ta tekrar denerken uygulamayı terminalden başlatıp çıktısını saklayın: `katip 2>&1 | tee katip-terminal.log`. Windows paketi konsol çıktısı vermez; orada yalnız teşhis dosyaları kullanılır.

Kaydı okumak: son iş kimliğinin olaylarını sırayla izleyin. `capture_progress` beklenen süreden önce kesildiyse **kayıt/sürücü**; `failed CAPTURE_*` varsa **cihaz**; `http_finished` `NETWORK_TIMEOUT` ve süre ≈90000 ms ise **ağ zaman aşımı**; `http_status` 4xx/5xx ise **sağlayıcı**; `previous_run_unclean` ise **süreç çöktü/öldürüldü** (`source` son aşama; `crash-traceback.log` yerel yığın).

## Manuel kabul listesi (sahip ve arkadaşı)

Her satırı ilgili makinede, bu daldan derlenmiş sürümle deneyin ve sonucu not edin. Sorun çıkarsa yukarıdaki teşhis adımlarını uygulayın.

**Her platformda**
- [ ] Kısa (5 sn), 40 sn, 60 sn ve ~3 dk dikte: metin eksiksiz ve doğru yerde.
- [ ] Groq ile 40–60 sn dikte en az 5 kez (U01): hata olursa teşhis kaydı alındı.
- [ ] Dikte sırasında mikrofonu çıkarın: hata mesajı görünür, alınan ses Son Sonuç'tan kaydedilebilir, uygulama açık kalır.
- [ ] USB mikrofonu çıkarıp başka porta takın; Ayarlar'da seçili kalır ve kayıt çalışır.
- [ ] Mikrofonu sessize alıp dikte: `CAPTURE_SILENT` açıklaması görünür.
- [ ] İşlem sürerken iptal (tepsi): metin/ses korunur, yeni dikte başlatılabilir.
- [ ] Ayarlar: API anahtarı kaydet, uygulamayı kapat/aç, anahtar yerinde (işletim sistemi kasası).
- [ ] "Panoyu geri yükle" açıkken dikte: yapıştırma sonrası eski pano geri gelir; arada başka bir şey kopyalarsanız o korunur.
- [ ] Terminal Uyumluluk Modu ile bir terminale dikte.
- [ ] Uygulamayı 1 gün açık bırakıp birkaç kez kullanın; kapanınca `app_stopped` yazılmış olmalı.

**Fedora KDE Plasma Wayland (sahibin ana ortamı)**
- [ ] `ydotoold` çalışırken: editör, tarayıcı, terminalde otomatik yapıştırma.
- [ ] `ydotoold` kapalıyken: RemoteDesktop izin penceresi bir kez çıkar; onaydan sonra yapıştırma çalışır, uygulamayı yeniden açınca tekrar sormaz. İzin penceresi kapandıktan sonra metnin doğru pencereye gittiğini kontrol edin.
- [ ] İzni reddedin: metin panoya alınır ve "Ctrl+V ile yapıştırın" bildirimi gelir.
- [ ] GlobalShortcuts portalı izin ekranı; reddedince `katip --toggle` sistem kısayolu ile çalışma.
- [ ] Kayıt göstergesi editör odağını almıyor (KWin kuralı, c2d8e8d).
- [ ] USB klavyeyi çıkarıp takın; kısayol çalışmaya devam eder.

**GNOME Wayland**
- [ ] RemoteDesktop portalı ile yapıştırma (veya `ydotoold`); GTK göstergesi/Qt göstergesi odak çalmıyor.
- [ ] `wl-copy` ile panoya alma GNOME'da odağı bozmuyor (GNOME veri denetimi protokolünü desteklemez; kısa bir pencere açılabilir).

**X11 (herhangi bir masaüstü)**
- [ ] `xdotool` ile yapıştırma; Ctrl+Alt basılıyken bile Ctrl+V gider (`--clearmodifiers`).
- [ ] Dikte bitmeden başka pencereye geçin: metin yazılmaz, panoya alınır ve bildirilir.

**Windows 10/11**
- [ ] Not Defteri, tarayıcı, Word, yönetici olarak çalışan bir uygulama (UIPI nedeniyle yapıştırma engellenebilir; bildirilmelidir).
- [ ] Tepsiden başlat/durdur: hedef pencere tepsi menüsü olarak yakalanıp yapıştırma reddediliyor mu kontrol edin (bilinen risk).
- [ ] Codex/Antigravity CLI iptali: alt süreçler kalmıyor (Görev Yöneticisi).
- [ ] Credential Manager'da anahtar kaydı.

**macOS (Apple Silicon ve Intel)**
- [ ] İlk dikte: mikrofon, Erişilebilirlik ve Otomasyon izin istekleri; izin yokken açıklayıcı hata.
- [ ] TextEdit, tarayıcı, VS Code'a Cmd+V; kısayol tuşları basılıyken yanlış kısayol gitmiyor.
- [ ] Keychain'de anahtar kaydı; imzasız paket uyarısı (imzalama/noterleme yapılmadı).

## Bilinen sınırlar ve açık noktalar

- **U01 kapanmadı**; yukarıdaki kayıtla tekrarında aşama belirlenecek.
- Wayland'da hedef pencere doğrulanamaz; odaktaki pencereye yapıştırılır. RemoteDesktop izni ilk yapıştırmada istenir ve izin penceresi açıkken (en fazla ~65 sn) sıradaki dikte bekler; izin verilince hedef ve iptal yeniden denetlenir, sonra tuşlar gönderilir.
- Kısayol portalı oturum ortasında kaybolursa (portal yeniden başlatıldı) evdev'e geçilir, portal yeniden denenmez; evdev izni yoksa kısayol uygulama yeniden başlatılana kadar `katip --toggle` ile çalışır.
- Windows Job Object, CLI süreci başladıktan sonra atanır; çok hızlı başlayan bir torun süreç dışarıda kalabilir veya hemen biten bir CLI yanıltıcı `PROCESS_ISOLATION` hatası verebilir. Windows'ta doğrulanmadı.
- Gemini, bazı modellerde düşünme jetonları çıktı sınırını tüketirse yanıtı eksik sayıp reddedebilir (teslim edilmez, kayıt korunur). Gemini düz metin çıktısı eskisi gibi temizlenmiyor (B12 gereği içerik silen temizleyici kaldırıldı).
- Antigravity promptu hâlâ komut satırı argümanıyla gider (mevcut CLI protokolü).
- `config.previous.json` ilk göçten önceki dosyanın kopyasıdır; eski düz metin anahtarları içerebilir. Döndürülen/temizlenen anahtarlar kasadan otomatik silinmez (`--purge` siler). Eski sürüme dönülürse anahtarlar o sürümde boş görünür; uygulamalar kapalıyken `config.previous.json` dosyasını `config.json` yerine koyun.
- Anahtar kasası olmayan masaüstlerinde yeni API anahtarı kaydedilemez (ortam değişkenleri kullanılabilir). Bu makinede (KDE) Secret Service `ksecretd` ile mevcut.
- Ses ve sonuç yalnız bellektedir; süreç çökerse kurtarılamaz (varsayılan disk ses geçmişi bilinçli olarak yok).
- Native PortAudio çökmesi uygulamayı düşürebilir (ses ayrı süreçte değil); `crash-traceback.log` bunu kaydeder.
- Paketler imzalanmadı/noterlenmedi; sürüm iş akışı artık kilit dosyasından kurar ve testleri Windows/macOS'ta da çalıştırır, ilk etiketli sürümde bu adım ilk kez koşacaktır.

## Protokol kaynakları

[QNetworkReply.abort](https://doc.qt.io/qt-6/qnetworkreply.html#abort) · [QProcess](https://doc.qt.io/qt-6/qprocess.html) · [XDG GlobalShortcuts](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) · [XDG RemoteDesktop](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html). Bunlar yerel uyarlamanın gerçek masaüstü testinin yerine geçmez.
