# Kâtip güvenilirlik uygulama planı

Tarih: 29 Ekim 2026 · Kaynak temel: v0.4.6 / 0fc304b · Durum: yerel uygulama ve doğrulama yapıldı; canlı olay/platform kabulü açık. Güncel kanıtlar ve tasarımdan sapmalar: [uygulama durumu](../reliability.md).

## 1. Hedef ve kapsam

Önce Groq uzun dikte olayının kök nedenini yakalayıp düzeltmek; ardından sağlayıcılar, kayıt kurtarma, iş yaşam döngüsü ve masaüstü teslimini ortak kurallara bağlamak. Mevcut Python + PySide6, işletim sistemi desteği ve kullanıcı ayarları korunarak aşamalı geçiş yapılır.

Bu belge, önceki incelemedeki B01–B15 bulgularının tamamını ve yeni U01 kullanıcı olayını kapsar. Mikroservis, yeni uygulama çatısı, gerçek zamanlı streaming, sınırsız kayıt veya varsayılan disk ses geçmişi kapsamda değildir.

## 2. Kullanıcının yeni hata bildirimi

Kullanıcı Groq ile yaklaşık 40 saniyelik konuşma yaptığını, yaklaşık 25. saniyede hata gördüğünü bildirdi. Hata metni hatırlanmıyor. Yalnız kaydın mı yoksa bütün uygulamanın mı kapandığı ve 25 saniyenin kayıt başlangıcına mı durdurmaya mı göre sayıldığı henüz doğrulanmış değil.

### Kanıt ve belirsizlikler

- **Bilinen:** Kaynak kodda süreye bağlı otomatik kayıt durdurma sayacı bulunamadı. Ağ isteği kayıt durdurulup WAV hazırlandıktan sonra başlıyor. (katip/audio.py:159; katip/app.py:293)

- **Bilinen:** Groq STT varsayılan timeout değeri 25 saniye. Bağlantı ve timeout hataları aynı genel “Groq Whisper bağlantı hatası” metnine çevriliyor. (katip/services/groq.py:118–140)

- **Bilinen:** Şu an yerel ayarlar Groq, whisper-large-v3, qwen/qwen3.8-27b, VAD=2 ve toggle. Bu bilgi olay anındaki ayarları kesin kanıtlamaz. (Yalnız gizli olmayan yerel ayar alanları okundu.)

- **Çıkarım:** Normal 16 kHz/16 bit/mono WAV için 40 saniye yaklaşık 1.280.044 bayt, yani 1,28 MB. Groq’un belgelenen 25 MB doğrudan dosya yükleme sınırına yaklaşmaz. (Yerel WAV biçimi + Groq STT belgesi, 29 Ekim 2026.)

- **Açık:** Kayıt sürerken cihaz okuması mı kesildi, beklenmeyen stop mu geldi, işlem sonrasında ağ mı zaman aşımına uğradı, yoksa süreç mü çöktü? (U01 — ilk iş paketinde ölçülecek; kök neden henüz yok.)

25 saniye kayıt süresi ile 25 saniye ağ beklemesi ayrı saatlerdir. Ağ timeoutunu artırmak yalnız ölçüm ağ aşamasını gösterirse ilgili bir düzeltmedir; bu değişiklik tek başına U01’i çözmüş sayılmaz.

## 3. Mevcut doğrulama temeli

Önceki incelemede 204 test geçti; satır kapsamı %55,96, dal kapsamı %40,28. Bu testler Python 3.14.8 ve mevcut sistem PySide6/PyAudio paketleriyle ayrı ortamda çalıştırıldı. Temiz Python 3.11 kurulumu portaudio.h eksikliğinde kaldı. Kaynak ve kurulu paket eşdeğerliği henüz kanıtlanmadı. Plan hazırlanırken uygulama testleri tekrar çalıştırılmadı; üretim kodu değişmedi.

## 4. Mimari kararlar

### Tek uygulama, Python + Qt

Korunacak. Çekirdek tipler ve uygulama akışı UI’den ayrılacak; bütün ürünü yeniden yazmak bu kapsamda yok.

### Uzun kayıt

İlk hedef tek oturumda 10 dakika. Yerel süre/boyut tavanı görünür ve güvenli; 25 saniyelik kayıt kesme kuralı eklenmeyecek.

### Parçalama/streaming

İlk düzeltmede yok. 40 saniye tek başına dosya sınırını açıklamıyor. Daha uzun süre istenirse bağlam, parça sınırı ve tekrar eden kelime testleriyle ayrı özellik olarak tasarlanacak.

### Ağ iptali

Hedef QtNetwork transportu + QNetworkReply.abort ve toplam aşama zamanlayıcısı. Python threadini zorla sonlandırmak iptal çözümü sayılmayacak.

### Sesin diskte saklanması

Varsayılan bellek politikası korunacak. Otomatik kalıcı ses kurtarma ayrı, açık seçimli ürün işi; bu planın zorunlu bağımlılığı değil.

### Sağlayıcı değiştirme/tekrar

Sessiz sağlayıcı geçişi ve belirsiz timeout sonrası otomatik yeniden ücretlendirme yok. Kullanıcı başarısız aşamayı yeniden deneyebilecek.

## 5. Hedef sözleşmeler ve veri sahipliği

- CaptureBuffer ham PCM ve metadata sahibidir; filtrelenmiş çıktı ayrı tutulur. Referans sayımı/okuma kiralarıyla worker hâlâ kullanırken silinmez.
- DictationRequest değişmez ayar kopyası taşır. job_id oturumu, attempt_id o oturumdaki denemeyi ayırır.
- Transcript, STT bittiği anda saklanır; formatter başarısına bağlı değildir.
- DictationResult sağlayıcı/metin/model/uyarı/aşama sürelerini taşır; anahtar içermez.
- ProviderError aşama ve kısa kod içerir; timeout, HTTP, iptal ve eksik çıktı ayrılır.
- SessionController durumun tek sahibidir. UI ve workerlar bu nesnenin verisini ayrı ayrı değiştirmez.
- ProviderCapabilities doğrudan ses-metne, STT ve yeniden düzenleme yeteneklerini bildirir.
- DeliveryResult panoya kopyalama, girdi gönderme, teyit ve belirsiz teslimi ayrı gösterir.

## 6. Uygulama sırası ve iş paketleri

İP01 ile teşhis ve hızlı CI başlar. İP02 → İP03 → İP04 çekirdeği taşır. İP05 ağ/CLI iptalini, İP06 teslimi, İP07 platformu ve İP08 ayar/gizliliği tamamlar. İP09’un yayın kabulü bütün paketler tamamlanınca kapanır. Her iş paketi gerekirse 1–2 küçük, tek amaçlı PRa bölünür; PR adları burada planlama birimidir, GitHub üzerinde oluşturulmuş kayıt değildir.

### İP01 — Önce Groq’taki 25 saniye olayını sınıflandır

**Öncelik:** İlk öncelik  
**Bağımlılık:** Yok  
**İnceleme eşlemesi:** Yeni olay U01; B11, B14  
**Dosyalar:** katip/audio.py, katip/app.py, katip/services/groq.py; yeni diagnostics.py ve uzun dikte regresyon testleri

**Yapılacak işler:**

- Kurulu v0.4.6 paketinin kimliğini ve kaynak commitini ayrı kaydet; sürüm numarası aynı diye ikisini birebir aynı derleme sayma. Baseline test sonucunu ve mevcut ayarların yalnız gizli olmayan alanlarını raporla.
- Oturum kimliği, artan sıra numarası ve monotonic zamanla recording_started, stop_requested, capture_stopped, preprocessing_started/finished, stt_started/finished, formatter_started/finished, delivery_started/finished, failed olaylarını üret. Stop olayında kaynağı kaydet: kısayol, IPC, tepsi, sürücü hatası, kaynak sınırı, kullanıcı iptali.
- CAPTURE_DEVICE_LOST, CAPTURE_READ_ERROR, CAPTURE_DRAIN_TIMEOUT, NETWORK_TIMEOUT, HTTP_ERROR, OUTPUT_INCOMPLETE ve PROCESS_CRASH durumlarını ayır. PyAudio hatasının tür/errno bilgisini izinli alanlarla tut; ham exception metnini, istek gövdesini, anahtarı ve transkripti loglama.
- Sahte saat/cihaz/ağ ile 20, 24, 25, 26, 40, 60 ve 180 saniye senaryolarını beklemeden çalıştır. Kaydın 25. saniyesinde sürücü hatası ile kayıt bittikten 25 saniye sonra ağ timeout olayını ayrı yeniden üret.
- Gerçek cihaz doğrulamasında kısa ve 40/60 saniyelik kayıtları kaynak uygulamada ve ayrı test paketinde dene; API testi yerel hata testlerinden ayrı ve sayısı sınırlı olsun. Kullanıcının normal çalışan uygulamasını değiştirme.
- Hata mesajı veya neden henüz yakalanmazsa U01 açık kalır. Timeout artışı tek başına bu olayı kapatmaz; ölçüm sonucu hangi aşamayı gösteriyorsa düzeltme o katmanda yapılır.

**Bitmiş sayılma koşulları:**

- T01: STOP komutu veya cihaz hatası olmadan, kayıt 25. saniyede durmaz; testte kayıt boyunca sıfır STT/LLM isteği vardır.
- T02: stop → STT isteği → 25 saniye timeout ayrı zaman damgalarıyla görülür; kullanıcıya “Ses tanıma zaman aşımı; kayıt korunuyor” gösterilir.
- T03: cihaz okuması kesilirse bir kez capture_error olayı üretilir; önceki kareler kurtarılabilir kalır. Erişilemeyen/henüz gelmemiş kareler korunmuş sayılmaz.
- T04: yerel teşhis özeti oturum kimliği, aşama, süre, kaynak boyutu ve hata kodu içerir; anahtar/ses/transkript içermez.

### İP02 — Ortak sonuç sözleşmesi ve sağlayıcı kırıklarını düzelt

**Öncelik:** İlk güvenilir sürüm  
**Bağımlılık:** İP01  
**İnceleme eşlemesi:** B01, B02, B05, B06, B12  
**Dosyalar:** yeni katip/domain/models.py, errors.py; katip/services/*.py, katip/prompts.py, katip/app.py; sağlayıcı sözleşme testleri

**Yapılacak işler:**

- Değişmez DictationRequest, CaptureMetadata, Transcript, DictationResult, ProviderError, ProviderCapabilities ve DeliveryResult tiplerini oluştur. İstek seçilmiş sağlayıcı/mod/sözlük/alias/dil/model ayarlarının kopyasını taşır; anahtarlar sonuç nesnesine konmaz.
- Sonuçta job_id, kaynak sağlayıcı, gerçek kullanılan model kimlikleri, ham transkript (varsa), düzenlenmiş metin (varsa), uyarılar ve aşama süreleri bulunur. Gemini doğrudan ses-metne özelliğini korur; olmayan ham transkript için None kullanılır.
- OpenAI/Claude prompt imzasını düzelt. Ortak mod kuralları sağlayıcıdan bağımsız olsun; sözlük ve transkript kullanıcı verisi olarak ayrı taşınsın. Sağlayıcıya özgü protokol/çıktı kodlaması adaptörde kalsın.
- Tüm metin adaptörlerinde yanıt türünü ve tamamlanmayı doğrula. Eksik çıktı, yanlış JSON alan türü, başarısız CLI ve boş yanıt otomatik yapıştırılmasın. Düz stdout tanılama cümlesi geçerli sonuç sayılmasın.
- Yeniden düzenlemeyi sonucu üreten formatter kimliği ve kayıtlı ayarlarla çalıştır. Yeteneği olmayan sağlayıcıda düğme açıklamayla kapalı olsun; başka sağlayıcıya gönderme açık kullanıcı seçimi gerektirsin.
- Önbellek anahtarına bütün ilgili servis ayarlarını, özellikle stt_model alanını ekle; bütün servislerin kapatma yaşam döngüsünü ortaklaştır. Eski GroqResult için geçici adaptör kullan ve tüketiciler taşınınca kaldır.

**Bitmiş sayılma koşulları:**

- T05: altı sağlayıcı aynı başarı/boş/timeout/bozuk çıktı/eksik yanıt sözleşme paketinden geçer; gerçek prompt fonksiyonu testte devrededir.
- T06: OpenAI ve Claude başarılı sahte STT’den sonra TypeError vermeden sonuç üretir; formatter hatasında ham transkript hazır kalır.
- T07: yeniden düzenleme doğru formattera gider, ikinci STT isteği üretmez; desteklenmeyen yetenek yanlış sağlayıcıya sessizce yönlenmez.
- T08: ses modeli değiştiğinde Claude/Codex/Antigravity dâhil bütün adaptörler yeni modeli kullanır; eski servis kaynakları kapanır.

### İP03 — Ham sesi koru ve uzun kaydı arayüzden ayır

**Öncelik:** İlk güvenilir sürüm  
**Bağımlılık:** İP01 + İP02 tipleri  
**İnceleme eşlemesi:** U01; B03, B07  
**Dosyalar:** katip/audio.py; yeni audio_buffer.py, audio_processing.py; katip/ui/settings.py; ses yaşam döngüsü ve performans testleri

**Yapılacak işler:**

- CaptureBuffer ham karelerin sahibidir; örnekleme hızı, kanal, örnek genişliği ve süreyi taşır. DSP türetilmiş çıktı oluşturur; stop/drain, VAD veya kodlama başarısızlığı ham tamponu temizlemez.
- Ham kayıt yalnız açık temizleme, başarılı kaydetme, tanımlı oturum tamamlama veya saklama politikasında bırakılır. VAD tüm sesi reddederse filtresiz yeniden işleme ve sesi kaydetme mümkündür. “Sesi Kaydet” kurtarmada ham WAV kaydeder; işlenmiş ses ayrı tanımlanır.
- Capture durdurma, resampling, VAD ve WAV kodlama GUI dışında çalışır. İki saniyelik driver join ana olay döngüsünde bekletilmez. GUI, stop istendiğini hemen gösterir ve sonucun olayını bekler. Ses sürücüsünün sahibi streami kapatır.
- Büyük Python sayı listeleri yerine sınırlı bloklar ve tampon görünümleri kullan. Başta/sonda kalan PCM örneklerini düşürme. 44,1/48 kHz → 16 kHz dönüşümünde uygun alçak geçiren filtreli resampling kullan; seçilen küçük bağımlılık/lisans/paket boyutu ayrıca doğrulanır.
- İlk destek hedefi 10 dakikalık tek dikte; başlangıç yerel tavanı 10 dakika veya 64 MiB ham PCM’den önce dolanıdır. 40 saniyelik kayıt bu sınırlara yaklaşmaz. Tavan kullanıcıya görünür olur; ulaşılırsa ses korunup “Kayıt sınıra ulaştı” durumuna geçilir, sessiz kırpma veya tamamlanmış gibi yapıştırma olmaz.
- Mikrofon testi ve aygıt taraması aynı audio backend üzerinden arka planda yürüsün; gerçek kayıttan farklı sample-rate/fallback davranışı kullanmasın. Sınırsız ses efekti threadleri yerine sınırlı bir oynatma kuyruğu kullan.

**Bitmiş sayılma koşulları:**

- T09: VAD yanlış olumsuz, kodlama hatası, durdurma timeout ve mikrofon kopmasında alınmış ham örnekler kaybolmaz; dosyaya kaydedilebilir.
- T10: 40/60 saniye ve 5/10 dakika sentetik girdiler, 16/44,1/48 kHz ve sessizlik/karışık ses testleri geçer; örnek sayısı ve sıra kontrol edilir.
- T11: 10 dakika/64 MiB sınırı tam sınırın öncesi/üzeriyle test edilir; yeni kayıt için örtük veri silme yapılmaz.
- T12: referans cihazda GUI olay gecikmesi hedefi p95 <100 ms; yoğun DSP altında p99 <250 ms. Ek tepe RSS için başlangıç hedefi 2 × ham ses boyutu +64 MiB; taban Qt belleği hariç, kaynak ve paket ayrı ölçülür. Bunlar doğrulanacak hedeflerdir.

### İP04 — Oturum durumlarını ve hata kurtarmasını tek elde topla

**Öncelik:** Çekirdek mimari  
**Bağımlılık:** İP02 + İP03  
**İnceleme eşlemesi:** B02, B07, B11, B13  
**Dosyalar:** yeni katip/application/session.py, pipeline.py, recovery.py; katip/app.py ve UI bağları

**Yapılacak işler:**

- IDLE → RECORDING → DRAINING → PREPROCESSING → TRANSCRIBING → FORMATTING → READY → DELIVERING → COMPLETED geçişlerini tanımla; Gemini TRANSCRIBING → READY yolu kullanabilir. Geçerli aşamalardan RECOVERABLE_ERROR, CANCELLING ve SHUTTING_DOWN yollarını açıkça tanımla.
- Durum geçişlerinin tek sahibi SessionController olsun. Capture ve provider workerları doğrudan last_text/is_busy_processing alanlarını yazmaz; job_id ve attempt_id taşıyan olaylar gönderir. Qt köprüsü olayları tek sahipte uygular.
- Ses tanıma başarıyla bittiğinde transkript formatterdan önce kaydedilir. Formatter tekrarında ses tanıma çağrılmaz; teslim tekrarında ağ çağrılmaz. Kullanıcının yeni denemesi eski başarılı sonucu doğrulanmış yeni sonuç gelene kadar silmez.
- Dikte başlamadan önce ayarları kopyala. Hedef pencere kimliği de destekleniyorsa o anda alınsın. Ayar kaydı, sonuç penceresi, kısayol, iptal ve çıkış komutları aynı geçiş tablosundan yetkilendirilsin.
- Kayıt/işleme sırasında ikinci dikte kuyruğa alınmasın; aynı komutun tekrar gelmesi tanımlı ve testli davranış olsun. Geç gelen eski hata/sonuç/cihaz callbacki yeni oturuma uygulanmasın.
- Kapatma için kullanıcıya bekle/iptal edip kaydı koru davranışı sun. Qt pencereleri ve threadler sıralı kapansın. Sürücü native çağrıda kilitlenirse güvenli biçimde sonlandırılamayan Python threadini zorla öldürme; bu durum ayrı teşhis ve gerekirse süreç izolasyonu gerektirir.

**Bitmiş sayılma koşulları:**

- T13: her geçerli ve geçersiz durum geçişi saf birim testle kapsanır; eski is_busy_processing kararlarının iki ayrı otoritesi kalmaz.
- T14: hızlı çift toggle, geç stop, ayar penceresi açıkken start, eski işin geç yanıtı ve kapanış sırasında callback senaryoları geçer.
- T15: formatter hatası sonrası yeniden denemede STT çağrı sayısı değişmez; başarısız teslimde sonuç ve alınmış ses korunur.

### İP05 — İptal edilebilir ağ ve CLI görevleri

**Öncelik:** Çekirdek mimari  
**Bağımlılık:** İP02 + İP04  
**İnceleme eşlemesi:** U01; B11, B12, B15  
**Dosyalar:** yeni katip/infrastructure/http_transport.py, process_runner.py, job_runner.py; bütün servis adaptörleri

**Yapılacak işler:**

- Sağlayıcı kodu HTTP kitaplığından ayrılan Transport sözleşmesine bağlı olsun. İlk hata düzeltmeleri mevcut Requests ile kalabilir; hedef transport, mevcut PySide6 QtNetwork modülü üzerinden QNetworkAccessManager/QNetworkReply kullanır. Alan katmanı Qt’ye bağımlı olmaz.
- Ağ nesneleri tek bir event-loop threadinde oluşturulup kullanılır. Multipart ses yükleme, HTTP durumları, JSON gövdesi, hata ve iptal tek adaptörde normalize edilir. Slotlarda büyük JSON/DSP işi yapılmaz; SSL doğrulaması kapatılmaz.
- İstek başlangıcından sayılan QTimer toplam aşama son süresini yönetir; kullanıcı iptali/son süre QNetworkReply.abort çağrısına gider. Çift error/finished olayı tek bir terminal sonuç üretir. Yerel iptal, uzak sunucunun yaptığı işi veya olası ücreti geri almış sayılmaz.
- İlk doğrulama profili: STT aşaması 90 sn, formatter 90 sn, kayıt durdurulduktan sonraki tüm işlem 180 sn üst sınır. Kayıt süresi bu saate dâhil değildir. Değerler ölçümle kalibre edilir; bağlantı, yükleme ve yanıt süreleri gözlemlenir. Bu değerleri koymak U01’in nedenini kanıtlamaz.
- CLI tarafında QProcess tabanlı yönetici kullan; stdout/stderr boyutunu sınırla, promptu mümkün olan protokolde stdin ile ilet. İptalde önce kontrollü bitir, sonra süreli terminate/kill; açılan alt süreçler Unix süreç grubu/Windows Job Object gibi platform mekanizmasıyla temizlensin. Yalnız QProcess.kill süreç ağacının kapandığı kabul edilmesin.
- Varsayılan otomatik bulut tekrarı yok: timeout veya kopmada isteğin sunucuda işlenip işlenmediği belirsiz olabilir. Hata sınıfını gösterip kullanıcının yalnız başarısız aşamayı tekrar etmesini sağla. 401/403/404 yeniden denenmez; 429 için Retry-After bilgisi gösterilir. Başka sağlayıcıya otomatik veri gönderilmez.

**Bitmiş sayılma koşulları:**

- T16: yerel HTTP test sunucusunda yavaş yükleme/yanıt, sürekli küçük parçalar gönderme, kopma, 401/403/404/413/429/5xx ve bozuk JSON testleri; aşama son süresi gerçekten isteği abort eder.
- T17: iptal/timeout/normal bitiş yarışı tam bir terminal olay üretir; eski iş UI’ye dönemez. GUI iptal isteğine hedef olarak <100 ms’de durum geri bildirimi verir.
- T18: CLI ve onun çocuk süreci, iptal/kapanış testinden sonra kalmaz. Normal timeoutta ham transkript ve sesin kurtarma yolları açıktır.

### İP06 — Doğru hedefe teslim ve pano sahipliği

**Öncelik:** Masaüstü güvenilirliği  
**Bağımlılık:** İP04; iptal entegrasyonu için İP05  
**İnceleme eşlemesi:** B08, B09  
**Dosyalar:** katip/injector.py; yeni platform/target.py, clipboard.py, delivery.py; sonuç/tepsi/kapsül görünümleri

**Yapılacak işler:**

- TargetSnapshot desteği olan ortamlarda iş başında hedefi al; yapıştırmadan hemen önce karşılaştır. Başka uygulama odaktaysa otomatik yapıştırmayı durdur, sonucu hazır göster. Wayland gibi hedef bilgisinin eksik olduğu ortamlarda destek düzeyini açık bildir; doğrulanamayan hedefi kesinmiş gibi kullanma.
- DeliveryResult; COPIED, INPUT_SENT, CONFIRMED (yalnız destekleniyorsa), FAILED ve UNCERTAIN durumlarını ayırsın. Kullanıcı metni gerçekten almış gibi yanlış başarı mesajı gösterme. UNCERTAIN durumunda otomatik tekrar yok.
- Pano geri yüklemeden önce sahiplik/sürüm değişimini kontrol et. Kâtip’in yazdığı veriden sonra başka kopyalama olduysa eski panoyu geri yazma. Yalnız metin kıyaslamasını platform sequence değeri yerine kesin kanıt sayma.
- Pano biçimleri güvenle korunamıyorsa mevcut muhafazakâr davranışı koru. Yapıştırma testi, ayarlar penceresine tuş göndermek yerine açık test hedefi ve sonuç kontrolü kullansın; terminal modu/normal alan farkı görünür olsun.

**Bitmiş sayılma koşulları:**

- T19: A panosu → dikte → kullanıcı B kopyalar akışında son pano B kalır; metin dışı format davranışı testlidir.
- T20: kayıt sırasında hedef değiştirme ve hedefin kapanması testleri; belirsiz teslim ikinci kez kendiliğinden yazılmaz.
- T21: terminal ve normal metin alanında gerçek paket testi; işletim sistemi girdi olayını kabul etmesi tek başına CONFIRMED üretmez.

### İP07 — Kısayol, gösterge ve paketli yardımcı süreçleri sağlamlaştır

**Öncelik:** Masaüstü güvenilirliği  
**Bağımlılık:** İP04; süreç yönetimi için İP05  
**İnceleme eşlemesi:** B04, B10, B15  
**Dosyalar:** katip/hotkey.py, katip/kde.py, katip/ui/overlay_controller.py, overlay_gtk.py; run_katip.py, katip/__main__.py, katip.spec

**Yapılacak işler:**

- IPC kullanılabilirliği ile global kısayol kaydını ayrı durumlar yap. evdev cihazlarını kapanışta kapat; kopan cihazı listeden çıkar ve geri çekilmeli yeniden keşifle yeni klavyeyi bul. Hata döngüsü CPU’yu meşgul etmesin.
- Wayland GlobalShortcuts portalını destek/izin tespitiyle tercih et; yoksa işletim sistemi kısayolu + mevcut IPC yolu devam etsin. Aynı kombinasyonu iki arka uç aynı anda dinlemesin.
- Paketli uygulamada sys.executable -m kullanma. Yardımcı mod, GUI ve tek örnek denetimi yüklenmeden önce açıkça ayrılan dahili giriş noktasına sahip olsun; normal Kâtip’i yeniden başlatmasın.
- GTK göstergesi için paket bağımlılığı, gi/Gtk yüklenebilirliği ve hazır sinyali zorunlu olsun. Başlangıç/çalışma hatasında Qt göstergesine dön; hata stderrini sınırlı ve maskeli sakla. Ses seviyesi desteği yoksa varmış gibi dalga animasyonu vaat etme.
- Qt/KWin kuralını ve mevcut odak koruma testlerini koru. CLI --version/--status gibi kısa işlemlerde GUI motorunu başlatmadan argüman ayrıştır; dahili helper argümanları kullanıcı eylemi gibi işlenmesin.
- Dış sistem komutları temiz ortam + timeout + maskeli hata sağlayan tek runnerdan çıksın. CLI çocuklarına paketli Qt/LD_LIBRARY_PATH ortamını istemeden miras bırakma.

**Bitmiş sayılma koşulları:**

- T22: klavye çıkar/tak, izin yok, portal yok/izin reddi, çift IPC start ve tekrar ayar kaydı testleri; en fazla bir kısayol olayı.
- T23: kaynak ve paketli modda gösterge helperı hazır olur veya Qt’ye döner; yeni ana uygulama/süreç zinciri oluşmaz.
- T24: paket --version, --status, başlat/ikinci örnek/ayar aç/kapat ve temiz alt süreç ortamı smoke testleri geçer.

### İP08 — Ayar göçü, anahtarlar ve teşhis politikasını tamamla

**Öncelik:** Bakım ve gizlilik  
**Bağımlılık:** İP02 + İP04  
**İnceleme eşlemesi:** B06, B13, B15  
**Dosyalar:** katip/config.py; yeni infrastructure/secrets.py, diagnostics.py; katip/ui/settings.py, katip/desktop.py

**Yapılacak işler:**

- Ayar şeması sürümü ve geri alınabilir göçler ekle. Atomik kayıt/rollback davranışı korunur; önceki dosya göçten önce güvenli yedeklenir. Geçerli kullanıcı modeli sessizce varsayılana çevrilmez; kullanılamayan model açıklanır.
- Model yetenekleri merkezde tutulur: STT/metin desteği, çıktı biçimi, bağlam/çıktı/yükleme sınırı ve son doğrulama bilgisi. API anahtarının bulunması erişim doğrulaması sayılmaz. Katalog kontrolü kayıt başlatmayı ağ isteğine bağımlı yapmaz.
- OS anahtar kasası adaptörü ekle; mevcut JSON anahtarını ancak güvenli yazma ve geri okuma doğrulandıktan sonra kaldır. Kasa erişilemiyorsa gizli düz metin dönüşü yapma; mevcut anahtar kaybolmasın ve kullanıcıya uygulanabilir bilgi ver.
- Varsayılan kayıt kurtarma bellekte kalsın. Diske otomatik ses kaydı bu sürüm kapsamı dışında ve ayrı açık seçim gerektirir. Loglar dönen boyut sınırlı dosyalar olsun; 5 × 1 MiB başlangıç sınırı, hassas alan maskeleme ve teşhis dışa aktarımında önizleme.
- Hata penceresinde aşama, kısa hata kodu, kayıt süresi ve yapılabilecek eylem görünsün. Mikrofon kesilmesi, STT timeout ve formatter hatası aynı genel hata mesajına dönüşmesin. Güncelleyicinin sürüm karşılaştırması ve worker testini gerçek metoda bağla.

**Bitmiş sayılma koşulları:**

- T25: v0.4.6 ayarları tek sefer göç eder; başarısız disk/kasa yazımı eski dosya/anahtarı korur. Geçerli özel model ve sözlük kaybolmaz.
- T26: anahtar/transkript içeren sahte hata nesneleri log/dışa aktarım çıktısında görünmez; log boyutu sınırlıdır.
- T27: uygulama normal kayıt sırasında ses/transkript dosyası üretmez. Hata mesajı doğru aşamayı gösterir; güncelleyici testi workerı gerçekten çağırır.

### İP09 — Her değişiklikte çalışan kalite ve yayın kapıları

**Öncelik:** Sürekli güvence  
**Bağımlılık:** Hızlı CI İP01 ile başlar; tam matris İP02–İP08 tamamlanınca kapanır  
**İnceleme eşlemesi:** B12, B14, B15  
**Dosyalar:** .github/workflows/ci.yml ve release.yml; pyproject.toml, bağımlılık kilidi, packaging/*; README ve test verileri

**Yapılacak işler:**

- İlk iş paketiyle birlikte push/PR için hızlı test ve lint kapısını aç. Kritik modüller taşındıkça tip denetimi ve dal kapsamı kapısını genişlet; bugün tüm depoya gerekçesiz %90 dayatma. Hedef çekirdek modüllerde dal kapsamı ≥%90 ve bütün kritik hata geçişleri için açık testtir.
- İlk referans ortam mevcut release Python 3.11 ve yerel Python 3.14; beyan edilen >=3.10 desteği ayrıca doğrulanır. PySide/PyAudio sistem ön koşulları ve minimum OS bilgileri README/paket tariflerinde açık olsun. Bağımlılıklar hedef platformlarda çözümlenip kilitlensin.
- Windows, iki macOS mimarisi ve Linux paketleri için temiz kurulum/başlangıç/IPC/kapanış smoke testleri ekle. Gerçek masaüstü hedefi önce kullanıcının doğrulanacak Linux oturumu; KDE Wayland kabul testleri test edilen ortam olarak kayıtlı olsun.
- İzinli Türkçe/İngilizce karışık ses örnekleri oluştur. STT kelime hatası ile formatter anlam korumasını ayrı ölç; isim/sayı/olumsuzluk/öz düzeltme ve uzun konuşma testleri bulunmalı. Canlı API testleri maliyet/istek sayısı sınırlandırılmış ayrı bir iş olsun.
- v0.4.6 → test paketi → aday sürüm sırasını kullan. Kurulu uygulama doğrudan değiştirilmesin; test paketi ayrı config/socket/kimlik alanı kullansın. Yalnız görsel adını değiştirmek yeterli izolasyon sayılmasın.
- Yayın öncesi paket bütünlüğü ve platform imzalama/noterleme durumunu doğrula. Bir hedef doğrulanmadıysa o hedef için genel çalışma garantisi verme; doğrulanmamış testleri yeşil kabul etme. Önceki paket ve ayar yedeğiyle geri dönüş prova edilsin.

**Bitmiş sayılma koşulları:**

- T28: mevcut 204 test ve yeni T01–T27 regresyonları kaynak ve uygun platform matrisinde geçer; atlanan senaryolar gerekçesiyle görünürdür.
- T29: referans cihazda 40/60 saniye ve 5/10 dakika kayıt, 100 kısa oturumluk sentetik dayanıklılık testi ve hata enjeksiyonu kaynak/süreç artışı bırakmaz.
- T30: kurulu paket, aday paket ve kaynak ortamı karışmaz; rollback ayarları okuyabilir. U01 ancak gerçek kök neden yakalanıp regresyon ve gerçek senaryo testleri geçince kapatılır.

## 7. İlk teslimat ve tüm planın bitiş koşulu

**İlk kullanıcı doğrulaması:** İP01–İP03 tamamlandığında Groq 40/60 saniyelik senaryo, sesin korunması, doğru aşama mesajı ve sağlayıcı regresyonları ayrı test paketinde doğrulanır. U01’in kök nedeni henüz yakalanmamışsa bu teslim “sağlamlaştırma adayı”dır; “hata çözüldü” etiketi taşımaz.

**Tamamlanma:** T01–T30 kabul testleri ve platform kabulü geçer; bilinen P1 bulguları kapanır. Açık/atlanmış testler gizlenmez. Başarısızlıkta ses ve başarılı aşamalar korunur; kullanıcı iptal edip tekrar kullanılabilir duruma döner. “Hiç hata olmaz” garantisi verilmez.

## 8. Geriye uyumluluk ve geri dönüş

- Mevcut config.json, sözlük, kısayol, mod, cihaz ve model seçimleri göç testleriyle korunur.
- Tek seferde hem bütün sağlayıcılar hem UI hem paketleme yeniden yazılmaz. Ortak tiplerin çevresinde geçici adaptörlerle ilerlenir.
- Test paketi ayrı config, log, IPC soketi/portu ve uygulama kimliği kullanır; mevcut kurulumun ayarlarını otomatik göç ettirmez.
- Aday sürüm kurulmadan mevcut paket ve ayarlar güvenli yedeklenir. Başarısızlıkta önceki sürüm ayarlarını okuyabildiği rollback senaryosu test edilir.
- Kurulu uygulamanın değiştirilmesi/yayınlama bu plan oluşturma işinin parçası değildir.

## 9. Riskler ve açık teknik bilgiler

### U01 henüz teşhis edilmedi

25 saniye benzerliğinden ağ timeoutunu kesin neden saymak yanlış olabilir. İlk iş paketi kapanmadan “düzeldi” denmeyecek.

### Ağ transportunun değişmesi

QtNetwork geçişi multipart, SSL, proxy ve hata eşleme regresyonu yaratabilir. Önce fake/local HTTP sözleşmeleri, sonra tek sağlayıcıyla geçiş; Requests geri dönüşü geçici geliştirme yolu olarak korunur, kullanıcıya iki farklı motor sunulmaz.

### Native ses sürücüsü

Thread taşıması C seviyesinde sürücü çökmesini izole etmez. Böyle bir çökme gözlenirse capture worker için ayrı süreç ve paketli helper protokolü ek planla ele alınır.

### İşletim sistemi sınırları

Wayland her ortamda hedef pencere kimliği/teslim teyidi vermeyebilir. Yetenek tespiti ve güvenli hazır-sonuç yolu korunur; desteklenmeyen teyit uydurulmaz.

### Gizlilik ve rollback

Yeni anahtar kasası/şema göçü başarısızsa eski anahtar ve ayar korunmalı. Ses disk saklaması gizlice etkinleşmemeli. Geri dönüş, yalnız kodu geri almakla bitmez; ayar uyumu test edilir.

### Süre ve maliyet belirsizliği

İş paketleri küçük PRlara bölünür; takvim taahhüdü teşhis öncesi verilmez. Canlı servis hızı/erişilebilirliği garanti edilemez; yerel veri koruma ve toparlanma doğrulanabilir.

## 10. Başvuru kaynakları

- [Groq STT — doğrudan dosya yükleme sınırları](https://console.groq.com/docs/speech-to-text)

- [Requests — timeout toplam iş süresi değildir](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts)

- [Qt — QNetworkReply.abort davranışı](https://doc.qt.io/qtforpython-6/PySide6/QtNetwork/QNetworkReply.html#PySide6.QtNetwork.QNetworkReply.abort)

- [Qt — QProcess yaşam döngüsü](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html)

## 11. İnceleme bulguları → iş paketi eşlemesi

| Bulgu | İş paketleri |
|---|---|
| U01 Uzun Groq diktesi | İP01, İP03, İP05, İP09 |
| B01 Prompt çağrısı | İP02 |
| B02 Yeniden düzenleme | İP02, İP04 |
| B03 VAD veri kaybı | İP03 |
| B04 Paketli gösterge | İP07 |
| B05 CLI çıktı doğrulama | İP02 |
| B06 Model önbelleği | İP02, İP08 |
| B07 GUI blokajı | İP03, İP04 |
| B08 Pano yarışı | İP06 |
| B09 Teslim hedefi | İP06 |
| B10 Klavye bağlantısı | İP07 |
| B11 İptal ve son süre | İP01, İP04, İP05 |
| B12 Sağlayıcı kalite kuralları | İP02, İP05, İP09 |
| B13 Saklama ve gizlilik | İP04, İP08 |
| B14 Test/CI boşluğu | İP01, İP09 |
| B15 Paket/bağımlılıklar | İP05, İP07, İP08, İP09 |
