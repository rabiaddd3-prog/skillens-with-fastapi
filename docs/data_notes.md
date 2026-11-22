# SkillSpan veri notları

Kaynak: Hugging Face `jjzha/skillspan` (Zhang ve ark., 2022, NAACL).

Lisans (22.11.2026'da kontrol edildi):
- Hugging Face veri kartının meta verisinde `license: cc-by-4.0` yazıyor. Kartın düz metninde lisans cümlesi yok.
- Orijinal GitHub deposu (`kris927b/SkillSpan`) MIT etiketli. README'de veri için ayrı bir lisans yok, sadece makaleye atıf isteniyor.
- Makale, yalnızca lisansı izin veren bölümlerin (HOUSE ve TECH) yayınlandığını söylüyor. Veri beyanına göre TECH ilanları Stack Overflow Jobs'tan geliyor ve CC BY-SA lisanslı. TECH alt kümesi yeniden paylaşılırsa share-alike koşulu geçerli olabilir.
- Bu projede veri yeniden dağıtılmıyor. Eğitim sırasında Hugging Face'ten indiriliyor ve kaynak gösteriliyor.
Ölçüm scripti: `scripts/inspect_skillspan.py` (22.11.2026'da çalıştırıldı).

## Şema

`idx`, `tokens`, `tags_skill`, `tags_knowledge`, `source` (`tech` veya `house`).
Skill ve Knowledge **ayrı BIO dizileri** halinde geliyor. Etiketler yalnızca `B`, `I`, `O`. Tür bilgisi, dizinin hangi sütunda olduğundan geliyor.

## Split sayıları (cümle)

| Split | Cümle | tech | house | Skill B | Knowledge B | Maks. uzunluk | p99 uzunluk |
|---|---|---|---|---|---|---|---|
| train | 4800 | 3133 | 1667 | 2221 | 2969 | 748 | 123 |
| validation | 3174 | 2156 | 1018 | 1070 | 1093 | 80 | 45 |
| test | 3569 | 2286 | 1283 | 1090 | 1174 | 149 | 47 |

## Kontroller

- Token ve etiket uzunluk uyuşmazlığı: her üç split'te 0.
- Örtüşme (aynı token hem Skill hem Knowledge): train 347 token / 97 cümle, validation 106 / 25, test 34 / 12.
  Örtüşme var. Bu yüzden tek bir 5 sınıflı BIO dizisi bilgi kaybettirir.

## DistilBERT hizalama kontrolü (`scripts/check_bert_alignment.py`, distilbert-base-cased, max_length 512)

| Split | Maks. subword | Pencereye bölünen cümle | Subword'süz kelime (etiketli) | Geri dönüş hatası |
|---|---|---|---|---|
| train | 1046 | 8 | 96 (0) | 0 |
| validation | 195 | 0 | 8 (0) | 0 |
| test | 196 | 0 | 3 (0) | 0 |

Altın etiketler, tahminlerin izleyeceği yoldan geçirilince her split'te kelime etiketleri birebir geri geliyor.
Pencereye bölme yalnızca train'deki 8 cümlede gerekiyor. Validation ve test'te hiçbir cümle 512 sınırını aşmıyor, yani test sonucu parçalamadan etkilenmiyor.
Subword üretmeyen kelimelerin hiçbiri etiketli değil. Bunlar tahminde `O` sayılıyor.

## Karar (onaylandı, 22.11.2026)

Her iki model de **ortak encoder + iki ayrı BIO başlığı** (Skill, Knowledge) kullanacak. Loss iki başlığın toplamı olacak.
Değerlendirmede span'ler `(cümle, başlangıç, bitiş, tür)` olarak çıkarılacak ve entity-level P/R/F1 genel ile tür bazında hesaplanacak.

## Açık noktalar

- Train'de 748 tokenlık bir cümle var. DistilBERT için 512 subword sınırını aşan örnekler kayan pencereyle parçalanacak. Sayısı veri hazırlığında ölçülecek.
- Sürüm: Hugging Face önbelleğindeki revizyon `33062e6bd0e03a5e01ae299ce0518f4613ef4298`.
