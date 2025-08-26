from pydantic import BaseModel, HttpUrl
from typing import Optional, List


class ResmiGazeteKaydi(BaseModel):
    tarih: str
    sayi: str
    kategori: str
    baslik: str
    karar_kanun_no: Optional[str] = ""
    kaynak_url: HttpUrl
    metin: str
    pdf_dosyasi: Optional[str] = ""
    sayfa_resimleri: Optional[List[str]] = []
