# Resmî Gazete PDF Metin Toplayıcı

Bu projede, Resmî Gazete’de yayımlanan PDF dosyaları üzerinden metinleri otomatik olarak çekip `.txt` dosyaları halinde kaydeden bir Python betiği yazdım. PDF’lerde yer alan tablolar, haritalar ve anlamlı olmayan görsel içerikler filtreleniyor; sadece düz yazı formatındaki içerikler dosyalara ekleniyor.

---

## Proje Nasıl Çalışıyor?

1. Son 7 güne ait Resmî Gazete sayfalarını kontrol ediyor.
2. Her gün için bağlantıları listeliyor.
3. Her bağlantıdaki PDF içeriğini indirip:
   - Metin olarak ayrıştırıyor,
   - Tabloları ve haritaları ayıklıyor,
   - Gereksiz ilan bölümlerini geçiyor.
4. Her bir belgeyi `output/` klasörü altına `.txt` dosyası olarak kaydediyor.

---

## Kurulum

Bu projeyi çalıştırmak için bazı kütüphanelere ve araçlara ihtiyaç var:

### Gereken Python Kütüphaneleri

```bash
pip install -r requirements.txt
```
## Tesseract Kurulumu (OCR işlemleri için)

macOS:
```bash
brew install tesseract
```

Ubuntu / Debian:
```bash

sudo apt update
sudo apt install tesseract-ocr
```

## Kullanım

Projenin ana betiğini çalıştırmak için:

```bash
python main.py
```
## Ne yapar?

1. Son 7 güne ait Resmî Gazete sayfalarını kontrol eder.

2. Her gün için bağlantıları listeler.

3. Her bağlantıdaki PDF içeriğini indirip:

- Metin olarak ayrıştırır,

- Tabloları, haritaları, grafik ve koordinat içeren bölümleri ayıklar,

- Gereksiz ilan bölümlerini atlar.

4. Her belgeyi output/ klasörü altına .txt olarak kaydeder.

## Çıktılar

- Çıktı dosyaları output/ klasörüne otomatik olarak yazılır.

- Her dosya; tarih, sayı, kategori ve başlık bilgilerini içerir.

---
## Yaptıklarım 

1. Resmî Gazete'den Veri Çekme

- Belirli bir tarih aralığı (örn. son 7 gün) için Resmî Gazete sayfalarının bağlantıları otomatik olarak taranıyor.

- Günlük yayınlanan HTML ya da PDF bağlantıları ayıklanıyor.

2. PDF Metin Ayrıştırma

- PyMuPDF ve PDFMiner ile sayfa sayfa içerik okunuyor.

- Sayfa başlıkları, karar numaraları ve metinler çıkarılıyor.

- Eğer metin seçilemiyorsa, Tesseract OCR ile görselden yazı tanıma yapılıyor.

3. Gereksiz İçeriği Ayıklama

- Harita, tablo, kroki, koordinat listesi gibi kelimelerle başlayan ek sayfalar tespit edilip otomatik olarak kırpılıyor.

- Koordinat benzeri sayısal içerikler de filtreleniyor.

- İlan bölümleri dışarıda bırakılıyor.

4. Kayıt ve Formatlama

- Her belge bir .txt dosyası olarak output/ klasörüne kaydediliyor.

- İçerik: Başlık, kategori, karar no, tarih, URL bilgisi ve sadeleştirilmiş metni içeriyor.

---

PDF’lerdeki bazı metinler resim formatında olduğu için, ne kadar uğraşıp araştırsam da tam olarak doğru şekilde ayıklayamadım. Çoğu PDF içeriğinde harita ve tablo gibi görseller vardı. Bunları OCR ile çıkarmayı, ardından regex ile düzeltmeyi denedim. Bazı kısımlar düzelse de bazılarını kurtaramadım.