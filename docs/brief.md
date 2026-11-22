# SkillLens — Claude proje brifi

Tek kişilik NLP mini projem **SkillLens: Deep Learning-Based Developer Skill Assessment and Job Matching System**. İngilizce yazılım ilanlarından teknik beceri ve bilgi gereksinimlerini çıkaran, bunları CV’de beyan edilen beceriler ve teknik quiz sonuçlarıyla karşılaştıran, ilanları sıralayan ve kişisel öğrenme yol haritası çıkaran bir prototip geliştireceğim. Dersin araştırma sorusu şu. **BiLSTM ile fine-tune edilmiş DistilBERT, aynı iş ilanı verisinde beceri ve bilgi ifadelerini ne kadar doğru ve ne kadar hızlı çıkarıyor?**

## 1. Ders gereksinimleri ve çalışma biçimi

- Final raporu için hocanın istediği **Springer LaTeX şablonunu** kullan. Tahtada Word’ün üzeri çizilmiş. **Sunum** da var. Raporda Abstract, Introduction, Contribution, Similar Studies, Methodology, Results ve Conclusion bölümlerini kapsa ve kaynakça ekle.
- Methodology’de sistemi girişten çıkışa adım adım açıkla. **Sistem mimarisi diyagramı ve pseudocode** yer alsın.
- Tahtada Turnitin ve “human work / NOT AI” vurgusu var. Dersin izin verdiği ölçüde öğretici destek ver. Kod inceleme, hata ayıklama, test senaryoları ve rapor iskeleti üzerinden ilerle. Teslim metnini ve deney yorumlarını kendi çalışmama dayanarak ben yazacağım. Ölçülmemiş metrik, yapılmamış deney, sahte kaynak veya öğrenci katkısı uydurma.
- Ayrıntılı proje önerisinde **BiLSTM, DistilBERT, CV, teknik sınav, otomatik ilan toplama, eşleştirme, skill gap, roadmap ve Streamlit** var. API isteğini karşılamak için önerilen mimari **FastAPI backend + Streamlit frontend**.
- Taslaklarda 8 ve 12 haftalık planlar var. Takvimi, kesin şablon sürümünü, varsa sayfa sınırı ve sunum süresini hocanın resmi yönergesinden doğrula. Aşağıdaki endpoint isimleri, soru sayısı ve uygulama ayrıntıları teknik öneri. Mevcut repo verilirse ilk iş dosyaları ve çalışan akışları incele.

## 2. Veri ve Deep Learning

### SkillSpan ve ön işleme

- İngilizce iş ilanları için SkillSpan kullan. Kaynak, sürüm, lisans, split’ler, örnek sayıları, etiketler ve kullanılan alt kümeyi kaydet.
- Veri şemasını ve BIO etiketlerini gerçek dosyada incele. Skill ve Knowledge ayrı etiket dizilerindeyse ikisini koru. Örtüşen span’ler varsa iki etiket başlığı veya belgelenmiş eşdeğer bir temsil kullan. İki modelin görevi ve değerlendirme temsili aynı olsun.
- Hazır train/validation/test ayrımlarını kullan. BiLSTM sözlüğünü train’den oluştur. Validation ile checkpoint seç, testte final ölçümü al. Token ve etiket uzunluklarını doğrula. Uzun ilanları parçalama, metin konumlarını koruma ve tekrar eden span’leri birleştirme davranışını tanımla.

### Model A — BiLSTM

PyTorch ile embedding → bidirectional LSTM → token classification katmanlarını kur. Padding maskesi, bilinmeyen token, sabit seed ve validation'a göre checkpoint seçimi olsun. Sözlük, etiket eşlemeleri, konfigürasyon ve ağırlıkları beraber kaydet.

### Model B — DistilBERT

DistilBERT’i SkillSpan üzerinde token classification için fine-tune et. Word/subword etiket hizalamasını yap. Padding ve özel token’ları loss dışında tut. Tahminleri kelime/span seviyesine dönüştür. Tokenizer, etiket eşlemeleri, konfigürasyon ve checkpoint’i beraber kaydet.

### Deney ve değerlendirme

- Aynı held-out test örneklerinde **entity-level Precision, Recall ve F1** ölç. Doğru sayılan span’in metin sınırı ve türü eşleşsin. Genel sonuç ve mümkünse Skill/Knowledge bazında kırılım göster.
- İki modeli aynı donanım, girdiler ve batch size ile karşılaştır. Warm-up sonrası en az medyan inference latency ölç. Ölçümün ön işlemeyi içerip içermediğini ve örnek sayısını yaz.
- Gerçek false positive, false negative ve hatalı span sınırı örnekleri çıkar. Modeli kullanıma alma kararını validation sonucu ve hız ihtiyacı üzerinden gerekçelendir.
- Eğitim, değerlendirme ve tek ilan inference komutları olsun. Seed, bağımlılık sürümleri, cihaz, koşum ayarları, metrik JSON/CSV, checkpoint’ler ve hata örneklerini kaydet. Önce küçük smoke test çalıştır, onu final deney sonucu olarak kullanma.

## 3. CV ve teknik değerlendirme

- Metin tabanlı PDF CV yükle, metni çıkar ve teknik becerileri tanı. İlk sürümde taranmış PDF için metin yapıştırma yeterli. Boş, bozuk ve boyutu aşan dosyalarda anlaşılır mesaj ver.
- CV için teknik beceri sözlüğü ve alias eşlemesi kullan. İlan modeli CV’ye uygulanırsa sonuçları kullanıcıya düzeltilebilir şekilde göster ve CV başarısı için ilan metriklerine dayanma. Kullanıcı becerileri ekleyebilsin, silebilsin ve onaylayabilsin. Orijinal CV ve iletişim bilgilerini kalıcı olarak saklama ihtiyacı varsayma.
- Önerilen quiz konuları Python, C#, SQL, OOP ve algoritma/veri yapıları. 60–80 açıklamalı çoktan seçmeli soru eski taslaktaki hedef. Kaydın id, konu, beceri, zorluk, seçenekler, doğru cevap ve açıklama alanları olsun.
- İlan gereksinimlerine göre soru seç. Doğru cevabı quiz teslim edilene kadar istemciye verme. Sonuçta konu bazında doğru sayısı, toplam, oran ve soru sayısı göster. CV beyanı ile quiz kanıtını ayrı tut. Test edilmemiş beceri “değerlendirilmedi” olarak görünsün.

## 4. İlan toplama, iş eşleştirme ve yol haritası

- Önce bir izinli ilan kaynağının desteklenen API’siyle otomatik içe aktarmayı kur. Öneride Greenhouse ve Lever örnek kaynak olarak geçiyor. İlan başlığı, şirket, açıklama, kaynak, kaynak id’si, URL ve içe aktarma zamanı tut. Aynı kaynak id’si tekrar gelirse mevcut kaydı güncelle. Ağ hatası ve boş sonuç için anlaşılır durum göster.
- Yapıştırılmış İngilizce ilan ve açıkça işaretli offline demo verisi de kabul et. Canlı entegrasyonun çalıştığını ancak gerçekten doğrulanırsa kaydet. Demo sonucu üzerinden canlı veri çalışıyor iddiası kurma.
- Çıkarılan her gereksinimde orijinal ifade, tür, mümkünse konum ve normalize beceri adı olsun. JS ve JavaScript’i birleştir, Java’yı ayrı tut. Belirsiz ifadeyi ve eşleşmeyenleri görünür bırak.
- İlan bazında CV’deki becerileri, quiz ile desteklenen becerileri, düşük quiz sonucunu, değerlendirilmemiş alanları ve profilde bulunamayan gereksinimleri göster.
- İlk puanlama önerisi. **CV kapsaması** = CV’de bulunan ilan becerileri / tüm ilan becerileri. **Quiz performansı** = ölçülen ilan konularının ortalama puanı. **Quiz kapsaması** = ölçülen ilan konuları / tüm ilan konuları. Sıralama için birleşik skor kullanılacaksa ağırlıkları ve eksik quiz verisi davranışını belgeleyip arayüzde göster. Çıkarılan beceri yoksa skoru “hesaplanamadı” döndür.
- Roadmap için elle tanımlı konu–önkoşul listesi kullan. İlgili eksikleri önceliklendir, önkoşulları bağımlı konudan önce ekle ve tekrarları kaldır. Her adımda konu, önerilme nedeni ve küçük bir öğrenme hedefi göster. Zorunlu/tercih ayrımı açıkça bulunmuyorsa varsayımı gerçek ilan bilgisi gibi sunma.
- Demo örneği. CV’de Python ve Git var. İlan Python, SQL ve Git istiyor. Quiz Python’da güçlü, SQL’de düşük, Git’te kanıt sunmuyor. Uygulama Git’i CV kanıtıyla gösterir ve yol haritasında SQL temellerini önerir.

## 5. FastAPI ve Streamlit

FastAPI veri doğrulama, inference, quiz puanlama ve eşleştirme kurallarını çalıştırır. Streamlit bu işlemleri HTTP üzerinden çağırır ve sonuçları gösterir. Modeli ve checkpoint yolunu ayardan al. Eksik checkpoint için anlaşılır hata ver. Yerel prototipte kalıcı ilan kataloğu gerekiyorsa SQLite kullan.

| Önerilen endpoint | İşlev |
|---|---|
| GET /health | API ve model hazır olma durumu |
| POST /cv/analyze | PDF’den aday becerileri çıkarma |
| POST /jobs/import | Kaynaktan veya girilen ilan metninden kayıt |
| GET /jobs | İlan kataloğu |
| POST /skills/extract | İngilizce metinden Skill/Knowledge span’leri |
| POST /quiz/start | Konu/ilan bazlı quiz |
| POST /quiz/submit | Konu bazında quiz kanıtı |
| POST /matches | Açıklamalı ilan sıralaması |
| POST /roadmap | Eksiklere ve önkoşullara göre yol haritası |

Ekran akışı **CV yükle ve onayla → ilan getir veya ekle → quiz çöz → eşleşmeleri incele → bir ilan seç ve yol haritasını gör**. Model sonuçları için bir karşılaştırma tablosu veya rapora aktarılabilir grafik ekle. Kodda model eğitimi, backend, frontend, örnek veri ve testler kolay bulunabilsin.

## 6. Rapor, diyagram, sunum ve teslim

| Rapor bölümü | Kendi çalışmama dayanarak cevaplayacağım soru |
|---|---|
| Abstract | Problem, veri, modeller, uygulama ve ölçülen temel sonuç ne? |
| Introduction | İş ilanı gereksinimlerini anlamak neden zor? Araştırma sorum ne? |
| Contribution | İki modeli aynı koşullarda kıyaslamak ve CV/quiz/roadmap entegrasyonu ne sağlıyor? |
| Similar Studies | SkillSpan, BiLSTM ve DistilBERT çalışmalarından nasıl yararlandım? |
| Methodology | Veriden modellere, ilan metninden kullanıcı sonuçlarına hangi adımlarla ulaştım? |
| Results | Precision/Recall/F1/latency sonuçları, hata örnekleri ve demo ne gösteriyor? |
| Conclusion | Araştırma sorusunun yanıtı, sınırlamalar ve sonraki araştırma ne? |
| References | Veri seti, model ve gerçekten kullandığım diğer kaynaklar hangileri? |

- **Diyagram:** Eğitim akışında SkillSpan → iki model → karşılaştırma → seçilen checkpoint. Uygulama akışında ilan + CV + quiz → beceriler ve kanıt → eşleşme ve eksikler → yol haritası. FastAPI ve Streamlit’in mimarideki yerini çiz.
- **Pseudocode:** İlan becerisi çıkarma, CV/quiz kanıtıyla eşleştirme ve yol haritasının girdi, temel karar ve çıktılarını yaz.
- **Sunum:** Problem ve amaç → veri/modeller → mimari → deney sonuçları → canlı demo → sonuç ve sınırlamalar. Dersin slayt süresi verilmişse ona göre kısalt.
- **Teslim paketi:** Çalışan repo, README ve kurulum komutları, bağımlılıklar, örnek veri, eğitim ve değerlendirme script’leri, iki checkpoint veya indirme talimatı, metrik tablosu ve hata örnekleri, Springer LaTeX kaynakları + derlenen PDF, sunum ve demo akışı.

## 7. Geliştirme sırası ve kabul kriteri

1. Mevcut dosyaları incele. Onaylı kapsamı, varsayımları, veri şemasını ve eğitim ortamını belirle.
2. SkillSpan hazırlığını kur. BiLSTM ve DistilBERT için küçük veriyle smoke test yap.
3. İki gerçek eğitimi tamamla. Validation ile checkpoint seç ve test karşılaştırmasını ölç.
4. FastAPI’ye gerçek checkpoint bağla. Örnek bir İngilizce ilanın span’lerini API üzerinden doğrula.
5. CV, quiz, ilan kaynağı, eşleştirme ve roadmap akışlarını tamamla. Streamlit’e bağla.
6. Boş ilan, yinelenen ilan, geçersiz PDF, eksik checkpoint ve değerlendirilmemiş quiz konusu senaryolarını dene. Temiz kurulumdan uçtan uca demo yap.
7. Gerçek deney kanıtlarıyla rapor, sunum ve demo materyallerini tamamla.

**İlk yanıtında** mevcut materyale göre kapsamı, varsayımları, modül sırasını, her modülün kabul kriterlerini ve ilk geliştirme adımını çıkar. Her aşamada komut, beklenen çıktı ve benim doğrulayacağım deneyi ver. Bir adım tamamlanamazsa sebebi ve ölçülebilen sonucu kaydet. Projenin tamamlanma ölçütü, gerçek checkpoint ile başlayıp CV ve quiz kanıtına dayalı açıklanabilir öğrenme planıyla biten çalışır demo ve iki modelin ölçülmüş karşılaştırmasıdır.
