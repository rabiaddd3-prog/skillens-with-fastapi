# ACP sunumu: demo adımları

## Sunumdan önce (5 dakika)

1. Proje klasöründe PowerShell aç ve siteyi **hafif modda** başlat:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\start_public_link.ps1 -Light
   ```

   - Birkaç saniyede açılır. Model yüklenmez; ilanlar daha önce kaydedilmiş model sonuçlarıyla gelir.
   - Ekranda yeşil **Public link** çıkar. Bu pencereyi sunum bitene kadar **kapatma**.
   - İnternet linki gerekmiyorsa sonuna `-LocalOnly` ekle.
2. Demo hesabını hazırla (her seferinde temiz başlar, şifre yenilenir):

   ```powershell
   .\.venv\Scripts\python.exe scripts\seed_demo_account.py
   ```

   E-posta ve şifre ekrana yazılır, ayrıca `runs\demo_account.txt` dosyasında durur.
3. Tarayıcıda iki sekme aç: `http://localhost:8000` ve `http://localhost:8000/docs`.

## Sunum sırasında

1. **`/docs`**: router başlıklarını göster (auth, users, jobs, …). Bir şemayı aç.
2. **Authorize**: demo e-posta ve şifresiyle giriş yap, sonra `GET /users/me` → *Try it out*.
3. **CRUD**: `POST /jobs` ile bir ilan oluştur (201), `PATCH` ile başlığını değiştir (200),
   `DELETE` ile sil (204). İstersen başka bir hesapla değiştirmeyi dene (403).
4. **Web sitesi**: sağ üstten *Giriş yap* → demo hesabı.
   - CV, quiz sonuçları ve kayıtlı ilanlar (★) hazır gelir.
   - *Örnek CV dene* düğmesi CV'yi tek tıkla tarar.
   - İlan önerileri, eşleşmeler, yol haritası (adım işaretle → sayfayı yenile → işaret duruyor).
5. **Veritabanı**: VS Code'da `data/jobs.db` → SQLite Viewer: `users`, `quiz_results`, `saved_jobs` tabloları.
6. **Admin**: `http://localhost:8000/admin` (anahtar `runs\admin_token.txt`): rota başına çağrı sayıları.

## Sık sorulabilecekler

- *Model nerede?* Hafif modda model yüklü değil; ilanların model sonuçları veritabanında saklı. Yeni metin
  okutmak için tam mod: komutu `-Light` olmadan çalıştır (açılış yaklaşık 1 dakika).
- *Şifreler nasıl saklanıyor?* Argon2 hash olarak; düz şifre hiçbir yerde tutulmaz.
- *Giriş nasıl çalışıyor?* `/auth/token` bir JWT verir, istemci onu `Authorization: Bearer` ile gönderir.
- *Başkası benim verimi görebilir mi?* Hayır; her sorgu giriş yapan kullanıcıya göre süzülür, testlerle kontrol edildi.
