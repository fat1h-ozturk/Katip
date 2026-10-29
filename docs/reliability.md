# Güvenilirlik uygulaması — yerel aday

29 Ekim 2026 · Dal: `reliability/long-dictation` · Temel: `0fc304b` / v0.4.6

Kaynak değişiklikleri ve ayrı Linux aday paketi hazırlandı. Kurulu v0.4.6 değiştirilmedi; uzaktaki depoya gönderim veya yayın yapılmadı. **U01 henüz kapalı değil:** Groq ile yaklaşık 25. saniyede görülen gerçek hata, hata metni veya olay kaydı olmadan kesin teşhis edilemedi. Bu çalışma o olayın yeniden oluşması halinde veriyi koruyan ve aşamasını belirleyen bir sağlamlaştırma adayıdır.

## Neler değişti?

| Alan | Uygulama |
|---|---|
| Kayıt ve kurtarma | Ham PCM, DSP sonucundan ayrı tutuluyor. VAD reddi, mikrofon kopması ve işleme hatasında alınmış örnekler korunuyor. Filtresiz yeniden işleme ve gerçek örnekleme hızında ham WAV kaydı var. Yeni kayıt önceki sesi sessizce silmiyor. |
| Uzun kayıt | 10 dakika / 64 MiB ham PCM sınırı açık hatayla duruyor. 44,1/48 kHz girişler soxr ile filtreli olarak 16 kHz'e çevriliyor. Son kısmi VAD karesi korunuyor; büyük Python sayı listeleri kaldırıldı. |
| Arayüz | Capture drain, DSP, sağlayıcı ve teslim işleri tek iş kuyruğunda GUI dışında çalışıyor. Sonuçları yalnız Qt olay köprüsü GUI durumuna uyguluyor. Cihaz tarama ve mikrofon testi de arka planda. |
| Oturum | `SessionController`, `job_id`, deneme numarası, derin ayar kopyası, kayıt başlangıcındaki hedef ve iptal belirteci var. Eski sonuç/callback yeni oturuma uygulanmıyor. Busy bilgisi bu durumdan türetiliyor. |
| Sağlayıcılar | Altı sağlayıcı ortak değişmez sonuç sözleşmesi kullanıyor. OpenAI/Claude prompt imzası düzeltildi. Metin tanıma başarısı formatterdan önce korunuyor. Yeniden düzenleme doğru sağlayıcı/model ile çalışıyor, ikinci STT çağrısı yapmıyor. Gemini için bu yetenek kapalı. |
| Çıktı kontrolü | JSON alanları, türler, tamamlanma nedenleri ve CLI protokolü doğrulanıyor. Eksik/bozuk çıktı otomatik teslim edilmiyor. Bağlam hesabında önce isteğe bağlı ipuçları azaltılıyor; ham transkript kesilmiyor. Model seçimi otomatik değiştirilmedi. |
| Ağ | QtNetwork, toplam istek süresi ve fiziksel `abort` kullanılıyor. Varsayılan STT ve formatter sınırları 90 saniye; işleme toplamı 180 saniye. Kayıt süresi bu saate dahil değil. Otomatik ücretli tekrar veya sağlayıcı geçişi yok. |
| CLI | QProcess, çıktı sınırı, iptal, Unix süreç grubu ve Windows Job Object temizliği eklendi. Codex promptu stdin üzerinden gidiyor. Antigravity'nin mevcut komut protokolü korunuyor. Sistem araçlarına paketli Qt/LD ortamı aktarılmıyor. |
| Teslim ve pano | Hedef kayıt başında alınarak teslim öncesinde ve pano senkronizasyonundan sonra karşılaştırılıyor. İptal de yapıştırma öncesinde tekrar kontrol ediliyor. Başarı metni “girdi gönderildi”; uygulamanın metni aldığı iddia edilmiyor. Pano geri yüklemesi sürüm ve içerik kontrolü yapıyor. |
| Masaüstü | Wayland GlobalShortcuts portalı, izin durumu, evdev yeniden keşfi ve descriptor temizliği eklendi. GTK helper ayrı giriş, READY el sıkışması ve Qt geri dönüşü kullanıyor. |
| Ayarlar ve gizlilik | Şema sürümü, bilinmeyen alanların korunması, tek geri dönüş yedeği ve OS anahtar kasası var. Başarısız disk/kasa yazımında önceki ayarlar korunuyor. Teşhis kayıtları içerik taşımıyor; boyutları sınırlı. Güncelleyici testi gerçek worker metodunu çağırıyor. |
| Sürekli kontrol | `uv.lock`, dışa aktarılmış pip kilidi, push/PR matrisi, lint ve çekirdek tip denetimi eklendi. Yeni oturum/teşhis/HTTP modüllerinde satır ve dal kapsamı için %90 CI kapısı var; diğer modüller raporlanıyor. |

## Kullanıcıya yansıyan davranışlar

- Hata sonrası **Son Sonuç**: ham/düzenlenmiş metin, teşhis, metni yeniden düzenleme, sesi yeniden işleme, filtresiz tekrar, ham WAV kaydetme ve açık temizleme.
- Sonuç metnini açıkça kopyalamak, sesi başarıyla kaydetmek veya temizlemek korunmuş kaydı bırakır ve yeni dikteye izin verir. Teşhis metnini kopyalamak sesi bırakmaz.
- **Wayland'da genel hedef pencere kimliği doğrulanamadığından otomatik yapıştırma yapılmaz.** Sonuç hazır tutulur ve elle kopyalanır. Bu, önceki davranışa göre bilinçli bir değişikliktir.
- Linux'ta güvenilir pano sürüm takibi henüz yok. “Panoyu geri yükle” açıkken mevcut pano korunur ve işlem açıklamayla durur. Windows/macOS sürüm kaynakları eklendi; gerçek masaüstü kabulü bekliyor.
- Ayarlardaki yapıştırma testi açık bir test alanına yönelir ve yalnız alanın içeriği eşleşirse “doğrulandı” der. Diğer durumda gönderim ile doğrulama ayrılır.
- İşleme sırasında iptal ve kaydı kurtarma mümkündür. Çıkış, alınmış ses için önce kopyalama/kaydetme/temizleme ister. Native sürücü çağrısında kilitlenen thread zorla öldürülmez.

## Yerel doğrulama

Son doğrulamanın sayısal kaydı: [validation/2026-10-29-summary.json](validation/2026-10-29-summary.json). Performans ayrıntıları: [validation/2026-10-29-performance.json](validation/2026-10-29-performance.json).

| Kontrol | Sonuç / sınır |
|---|---|
| Linux Python 3.10.22, 3.11.17, 3.14.8 | Her birinde **298 geçti, 12 performans testi bilinçli atlandı**. Temiz ortamlar kilitli bağımlılıklarla kuruldu. Performans paketi ayrıca çalıştırıldı. |
| Uzun yakalama | Sahte cihazla 20/24/25/26/40/60/180/300/600 saniye; 25 saniyede cihaz hatası ve alınan örneklerin kurtarılması; boyut sınırının tam sınır/üzeri; VAD reddi. Gerçek mikrofon kullanılmadı. |
| Qt iş parçacıkları | Gerçek executor ve Qt sinyalleriyle capture/DSP/sağlayıcı GUI dışında, sonuç commitleri GUI üzerinde. Cihaz, IPC ve işletim sistemi girdi sınırları sahte. |
| Ağ | Gerçek localhost sunucusunda JSON/multipart, 401/403/404/413/429/500/503, yavaş ve sürekli akan yanıt, kopma, yanıt boyutu sınırı, iptal ve toplam süre. Canlı API çağrılmadı. |
| Sağlayıcılar | Altı adaptörde ortak başarı, STT timeout ve bozuk çıktı kontrolleri; ayrıca kesilmiş formatter çıktısı, CLI protokol ihlali, bağlam sınırı ve ham metin koruma testleri. Hesap/model erişimi doğrulanmadı. |
| Süreçler | Gerçek yerel çocuk süreçte UTF-8, bulunamayan komut, iptal, timeout ve torun süreç temizliği. Linux süreci üzerinde doğrulandı; Windows native mekanizması çalıştırılmadı. |
| Dayanıklılık | 100 kısa oturumda önceki sonuçların reddi; pano senkronizasyonu sırasında hedef değişmesi/iptal; yeni kullanıcı kopyasının korunması; kasa yazma ve ayar rollback hataları. 100 oturum testi tüm GUI/native sürecin sızıntı testi değildir. |
| Performans | 12 ek test: 40/60/300/600 saniye × 16/44,1/48 kHz. En yüksek GUI p95 **30,44 ms**, p99 **30,56 ms**, örneklenmiş ek RSS **75,88 MiB**, DSP süresi **4,2 sn**. Kaynak uygulama, sentetik PCM ve tüm kareleri kabul eden VAD; paket veya gerçek konuşma kalitesi ölçümü değildir. |
| Statik kontroller | `ruff check katip`, daraltılmış çekirdek `mypy`, `git diff --check`, `uv lock --check` ve iki kilidin eşdeğerliği. Tüm depoya tip güvenliği iddia edilmiyor. |
| Linux paket | PyInstaller 6.20.0 ile yaklaşık 99 MiB tek dosya. Ayrı profilde `--version` ve `--status` başarılı. Kurulu paketle aynı sürüm metnini taşısa da farklı SHA-256 ile ayrı tanımlandı. |
| Sonuç penceresi | Offscreen Qt görüntüsü incelendi; 700 px genişliğe sığıyor. Gerçek masaüstü odak/izin testi değildir. |

Normal test çalışmasında performans testleri bilinçli atlanır; ayrı çalıştırmada 12'si de geçti. Toplam kapsama ve modül bazlı satır/dal sayıları doğrulama JSON'unda bulunur. Tüm çekirdek modüllerde %90 dal kapsamı hedefi henüz sağlanmış değildir.

## Açık kabul adımları ve tasarımdan sapmalar

1. **U01 / T30:** gerçek Groq hatası kaynak ve aday pakette 40/60 saniye konuşmayla yeniden yakalanmalı. Timeout değerinin artırılması kök neden kanıtı değildir. Kurulu paketin kaynak commitine eşitliği bilinmiyor.
2. **T21–T24:** Windows, iki macOS mimarisi, gerçek KDE/Wayland, portal izin ekranı, USB klavye tak/çıkar, mikrofon izinleri, terminal/normal alan ve paketli helper kabulü yerel olarak tamamlanmadı. CI matrisi eklendi; uzaktaki CI çalıştırılmadı. İmzalama/noterleme yapılmadı.
3. **T12/T29:** paket üzerinde uzun kayıt/RSS/GUI gecikmesi ve 100 tam uygulama oturumunda süreç/descriptor artışı henüz ölçülmedi. Kaynak DSP ölçümü bunların yerine sayılmadı.
4. **T05/T16/T25:** canlı sağlayıcı erişimi, model hesap yetenekleri, TLS/proxy, yavaş gerçek yükleme, OS kasası kilit/izin ekranı ve eski yayımlanmış paketle gerçek rollback provası bekliyor. Bu çalışma canlı API veya kullanıcı anahtarı kullanmadı.
5. Ham PCM sahipliği `AudioRecorder` içinde kilit ve çalışan thread kontrolüyle tutuldu; ayrı `CaptureBuffer`/lease sınıfı eklenmedi. Küçük adaptörler yeni dosyalara ayrıldı, fakat bütün akış `pipeline.py`/`recovery.py` dosyalarına taşınmadı. `app.py` hâlâ önemli bir koordinatördür.
6. Ayrı Transcript/CaptureMetadata/DeliveryResult sınıfları yerine ortak sonuç, olay ve hedef değerleri kullanıldı. Durum geçişleri açık; iptal UI'yi hemen kurtarılabilir hata durumuna geçirir. Tüm soyut tiplerin eklenmiş olduğu iddia edilmiyor.
7. QtNetwork her isteğin nesnelerini, tek executor iş parçacığında kendi Qt event loop'unda oluşturur. Her iş için yeni ağ nesnesi kullanılır; kalıcı bağlantı havuzu yoktur. CLI sınırlı QProcess üzerinden gider; kısa sistem komutları timeout ve ortak temiz ortam kullanır, hepsi QProcess'e taşınmadı.
8. Yerel iptal uzak sağlayıcının işi veya ücreti geri almaz. İşletim sistemine gönderilmiş girdi geri çekilemez. Native PortAudio çökmesi aynı süreci etkileyebilir; ses ayrı süreçte izole edilmedi.
9. Süreç çökmesi uygulama içinden güvenilir biçimde sınıflandırılmadı. Bu makinedeki `coredumpctl` sorgusunda Kâtip kaydı yoktu; bu geçmişte çökme olmadığını kanıtlamaz. `PROCESS_CRASH` otomatik tespiti tamamlanmış sayılmaz.
10. OS kasa yazımı ile JSON dosyası arasında ortak transaction yoktur. Yeni referanslar önce yazılır, başarısız dosya kaydında silme denenir; kasa silme işlemi de başarısız olursa artık referans manuel inceleme gerektirebilir. Eski geçerli anahtar üzerine yazılmaz. Bir defalık ayar yedeği eski düz metin anahtarları içerebilir.

Bu nedenle bütün T01–T30 kabul matrisi yeşil olarak kapatılmadı. Yerel uygulama/test işi tamamlandı; gerçek olay ve platform kabulü açıkça ayrı tutuluyor.

## Adayı denemek ve geri dönmek

```bash
KATIP_PROFILE=reliability ./dist/reliability/Katip
```

Paket bu çalışma alanında yereldir; `dist/` Git'e dahil edilmez. `dist/reliability/build-info.json` kaynak ağacı, kilit, paket ve kurulu binary kimliklerini kaydeder. Aday profil kendi ayar ve IPC alanını kullanır; kurulu uygulamanın anahtarlarını/legacy ayarlarını otomatik taşımaz. Açıkça geçirilen API ortam değişkenleri uygulanmaya devam eder.

Üretim profiline kurulmadığı için geri dönüş, adayı kapatıp mevcut kurulu uygulamayı kullanmaktır. Gelecekte üretim ayarları kasaya göç ettirilirse, eski sürüme dönüşte uygulamalar kapalıyken `config.previous.json` yedeği gerekir. `--purge` kasa referanslarını da temizlemeye çalışır; kasa kilitliyken tam silme başarısı bildirmez.

## Protokol kaynakları

Qt ağ iptali [QNetworkReply.abort](https://doc.qt.io/qt-6/qnetworkreply.html#abort), süreç yönetimi [QProcess](https://doc.qt.io/qt-6/qprocess.html) ve portal sözleşmesi [XDG GlobalShortcuts](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html) üzerinden kontrol edildi. OpenAI çıktı bütçesi ve örnekleme alanları [Chat Completions referansı](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) ile karşılaştırıldı. Bunlar yerel uyarlamanın test kanıtının yerine geçmez.
