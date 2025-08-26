import os
import re
import time
import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import urljoin
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from dateutil import tz
from models import ResmiGazeteKaydi


from pdfminer.high_level import extract_text as pdf_extract_text, extract_pages
from pdfminer.layout import LAParams, LTTextContainer

try:
    import fitz

    PYMUPDF_OK = True
except Exception:
    fitz = None
    PYMUPDF_OK = False

try:
    import pytesseract

    if os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")
    TESSERACT_OK = True
except Exception:
    pytesseract = None
    TESSERACT_OK = False

try:
    from PIL import Image, ImageOps, ImageFilter

    PIL_OK = True
except Exception:
    Image = ImageOps = ImageFilter = None
    PIL_OK = False

BASE = "https://www.resmigazete.gov.tr/"
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; resmigazete-scraper/1.1)",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.6,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

OUT_DIR = "output"
os.makedirs(OUT_DIR, exist_ok=True)


def ddmmyyyy(d): return d.strftime("%d.%m.%Y")


def yyyymmdd(d): return d.strftime("%Y%m%d")


def y(d): return d.strftime("%Y")


def m(d): return d.strftime("%m")


def get_soup(url, referer=BASE):
    try:
        r = SESSION.get(url, timeout=30, allow_redirects=True, headers={"Referer": referer})
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.content, "lxml")
    except requests.RequestException:
        return None


def boot_session():
    try:
        SESSION.get(BASE, timeout=20)
    except requests.RequestException:
        pass


def build_candidates(d):
    return [
        urljoin(BASE, ddmmyyyy(d)),
        urljoin(BASE, f"eskiler/{y(d)}/{m(d)}/{yyyymmdd(d)}.htm"),
        urljoin(BASE, f"eskiler/{y(d)}/{m(d)}/{yyyymmdd(d)}.pdf"),
    ]


def is_ilan_header(txt):
    return "İLAN BÖLÜMÜ" in txt.upper()


def clean_text(soup):
    for t in soup(["script", "style", "noscript"]): t.decompose()
    txt = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", txt)


def find_issue_number(page):
    full = page.get_text(" ", strip=True)
    m = re.search(r"ve\s+(\d{4,6})\s+Sayılı\s+Resmî\s+Gazete", full, flags=re.I)
    return m.group(1) if m else None


def extract_title(soup):
    for sel in ["h1", "h2", "h3", "strong", "b", "title"]:
        el = soup.find(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return clean_text(soup).splitlines()[0][:200]


def extract_no(text):
    pats = [
        r"Karar\s*Say[ıi]s[ıi]\s*:?\s*([0-9/\-]+)",
        r"Karar\s*No\s*:?\s*([0-9/\-]+)",
        r"Karar\s*:?\s*([0-9][0-9/\-]+)",
        r"Kanun\s*No\s*:?\s*([0-9/\-]+)",
    ]
    for p in pats:
        m = re.search(p, text or "", flags=re.I)
        if m:
            return m.group(1)
    return ""


def find_issue_and_date(page_soup: BeautifulSoup):
    s = page_soup.find(id="spanGazeteTarih")
    if not s: return None, None
    text = s.get_text(" ", strip=True)
    m_no = re.search(r"ve\s+(\d{4,6})\s+Sayılı\s+Resmî\s+Gazete", text, flags=re.I)
    issue = m_no.group(1) if m_no else None
    aylar = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
             "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}
    m_dt = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{4})", text)
    date_str = None
    if m_dt:
        gun, ay_str, yil = int(m_dt.group(1)), m_dt.group(2).lower(), int(m_dt.group(3))
        ay = aylar.get(ay_str)
        if ay: date_str = f"{gun:02d}.{ay:02d}.{yil}"
    return date_str, issue


def collect_from_daily_page(day_url: str, soup: BeautifulSoup):
    date_from_header, issue = find_issue_and_date(soup)
    issue = issue or "NA"
    root = soup.find(id="html-content") or soup
    items, current_category, in_ilan = [], None, False
    for el in root.children:
        if not getattr(el, "name", None): continue
        cls = el.get("class", [])
        if "html-title" in cls:
            txt = el.get_text(" ", strip=True)
            if txt and ("İLÂN BÖLÜMÜ" in txt.upper() or "İLAN BÖLÜMÜ" in txt.upper()): in_ilan = True
            continue
        if "html-subtitle" in cls:
            current_category = el.get_text(" ", strip=True) or None
            continue
        if in_ilan: continue
        if "fihrist-item" in cls:
            a = el.find("a", href=True)
            if not a: continue
            href, text = urljoin(day_url, a["href"]), a.get_text(" ", strip=True)
            if not text or re.search(r"(Önceki|Sonraki|PDF Görün|Uygulaması)", text, flags=re.I): continue
            cat = current_category
            if not cat:
                prev_cat = el.find_previous(class_="html-subtitle")
                if prev_cat: cat = prev_cat.get_text(" ", strip=True)
            items.append({"category": cat or "GENEL", "url": href, "title_from_list": text, "issue": issue,
                          "date_from_header": date_from_header})
    dedup, seen = [], set()
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            dedup.append(it)
    return dedup, issue


def collect_for_date(d):
    last_issue, last_page_url = "NA", None
    for u in build_candidates(d):
        s = get_soup(u)
        if not s: continue
        last_page_url = u
        if u.lower().endswith(".pdf"): return {"pdf_index_url": u, "items": [], "issue": "NA"}
        items, issue = collect_from_daily_page(u, s)
        last_issue = issue or last_issue
        if items: return {"page_url": u, "items": items, "issue": issue or "NA"}
    if last_page_url: return {"page_url": last_page_url, "items": [], "issue": last_issue}
    return None


def sanitize(s):
    s = re.sub(r"[ \t/\\]+", "-", s.strip())
    s = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü\.-]+", "", s)
    return re.sub(r"-{2,}", "-", s)


def save_rec(n, rec):
    base = f"{rec['tarih']}_{rec['sayi']}_{sanitize(rec['kategori']).upper()}_{n:03d}"
    maxlen = 180
    if len(base) > maxlen:
        h = hashlib.md5((rec.get("kaynak_url", "") + rec.get("baslik", "")).encode("utf-8")).hexdigest()[:8]
        base = f"{base[:maxlen]}_{h}"
    fn = base + ".json"
    p = os.path.join(OUT_DIR, fn)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
    return p


def _normalize_ws(text: str) -> str:
    text = text or ""
    ws_chars = "\xa0\u2009\u202f\u2007\u200a\u2002\u2003\u2004\u2005\u2006"
    for char in ws_chars: text = text.replace(char, " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_headers_footers(text: str) -> str:
    lines = text.splitlines()
    out = []

    for ln in lines:
        s = ln.strip()

        if re.match(r"\d{1,2} [A-Za-zÇĞİÖŞÜçğıöşü]+ \d{4}(,|\s)?(PAZAR|PAZARTESİ|SALI|ÇARŞAMBA|PERŞEMBE|CUMA|CUMARTESİ)?", s, re.I):
            continue

        if "resmî gazete" in s.lower():
            continue

        if re.match(r"Sayı\s*:\s*\d{5}", s):
            continue

        if s.isupper() and len(s) < 20 and s in ["YÖNETMELİK", "TEBLİĞ", "KURUL KARARI", "GENELGE", "İLAN"]:
            continue

        out.append(ln)

    return "\n".join(out).strip()
def _strip_header_lines(text: str) -> str:

    lines = text.splitlines()
    cleaned = []
    skip_patterns = [
        r"^\s*\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+\d{4}(?:\s+[PAZARTESİ|SALI|ÇARŞAMBA|PERŞEMBE|CUMA|CUMARTESİ|PAZAR]*)?$",
        r"^\s*Resm[iî] Gazete\s*$",
        r"^\s*Sayı\s*:\s*\d+",
        r"^\s*Karar\s*No\s*:?\s*\d+",
        r"^\s*Karar\s*Tarihi\s*:?\s*\d{1,2}/\d{1,2}/\d{4}",
        r"^\s*\(.*?\)$",
    ]
    for ln in lines:
        if any(re.match(pat, ln.strip(), flags=re.IGNORECASE) for pat in skip_patterns):
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()

def extract_title_from_text(text: str) -> str:
    lines = text.splitlines()
    candidates = []

    for i, line in enumerate(lines[:30]):
        s = line.strip()
        if len(s) > 30 and s.isupper() and not s.lower().startswith("resmî gazete"):
            candidates.append(s)

        elif (
            40 < len(s) < 150
            and sum(1 for c in s if c.isupper()) > len(s) * 0.6
            and not re.match(r"\d{1,2} [A-Za-zÇĞİÖŞÜçğıöşü]+ \d{4}", s)
        ):
            candidates.append(s)

    if candidates:
        return max(candidates, key=len)

    return lines[0].strip() if lines else ""

def save_rec_with_pdf_and_images(n, rec, pdf_bytes=None, page_images=None):
    folder_name = f"{rec.tarih.replace('.', '')}_{rec.sayi}_{sanitize(rec.kategori).upper()}_{n:03d}"
    record_dir = os.path.join(OUT_DIR, folder_name)
    os.makedirs(record_dir, exist_ok=True)

    # PDF dosyasını kaydet
    pdf_filename = None
    if pdf_bytes:
        pdf_filename = "kaynak.pdf"
        pdf_path = os.path.join(record_dir, pdf_filename)
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)

    # Sayfa görsellerini kaydet
    image_paths = []
    if page_images:
        pages_dir = os.path.join(record_dir, "pages")
        os.makedirs(pages_dir, exist_ok=True)
        for i, img in enumerate(page_images, start=1):
            img_filename = f"page_{i}.png"
            img_path = os.path.join(pages_dir, img_filename)
            img.save(img_path)
            image_paths.append(os.path.relpath(img_path, record_dir))

    rec.pdf_dosyasi = pdf_filename if pdf_filename else ""
    rec.sayfa_resimleri = image_paths

    json_path = os.path.join(record_dir, "data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rec.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    return json_path

def pdf_to_text_robust_with_images(pdf_bytes: bytes):
    text_pieces, images, used_ocr = [], [], 0
    if PYMUPDF_OK and PIL_OK:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for pg in doc:
                txt = (pg.get_text("text") or "").strip()
                if len(txt) < 200:
                    ocr_txt = _ocr_page_with_tesseract(pg)
                    if len(ocr_txt.strip()) > len(txt):
                        txt = ocr_txt
                        used_ocr += 1
                text_pieces.append(txt)

                pix = pg.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            doc.close()
        except Exception:
            text_pieces, images = [], []

    text = "\n".join(text_pieces).strip()

    if len(text) < 200:
        try:
            params1 = LAParams(char_margin=2.0, line_margin=0.6, word_margin=0.10, boxes_flow=0.5)
            params2 = LAParams(char_margin=2.5, line_margin=0.3, word_margin=0.05, boxes_flow=None)
            t1 = pdf_extract_text(BytesIO(pdf_bytes), laparams=params1) or ""
            t2 = pdf_extract_text(BytesIO(pdf_bytes), laparams=params2) or ""
            text = t2 if len(t2) > len(t1) else t1
        except Exception:
            pass

    text = _normalize_ws(text)
    text = _dehyphenate(text)
    text = _strip_headers_footers(text)
    text = _strip_appendix_parts(text)

    return text.strip(), images


def _dehyphenate(text: str) -> str:
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


# --- PDF İŞLEME ---
def _ocr_page_with_tesseract(page, dpi=350, lang=None, config=None) -> str:
    if not (PYMUPDF_OK and PIL_OK and TESSERACT_OK): return ""
    lang = lang or os.getenv("OCR_LANG", "tur+eng")
    config = config or os.getenv("OCR_CONFIG", "--psm 6 --oem 3")
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=1)
    g = g.filter(ImageFilter.SHARPEN)
    bw = g.point(lambda x: 255 if x > 180 else 0)
    try:
        return pytesseract.image_to_string(bw, lang=lang, config=config)
    except Exception:
        return ""


def pdf_to_text_robust(pdf_bytes: bytes) -> str:
    pieces, used_ocr = [], 0
    if PYMUPDF_OK:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for pg in doc:
                txt = (pg.get_text("text") or "").strip()
                if len(txt) < 200:
                    ocr_txt = _ocr_page_with_tesseract(pg)
                    if len(ocr_txt.strip()) > len(txt):
                        txt = ocr_txt
                        used_ocr += 1
                pieces.append(txt)
            doc.close()
        except Exception:
            pieces = []
    base = "\n".join(pieces).strip()
    if len(base) < 200:
        try:
            params1 = LAParams(char_margin=2.0, line_margin=0.6, word_margin=0.10, boxes_flow=0.5)
            params2 = LAParams(char_margin=2.5, line_margin=0.3, word_margin=0.05, boxes_flow=None)
            t1 = pdf_extract_text(BytesIO(pdf_bytes), laparams=params1) or ""
            t2 = pdf_extract_text(BytesIO(pdf_bytes), laparams=params2) or ""
            base = t2 if len(t2) > len(t1) else t1
        except Exception:
            pass
    base = _normalize_ws(base)
    base = _dehyphenate(base)
    base = _strip_headers_footers(base)
    base = _strip_appendix_parts(base)
    base = _strip_header_lines(base)
    return base.strip()

def _cut_after_appendix_markers(text: str, min_keep_chars: int = 400) -> str:
    if not text:
        return text
    upper = text.upper()

    markers = [
        r"\bTARİHLİ\s+VE\s+\d+\s+SAYILI\s+CUMHURBAŞKANI\s+KARARININ\s+EK[İI]\b",
        r"CUMHURBAŞKANI\s+KARARININ\s+EK[İI]",
        r"\bEK[-–—]?\s*\d+\b",
        r"\bEK[İI]\b",
        r"\bL[İI]STE\b",
        r"\bKROK[İI]\b",
        r"\bKOORD[İI]NAT\s+L[İI]STES[İI]\b",
        r"\bHAR[İI]TA\b",
        r"\bTABLO\b",
        r"\bŞEMA\b",
        r"\bÇİZELGE\b",
        r"\bGRAF[İI]K\b",
        r"\bPROJE\s+ALANI\b",
        r"\bALAN\s+BÜYÜKLÜĞÜ\b"
    ]

    first_idx = None
    for pat in markers:
        m = re.search(pat, upper, flags=re.IGNORECASE)
        if m:
            idx = m.start()
            if first_idx is None or idx < first_idx:
                first_idx = idx

    if first_idx is not None and first_idx > min_keep_chars:
        return text[:first_idx].rstrip()
    return text

def _drop_coordinate_like_lines(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            out.append(ln)
            continue
        # Eğer satırda neredeyse hiç harf yoksa ve çok sayıda sayı varsa, atla
        if len(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", s)) < 3 and len(re.findall(r"\d", s)) > 5:
            continue
        out.append(ln)
    return "\n".join(out)

def _strip_appendix_parts(text: str) -> str:

    t = _cut_after_appendix_markers(text)
    t = _drop_coordinate_like_lines(t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()



# ----------------------------------------------------------------------
def parse_table_from_ocr_text(ocr_text: str) -> list[dict]:


    pattern = re.compile(
        r"^\s*(\d+)\s+" 
        r"(\d{1,2}\s+[A-Za-zŞşİıĞğÜüÖöÇç]+\s+\d{4}\s+[A-Za-zŞşİıĞğÜüÖöÇç]+)\s+" 
        r'["“]?(.*?)["”]?\s+'  
        r"(\d{1,2}\s+[A-Za-zŞşİıĞğÜüÖöÇç]+\s+\d{4})\s*$",
        re.MULTILINE
    )

    matches = pattern.findall(ocr_text)

    results = []
    for match in matches:
        results.append({
            "sira_no": match[0].strip(),
            "imza_tarihi_yeri": match[1].strip(),
            "anlasma_adi": match[2].strip().replace('”', '').replace('“', ''),
            "yururluk_tarihi": match[3].strip(),
        })

    if not results:
        print("   [UYARI] Tablo yapısı regex ile ayrıştırılamadı. Ham OCR metni kullanılacak.")

    return results


def format_table_as_text(table_data: list[dict]) -> str:
    if not table_data:
        return ""

    lines = []
    lines.append(f"{'SIRA NO':<10} | {'İMZA TARİHİ VE YERİ':<25} | {'ANLAŞMANIN ADI':<80} | {'YÜRÜRLÜK TARİHİ':<20}")
    lines.append("-" * 140)

    for row in table_data:
        lines.append(
            f"{row.get('sira_no', ''):<10} | "
            f"{row.get('imza_tarihi_yeri', ''):<25} | "
            f"{row.get('anlasma_adi', ''):<80} | "
            f"{row.get('yururluk_tarihi', '')}"
        )
    return "\n".join(lines)



def parse_detail(item: dict, date_str: str, seq_num: int) -> ResmiGazeteKaydi | None:
    url = item["url"]
    try:
        resp = SESSION.get(url, timeout=40)
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    content_type = (resp.headers.get("Content-Type") or "").lower()
    title = item.get("title_from_list", "").strip()
    text = ""
    pdf_bytes, images = None, []

    if url.lower().endswith(".pdf") or "pdf" in content_type:
        pdf_bytes = resp.content
        text, images = pdf_to_text_robust_with_images(pdf_bytes)

        if "CUMHURBAŞKANI KARARININ EKİ" in text or "LİSTE" in text:
            table_data = parse_table_from_ocr_text(text)
            if table_data:
                header_part = ""
                if "LİSTE" in text:
                    header_part = text.split("LİSTE")[0] + "LİSTE\n"
                elif "CUMHURBAŞKANI KARARININ EKİ" in text:
                    parts = text.split("CUMHURBAŞKANI KARARININ EKİ")
                    header_part = parts[0] + "CUMHURBAŞKANI KARARININ EKİ\n"

                formatted_table = format_table_as_text(table_data)
                text = header_part + "\n" + formatted_table
    else:
        soup = BeautifulSoup(resp.content, "lxml")
        try:
            t = extract_title(soup)
            if t:
                title = t
        except Exception:
            pass
        text = _normalize_ws(clean_text(soup))

    karar_kanun_no = extract_no(text)
    tarih = item.get("date_from_header") or date_str

    if not title or title.lower() == "resmî gazete":
        title = extract_title_from_text(text)

    # Pydantic model nesnesi oluştur
    rec = ResmiGazeteKaydi(
        tarih=tarih,
        sayi=item.get("issue") or "NA",
        kategori=item["category"],
        baslik=title,
        karar_kanun_no=karar_kanun_no or "",
        kaynak_url=url,
        metin=(text or "").strip(),
    )

    save_rec_with_pdf_and_images(seq_num, rec, pdf_bytes=pdf_bytes, page_images=images)

    return rec



def main():
    boot_session()
    today = datetime.now(tz=tz.tzlocal()).date()
    # son kaç gün olacağı belirleniyor
    dates = [today - timedelta(days=i) for i in range(0, 7)]
    for d in dates:
        ds = ddmmyyyy(datetime.combine(d, datetime.min.time()))
        print(f"[+] Gün: {ds}")
        pack = collect_for_date(d)
        if not pack:
            print("   (Hiçbir aday URL’den içerik alınamadı)")
            continue
        items, issue = pack["items"], pack.get("issue", "NA")
        if not items:
            if pack.get("pdf_index_url"):
                print(f"   Liste HTML’i yerine PDF indeks bulundu: {pack['pdf_index_url']}")
            else:
                print("   Sayfa açıldı ama listelenecek bağlantı bulunamadı.")
            continue
        print(f"   {len(items)} bağlantı bulundu (İlan Bölümü hariç). Ayrıştırılıyor...")
        seq = 1
        for it in items:
            it["issue"] = issue
            rec = parse_detail(it, ds, seq)
            if rec:
                print(f"   -> {rec.baslik[:60]}... [kaydedildi]")
                seq += 1
            time.sleep(0.4)


if __name__ == "__main__":
    main()