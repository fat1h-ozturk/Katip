# Groq metin dönüştürme akışı — implementasyon planı

Tarih: 30 Eylül 2026. Durum: Uygulandı; çevrimdışı entegrasyon kontrolleri tamamlandı.

Amaç: Mevcut Groq ses tanıma ve metin modelleriyle, transkriptin anlamını daha iyi koruyan, biçimi güvenilir ve geri alınabilir bir metin dönüştürme akışı oluşturmak.

## 1. Kapsam ve sabit kararlar

- Kullanıcının seçili Groq STT ve LLM model kimlikleri, sağlayıcısı ve dil tercihi değiştirilmeyecek. Varsayılan model değerleri de bu iş kapsamında değişmeyecek.
- Normal bir dikte en fazla bir STT ve bir formatter çağrısı kullanacak. Otomatik ikinci düzeltici LLM, alternatif model, otomatik yeniden deneme veya parçalara bölme eklenmeyecek.
- Kullanıcının başlattığı metni yeniden düzenleme işlemi yalnız formatter çağıracak; her seferinde özgün ham transkriptten başlayacak.
- Gemini'nin mevcut servis dönüşü, promptu ve çıktı temizleyicisi korunacak. Groq'a özel metin promptu ve JSON ayrıştırması ayrı giriş noktaları olacak.
- Mevcut commit edilmemiş çalışmalar korunacak. Commit, push, yayın, ücretli API çağrısı veya kullanıcıdan ses kaydı/test seti isteme bu planın parçası değil.
- Yeni bir framework, servis, veritabanı veya varsayılan kalıcı transkript geçmişi eklenmeyecek. Standart kütüphane ve mevcut bağımlılıklar kullanılacak.

Hedef akış:

`Mevcut Groq STT → ham metin + segment bilgisi → bağlam hazırlığı → mevcut LLM ile tek dönüşüm → JSON/tamamlanma doğrulaması → sonuç kaydı → yapıştırma`

Hata akışı: `formatter hatası → ham metni koru + mevcut uyarı yolu → otomatik yapıştırma yok`.

## 2. İş paketleri ve bağımlılıklar

| Sıra | İş paketi | Başlıca dosyalar | Bağımlılık |
| --- | --- | --- | --- |
| 1 | Groq formatter promptu ve mod sözleşmeleri | `katip/prompts.py`, `tests/test_prompts.py` | Yok |
| 2 | Sözlük ve telaffuz/yazım ipuçları | `katip/config.py`, `katip/ui/settings.py`, `katip/prompts.py`, ilgili testler | 1'deki bağlam sözleşmesi |
| 3 | STT bilgisi, JSON çıktı, uzunluk bütçesi ve ayrık formatter metodu | `katip/services/groq.py`, `tests/test_service_responses.py`, `tests/test_accuracy.py` | 1 ve 2 |
| 4 | Ham/düzenlenmiş sonuç, yeniden düzenleme ve yerel inceleme bilgisi | `katip/app.py`, `tests/test_app_recovery.py`, gerekirse yeni odaklı sonuç ekranı testi | 3'teki sonuç sözleşmesi |
| 5 | Entegrasyon, kullanım açıklamaları ve tamamlanma kontrolü | `README.md`, ilgili testler | 1–4 |

Servis ve uygulama arasındaki sonuç sözleşmesi işe başlarken netleştirilecek. Prompt ile ayar arayüzü işleri bu sınır üzerinden ayrılabilir; aynı dosyada eşzamanlı değişiklik yapılmayacak. Entegrasyon ve son inceleme tek sorumluda olacak.

## 3. İş paketi 1 — prompt ve modlar

`build_groq_formatter_prompt(...)` gibi Groq'a özel bir giriş noktası eklenecek. Gemini'nin kullandığı mevcut `build_system_prompt(...)` ve temizleyici sözleşmesi değiştirilmeden kalacak.

Prompt üç parçadan oluşacak: ortak anlam koruma kuralları, yalnız seçilen modun kuralları ve az sayıda ilgili giriş/çıkış örneği. Bütün modların örnekleri her isteğe eklenmeyecek.

Ortak kurallar:

- Modelin girdisi metindir; sesi dinlediğini veya yanlış duyulan kelimeyi kesin bildiğini varsaymayacak.
- Akıcılıktan önce anlamı koruyacak. Belirsiz kelimeyi veya eksik cümleyi tahminle tamamlamayacak.
- İsim, miktar, tarih, olumsuzluk, koşul, ihtimal ve taahhüt derecesini değiştirmeyecek. Sayıların gösterimi yalnız değeri açıkken düzenlenebilecek.
- Dolgu sözcüklerini bağlama göre ele alacak; anlamlı “şey/yani/falan” ve vurgu tekrarlarını koruyacak.
- Açık öz düzeltmede düzeltilen bilgiyi kullanacak; sıradan karşılaştırmaları ve olumsuz ifadeleri öz düzeltme sanmayacak.
- Transkriptteki soru ve emirler düzenlenecek veri sayılacak. Prompt modunda da görev uygulanmayacak, yalnız istem yazılacak.
- Dil ve Türkçe/İngilizce karışık teknik terimler korunacak; kendiliğinden çeviri yapılmayacak.
- Metin girdisinden “aslında sessizlik vardı” sonucu çıkarılmayacak. Akustik belirsizlik ayrı bilgi olarak ele alınacak.

| Mod | İzin verilen dönüşüm | Sınır |
| --- | --- | --- |
| Dikte | Yazım, noktalama, açık aksaklık ve öz düzeltme | Özetleme ve serbest yeniden anlatma yok |
| Chat | Akıcılık ve samimi üslup | Bilgi, kişi, zaman ve belirsizlik korunur |
| E-posta | Kurumsal üslup ve paragraflar | Uydurma alıcı, imza, gerekçe veya vaat yok |
| Prompt | Söylenen görev ve gereksinimleri yapılandırma | Yeni özellik, araç veya başarı koşulu uydurulmaz |
| Maddeler | Özetleme ve gruplama | Karar, istisna, aksiyon, sorumlu ve kritik değerler korunur |

Örnek sözleşmeleri: “Bir şey söyleyeceğim” ve “çok çok önemli” korunur; “salı, pardon çarşamba” düzeltilir; “gelebilirim” kesin taahhüde çevrilmez; dikte edilen “yalnız tamam yaz” uygulanmaz. E-posta, prompt ve maddeler için de birer sınır örneği bulunacak.

Ham metin, sözlük ve eşleşmeler sistem talimatına doğrudan eklenmek yerine `json.dumps(..., ensure_ascii=False)` ile oluşturulan kullanıcı veri mesajında taşınacak. Veri alanlarını ayırmak ve açık talimat vermek kesin prompt-injection koruması olarak sunulmayacak.

Kabul: Doğru modun kuralları ve örnekleri oluşturulur; kullanıcı metni ve sözlük talimat katmanına yükseltilmez; Gemini'nin prompt sözleşmesi değişmez. Örneklerin prompta yerleşmesi, gerçek modelin her zaman bu örneklere uyduğunun kanıtı sayılmaz.

## 4. İş paketi 2 — özel sözlük ve eşleşmeler

- `custom_vocabulary: list[str]` biçimi aynen korunacak.
- Boş varsayılanlı `vocabulary_aliases` alanı eklenecek: duyulan/yazılan varyant → tercih edilen yazım. Eski ayarlar dönüşüm istemeden açılacak.
- Ayarlara küçük, isteğe bağlı çok satırlı alan eklenecek; satır biçimi `paysayd altı => PySide6` olacak. Ayrı bir sözlük yönetim ekranı yapılmayacak.
- Boş taraflar, kontrol karakterleri, biçimsiz satırlar ve aynı varyantın farklı hedeflere atanması kaydetmeden önce açıklanacak. NFC normalizasyonu ve kenar boşluğu temizliği uygulanacak; Türkçe harfler ve büyük/küçük harfler korunacak.
- Yeni eşleşmeler en fazla 100 kayıt ve taraf başına 200 karakterle sınırlanacak. Tekrarlanan aynı eşleşme birleştirilecek. Eski özel kelime listesi sessizce budanmayacak.
- Eşleşmeler LLM'ye bağlama bağlı yazım ipucu olacak. Ham metne global arama/değiştirme uygulanmayacak; Türkçe eklerin korunması promptta belirtilecek.
- Whisper bağlamına doğru yazımlar öncelikli verilecek. Genel “Merhaba, bu bir dikte” metni yerine ilgili terimler kullanılacak. Eşleşmelerin uzun açıklamaları STT promptuna taşınmayacak.
- STT promptunun tamamı için, ek tokenizer bağımlılığı gerektirmeyen muhafazakâr 224 UTF-8 byte uygulama sınırı kullanılacak. Bu değer gerçek token sayısı diye raporlanmayacak. Tam terimler kullanıcı sırasıyla eklenecek; sözcük ortasından kesilmeyecek. Sığmayan terimlerin sayısı ayarlarda/sonuç ayrıntısında bildirilecek; kayıtlı sözlük korunacak.
- LLM sözlük bağlamı da toplam istek bütçesine dahil edilecek. Sığmama durumunda ham transkript kesilmeyecek; önce sözlük ipuçları azaltılacak ve bu durum kaydedilecek.

Kabul: Eski ayar dosyası aynı model ve kelimelerle açılır; eşleşmeler kaydet/aç döngüsünde korunur; çakışmalar sessizce üzerine yazılmaz; STT bağlamı sınırı terimler bölünmeden uygulanır.

## 5. İş paketi 3 — servis sözleşmesi ve doğrulama

### STT yanıtı

- Ses modeli ve dil davranışı korunarak `response_format="verbose_json"` kullanılacak.
- `text` ana kaynak olacak. Geçerli segmentlerde başlangıç/bitiş, metin, `avg_logprob`, `no_speech_prob` ve `compression_ratio` tutulabilecek.
- Eksik, null, biçimsiz veya sonlu olmayan segment alanları atlanacak; geçerli ana transkript bunlar yüzünden reddedilmeyecek.
- Segment değerleri kelime güven puanı veya “% doğruluk” olarak sunulmayacak. Kalibre edilmemiş eşiklerle konuşma silinmeyecek, otomatik yapıştırma engellenmeyecek veya ek API çağrısı başlatılmayacak.
- Segment metaverisi ilk sürümde isteğe bağlı sonuç ayrıntısında kullanılacak. Desteklenmeyen bir “düşük güven” sınıflandırmasını formatter'a gerçek bilgi gibi vermeyeceğiz.

### Formatter ve JSON

- Formatter, `format_transcript(...)` gibi ayrı çağrılabilir bir metoda çıkarılacak; ilk dikte ve yeniden düzenleme aynı metodu kullanacak.
- Tam model kimliğine göre küçük bir yetenek tablosu kullanılacak: mevcut Qwen için strict JSON Schema, mevcut Llama için JSON Object Mode ve yerel şema kontrolü. Bilinmeyen model için destek uydurulmayacak, model kendiliğinden değiştirilmeyecek.
- Çıktı sözleşmesi yalnız `{"text": "..."}` olacak. Strict şemada `text` zorunlu, ek alanlar kapalı olacak.
- Her iki yolda tamamlanma nedeni `stop`, geçerli JSON nesnesi, tek `text` alanı, metin türü ve boş olmama kontrol edilecek. Yinelenen JSON anahtarları da reddedilecek. ASVS 2.2.1: servis sınırında beklenen yapıyı doğrula.
- `text` alanı eski regex temizleyiciye verilmeyecek; meşru “İşte:”, tırnak, kod çiti veya `<think>` içeriği korunacak. Model reasoning seçenekleri yalnız desteklenen model için gönderilecek.
- Boş, kesilmiş, şema dışı, bağlantı hatalı veya reddedilmiş yanıtta mevcut ham-metin kurtarma davranışı korunacak. Otomatik ikinci istek ya da sessiz düz metin fallback'i olmayacak.
- `temperature=0.1` ve mevcut reasoning tercihi korunacak; bu işte model/örnekleme ayarı değişikliğiyle prompt etkisi karıştırılmayacak.

### Uzun metin bütçesi

- Sabit 2048 yerine girdi uzunluğu ve moda bağlı, 2048–8192 arasında sınırlı çıktı bütçesi hesaplanacak.
- Başlangıç hesabı: ham metnin UTF-8 byte uzunluğu; e-posta/prompt için 1,25, diğer modlar için 1 çarpanı; JSON payı için 128 eklenip aralığa sıkıştırılacak. Bu muhafazakâr tahmindir, gerçek token sayımı değildir.
- Sistem promptu, veri mesajı ve çıktı bütçesi birlikte modelin doğrulanmış bağlam sınırına karşı kontrol edilecek; tahmini sınır aşılırsa metin kesilmeden ham sonuç korunacak.
- Formatter yanıt bekleme sınırı çıktı bütçesine bağlı olarak mevcut 25 saniyeden en fazla 60 saniyeye genişleyebilecek. STT'nin mevcut süresi korunacak. Otomatik parçalama veya sınırsız bekleme olmayacak.
- `finish_reason="length"` hiçbir zaman başarılı dönüşüm sayılmayacak. Süre ölçümünde monotonik saat kullanılacak.

### Sonuç aktarımı

- Groq içinde küçük bir sonuç kaydı kullanılacak: ham transkript, varsa doğrulanmış düzenlenmiş metin, süre, uyarı, isteğe bağlı segment bilgisi ve kullanılan dönüşüm bağlamı.
- Groq'un çağrıcıları ve testleri bu sözleşmeye birlikte geçirilecek. Gemini'nin mevcut tuple dönüşü korunacak; uygulamanın sağlayıcı dalında açıkça ele alınacak. Yeni genel sağlayıcı arayüzü kurulmayacak.
- Ağ hataları anahtar, ses, transkript veya sağlayıcının ham hata gövdesini loglamayacak; mevcut güvenli mesajlar korunacak.

Kabul: Normal başarı tam iki çağrı kullanır; geçersiz formatter çıktısı ham metni yok etmez; eksik metaveri başarıyı bozmaz; uzun girdi bütçeyi artırır ama üst sınırı geçmez; JSON içindeki kullanıcı içeriği değişmeden teslim edilir.

## 6. İş paketi 4 — sonuç ekranı, yeniden düzenleme ve inceleme

- Son Sonuç ekranında ham ve düzenlenmiş metin ayrı erişilebilir olacak. Formatter başarısızsa ham metin kullanılabilir, düzenlenmiş çıktı alanı başarılıymış gibi doldurulmaz.
- Sonuç yalnız bellekte tutulacak. Varsayılan disk geçmişi veya ham metin günlüğü eklenmeyecek. Sonraki kayıt, açık temizleme ve uygulama kapanışı için yaşam döngüsü tanımlanacak. ASVS 14.2.4 ve 14.2.7: özel verinin saklama/loglama sınırını uygula.
- Yeni kayıt başladıktan sonraki STT başarısızlığı eski kaydın metnini yeni sesin sonucu gibi göstermeyecek. Yeni STT başarılı ama formatter başarısızsa yeni ham metin mutlaka erişilebilir olacak.
- “Metni Yeniden Düzenle” varsayılan olarak kaydın mod ve sözlük kopyasını kullanacak. “Güncel mod ve sözlüğü kullan” seçimi açıkça sunulacak; model değiştirme bu işlemden yapılmayacak. Dil korunacak, çeviri yapılmayacak.
- Her yeniden düzenleme özgün ham transkriptten başlayacak. Başarıda aday sonuç tek seferde son kaydın yerini alacak; başarısızlıkta önceki ham/düzenlenmiş ikilisi korunacak.
- Yeniden düzenleme bir LLM, sıfır STT ve sıfır otomatik yapıştırma çağrısı yapacak. Kullanıcı sonucu mevcut kopyalama yoluyla alabilecek.
- Mevcut “Yeniden İşle” ses kurtarma eylemi, “Sesi Yeniden İşle” olarak ayrıştırılacak. Ses yokken de metin yeniden düzenleme çalışacak.
- İşleme/meşguliyet kilidi ve Qt sinyalleri yeniden kullanılacak. Yeniden düzenleme sırasında ikinci iş, yeni kayıt veya ayar değişikliği başlatılmayacak; GUI bileşenleri worker içinden güncellenmeyecek.
- Yapısal başarısızlıklarda mevcut otomatik yapıştırmama kuralı korunacak.
- Yerel karşılaştırma, açık URL, e-posta, kod bloğu ve belirgin kimliklerdeki farkları sonuç ayrıntısında gösterecek. Bunlar otomatik “anlam hatası” kararı, literal maskeleme veya otomatik düzeltme üretmeyecek. Özel formatı belirsiz her sayıyı/kelimeyi kimlik sayan geniş regex yazılmayacak.
- “A değil B”, meşru özetleme, yazıyla/rakamla gösterim ve anlamlı tekrarlar nedeniyle bu farklar tek başına sonucu engellemeyecek. Negasyon ve genel anlam doğruluğu için sahte bir güven yüzdesi üretilmeyecek.
- Metaveri ve literal farkları normal kullanıcı akışına teknik ayrıntı yüklemek yerine isteğe bağlı ayrıntıda kalacak.

Kabul: Kullanıcı özgün metni kaybetmez; yeniden düzenleme sesi göndermez ve önceki düzenlenmiş metni tekrar girdi yapmaz; başarısız yeniden düzenleme son başarılı sonucu bozmaz; inceleme sinyalleri meşru öz düzeltmeyi bloke etmez.

## 7. İş paketi 5 — doğrulama ve bitiş koşulu

Kullanıcıdan model karşılaştırması veya ses kaydı istenmeyecek. Doğrulama geliştirici tarafından, sahte API yanıtları ve mevcut cihaz/ağ izolasyonu ile yapılacak.

1. Prompt üretimi: mod seçimi, veri/talimat ayrımı, Türkçe örnekler, alias bağlamı, Gemini gerilemesi.
2. Servis sözleşmesi: strict ve JSON Object istekleri; bozuk/boş/ek alanlı/yinelenen anahtarlı/kesilmiş yanıtlar; meşru tırnak, kod ve etiketlerin korunması.
3. Sözlük/uzunluk: eski config, çakışan alias, Unicode, tam terimle bütçe sınırlama, dinamik çıktı alt/üst sınırları, kesilmede ham metin.
4. Durum yönetimi: ilk dönüşüm hatası, yeniden düzenleme hatası, ses olmadan yeniden düzenleme, yeni kaydın eski metinle karışmaması, meşguliyet ve otomatik yapıştırma sınırı.
5. Metaveri/inceleme: eksik alanlara tolerans, sonlu sayı kontrolü, öz düzeltme ve özetleme farklarının otomatik blok oluşturmaması.

İlgili testler değişiklikler toplandıktan sonra çalıştırılacak; ardından mevcut test paketi entegrasyon için bir kez çalıştırılacak. Önceki incelemede mevcut Python ortamında `requests` bulunmadı: uygulama aşamasında uygun izole geliştirme ortamı ve mevcut `requirements-dev.txt` kurulumu doğrulanacak. Bu, kullanıcıya test yaptırma veya ürüne yeni bağımlılık ekleme işi değildir.

Qt ekranı offscreen çalıştırılarak ham/düzenlenmiş alanlar ve düğmeler kontrol edilecek; gerçek mikrofon/pano/ücretli API kullanılmayacak. Windows paketleme bağımlılıkları veya import yolları etkilenirse mevcut paketleme duman kontrolü tekrarlanacak; tüm platformlarda canlı doğrulama yapıldığı iddia edilmeyecek.

README, yeni sözlük alanını, ham metne erişimi, metin/ses yeniden işleme farkını ve kalıcı geçmiş bulunmadığını açıklayacak.

Bitmiş sayılma koşulları:

- [x] Model kimlikleri ve Groq altyapısı korunuyor.
- [x] Beş modun dönüşüm sınırları promptta uygulanmış ve kısa örneklerle belgelenmiş.
- [x] Eski sözlük ayarları korunuyor; alias ve bağlam bütçesi çalışıyor.
- [x] JSON ayrıştırması kullanıcı içeriğini regex ile silmiyor.
- [x] Uzun metin sessizce kesilmiyor; hatada ham metin erişilebilir.
- [x] Ham/düzenlenmiş sonuç ve yalnız metin yeniden düzenleme sahte API yanıtlarıyla doğrulandı.
- [x] Metaveri ve fark incelemesi anlam doğruluğu garantisi diye sunulmuyor.
- [x] İlgili kontroller ve birleştirilmiş test paketi geçiyor; çalıştırılamayan kontrol açıkça bildiriliyor.
- [x] Mevcut kullanıcı değişiklikleri korunuyor; commit ve ücretli çağrı yapılmamış.

Bu kontroller kodun sözleşmesini ve hata davranışını kanıtlar. Gerçek Türkçe model kalitesinde ölçülmemiş bir yüzde artışı veya kusursuz anlam koruma iddiası üretilmeyecek.

## 8. Kararların dayanakları

- [Groq prompt rehberi](https://console.groq.com/docs/prompting): açık görev, veri, bağlam ve kısa örnekler.
- [Groq STT dokümanı](https://console.groq.com/docs/speech-to-text): verbose JSON segment alanları ve 224 token bağlam sınırı.
- [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs): Qwen strict şema desteği ve JSON Object ayrımı.
- [Qwen model dokümanı](https://console.groq.com/docs/model/qwen/qwen3.8-27b): mevcut modelin bağlam/çıktı ve reasoning sınırları.
- [Llama model dokümanı](https://console.groq.com/docs/model/llama-3.3-70b-versatile): JSON Object Mode desteği.
- [ASR Error Correction using Large Language Models](https://arxiv.org/html/2409.09554v1): serbest LLM düzeltmesinin her veri kümesinde iyileştirme sağlamaması; ek model çağrısının varsayılan çözüm yapılmaması.

Kaynaklar ve değişken Groq API yetenekleri 30 Eylül 2026'da uygulama sırasında resmi dokümanlardan yeniden kontrol edildi; ücretli istek yapılmadı.

## 9. Uygulama doğrulaması — 30 Eylül 2026

- Mevcut izole geliştirme ortamında `python -m pytest -q -rs`: **153 passed, 1 skipped**. Atlanan kontrol Linux'a özgü `evdev` testi; çalışma ortamı Windows.
- Qt sonuç diyaloğu offscreen modda açıldı: iki metnin ayrı erişimi, kopyalama hedefi ve modal pencere kapandıktan sonra yeniden düzenleme başlatılması doğrulandı. Üst üste modal açılış ve aktif iş sırasında kaydı temizleme/kaydetme sınırları test edildi.
- Sonuç ekranı ve yeni sözlük alanı offscreen olarak görüntülendi. Bu, gerçek masaüstü/cihaz testi değildir.
- Yeni bağımlılık eklenmedi. README kullanım ve saklama davranışını açıklıyor.
- PyInstaller, temiz PATH ve mevcut `katip.spec` ile geçici doğrulama dizininde Windows EXE oluşturdu; gizli pencerede `--version` kontrolü çıkış kodu **0** verdi. macOS/Linux paketleri bu ortamda çalıştırılmadı.
- Canlı API, mikrofon ve gerçek pano kullanılmadı. Türkçe model kalitesindeki artış ölçülmedi; testler veri koruma, çağrı sayısı, istek/yanıt sözleşmesi ve durum yönetimini doğrular.

### Kullanım sonrası düzeltme

Kullanıcının bildirdiği ilk düzenleme hatası ve ardından kısayolun sessiz kalması araştırıldı. Groq'un salt okunur model listesinde seçili `llama-3.3-70b-versatile` bulunmazken `whisper-large-v3` ve `qwen/qwen3.8-27b` erişilebilir göründü. Eski günlükte formatter HTTP 404 kaydı vardı. Hata sonrası `pending_audio` koruması yeni kaydı reddediyor, yalnız tepsi bildirimi gösteriyordu.

- Formatter HTTP hataları özel içerik sızdırmadan durum kodu ve yönlendirme gösteriyor.
- Korunan kayıt varken kısayol kurtarma penceresini açıyor; temizleme sonrası kayıt yeniden başlıyor.
- Kullanıcının açık onayıyla yerel ayarlarda yalnız metin modeli Qwen'e geçirildi. Ses modeli `whisper-large-v3`, kısayol `Ctrl+Alt` ve basılı tutma davranışı korundu. Uygulama otomatik model değiştirmiyor.
- Yeniden doğrulama: **159 passed, 1 skipped** (Linux evdev). Model listesi dışında canlı çıkarım/STT isteği, mikrofon veya pano testi yapılmadı.
- Düzeltilmiş Windows paketi `dist/Katip.exe` olarak derlendi; `--version` çıkış kodu 0. Mevcut Başlat menüsü kısayolu yedeklenerek eski İndirilenler EXE'sinden bu pakete yönlendirildi. Açık eski uygulama, bellekteki kaydı kaybetmemek için zorla kapatılmadı.
