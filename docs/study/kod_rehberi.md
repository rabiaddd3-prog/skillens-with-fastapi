# Kod çalışma rehberi (teslime dahil değil)

Bu dosya demoda koddan soru gelirse hazırlıklı olman için bir çalışma listesi. Rapora ya da
sunuma kopyalanacak metin değil. Her maddede önce dosyayı aç, kodu kendin oku, sonra soruyu
yüksek sesle, kendi cümlelerinle cevaplamayı dene. Takıldığın yeri birlikte açarız.

## 1. Veri ve etiketler

| Dosya / fonksiyon | Ne yapıyor | Kendine sor |
|---|---|---|
| `core/labels.py` `bio_to_spans` | B/I/O dizisini (başlangıç, bitiş) aralıklarına çevirir | `O I I` neden yine bir aralık sayılıyor? (seqeval ile aynı davranış) |
| `core/data.py` `Vocab.build` | Kelime sözlüğü yalnız train'den, en az 2 kez geçen kelimeler | Test kelimesi sözlükte yoksa ne olur? (`<unk>`) Neden test'ten sözlük kurmuyoruz? |
| `bilstm_collate` | Batch'i sağdan doldurur, `mask` gerçek kelimeleri işaretler, padding etiketi -100 | -100 neden? (`CrossEntropyLoss(ignore_index)`) |
| `align_labels` | DistilBERT'te yalnız kelimenin ilk alt-kelimesi etiketlenir | "PostgreSQL" 3 alt-kelimeye bölünürse kaç tanesi loss'a girer? |
| `word_chunks`, `merge_windows` | 512 alt-kelimeden uzun cümleler pencerelere bölünür, sonra birleştirilir | Hangi cümleler bu kadar uzun? (`docs/data_notes.md`: maks. 748 kelime) |

SkillSpan'de Skill ve Knowledge iki ayrı BIO dizisi. Aynı kelime ikisinde birden olabilir, bu
yüzden iki ayrı "kafa" (head) var. Bunu bir cümleyle açıklayabilmelisin.

## 2. Modeller

**BiLSTM (`core/bilstm.py`)**
- Akış: kelime gömmesi → 2 katmanlı çift yönlü LSTM → her head için bir doğrusal katman.
- `pack_padded_sequence`: geri yönlü LSTM'in padding'i okumaması için.
- Yeni seçenekler (varsayılan kapalı):
  - `char_dim > 0`: her kelimenin harfleri ayrı bir küçük BiLSTM'den geçer.
  - `use_crf`: her head için bir CRF katmanı.
- Soru: CRF softmax'tan neyle farklı? Cevap: etiket geçişlerini birlikte puanlar; örneğin `O → I` geçişi cezalanabilir.
- `CRF.nll`: ileri algoritma (forward algorithm), log-sum-exp ile.
- `CRF.decode`: Viterbi. Testi `tests/test_bilstm.py::test_crf_nll_matches_brute_force` içinde; tüm olası dizileri tek tek sayarak karşılaştırıyor. Bu testi okursan CRF'i anlamış olursun.

**DistilBERT (`core/distilbert.py`)**
- Hazır `distilbert-base-cased` kodlayıcısı ve üstünde iki doğrusal kafa. Loss iki kafanın toplamı.
- Soru: neden "cased"? Cevap: C#, SQL, iOS gibi büyük-küçük harfin anlam taşıdığı terimler.

## 3. Ölçüm

- `core/metrics.py` `entity_scores`: bir aralık ancak cümle, başlangıç, bitiş ve tür aynıysa doğru sayılır.
- `scripts/evaluate.py`: gecikme ölçümü batch 1 ile, 20 ısınma turundan sonra, ön işleme dahil. `cuda.synchronize` neden gerekli?
- `scripts/analyze_by_source.py`: TECH ve HOUSE ayrımı; sözlük taban modeli.
- `scripts/ablation_jobs.py`: model ile sözlüğün uygulamadaki beceri listesine katkısı.
- `scripts/sensitivity.py`: ağırlık 0,5/0,5 değişince sıralama ne kadar değişiyor. Profiller rastgele ve sentetik, bunu söyleyebilmelisin.

## 4. Uygulama

- `core/extractor.py` `SkillExtractor.mentions`:
  1. metni cümlelere ve kelimelere böler,
  2. modeli çalıştırır,
  3. aralıkları sözlükle adlandırır,
  4. adlandırılamayanları Sentence-BERT ile dener (`core/embed_normalize.py`, eşik 0,75),
  5. modelin kaçırdığı sözlük eşleşmelerini "dictionary" etiketiyle ekler.
- `core/cv.py`: CV için model kullanılmıyor, yalnız sözlük kullanılıyor. Neden? Model ilan metinleriyle eğitildi; kullanıcı da sonucu onaylıyor.
- `core/matching.py`: CV kapsaması, quiz performansı, birleşik puan. Formülü tahtaya yazabilmelisin.
- `core/roadmap.py`: önkoşul grafiği. Döngü kontrolü `_check_acyclic` içinde.
- `api/main.py`: uç noktalar, `X-Lang` başlığı, admin anahtarı (`secrets.compare_digest` neden?), zamanlanmış içe aktarma (`SKILLLENS_AUTO_IMPORT`).

## 5. Muhtemel hoca soruları (cevabı sen hazırla)

1. DistilBERT neden BiLSTM'den iyi? CRF eklenince fark ne kadar kapandı?
2. Skill F1 neden Knowledge F1'den düşük?
3. Modelin uygulamaya katkısı ne? Sözlük tek başına yetmez miydi? (ablation tablosu)
4. Sentence-BERT eşiğini nasıl seçtin? Yanlış eşleşme örneği var mı? (`results/embed_candidates.csv`)
5. 0,5/0,5 ağırlıkları nereden geldi?
6. Test setine ne zaman dokundun?
7. CV'deki kişisel veri nerede saklanıyor? (Hiçbir yerde; istek bitince atılıyor.)
8. Yapay zekâ araçlarını nerede, nasıl kullandın? (Dürüst beyan.)
