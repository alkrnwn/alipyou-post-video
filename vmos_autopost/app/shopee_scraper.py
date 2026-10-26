"""
shopee_scraper.py
=============================================================================
Modul Ekstraksi Detail Produk Shopee & Generator Kuncian Prompt ALIPYOU AUTO POST
Diadaptasi 1:1 dari AffiliatePromptService.js (TungTung Poster & ALIPYOU AUTO POST)
=============================================================================
"""

import html as html_lib
from html.parser import HTMLParser
import logging
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

_log = logging.getLogger(__name__)

# Google Flow Public API Key untuk resolve shared link tanpa login
FLOW_API_KEY = "AIzaSyDSjGxWlo68HcGt6mbaIq9YbkKhFQnt3sk"

# =============================================================================
# KUNCIAN PROMPT MASTER ALIPYOU AUTO POST (AffiliatePromptService.js)
# =============================================================================

CATEGORIES = [
    "Premium UGC / Soft-Sell",
    "Review / Unboxing",
    "Problem-Solution",
    "Price & Value",
    "Lifestyle / Aspirational",
    "Curiosity / Trending",
    "POV / Product Only",
]

_PRIMARY_RULE_LOCKED = """PRIMARY RULE (LOCKED):
The product shown in the reference image must remain 100% identical throughout the entire video. Preserve the exact shape, proportions, colors, materials, logo, branding, packaging, label, typography, graphics, texture, reflections, and every printed detail exactly as shown. Never redesign, regenerate, replace, duplicate, crop, stretch, melt, deform, rotate unnaturally, or hallucinate any part of the product. The reference image is the only source of truth.
The product must remain perfectly sharp, realistic, and be the main visual focus in every scene. Never allow text, hands, props, or effects to cover the product for more than one second."""

_VIDEO_STYLE_BASE = """VIDEO STYLE:
Create a premium short-form vertical style UGC advertisement with a fast-paced rhythm and excellent viewer retention. Use bright commercial lighting, smooth cinematic transitions, energetic camera movement, push-in shots, orbit shots, handheld movement, macro close-ups, side tracking, top-down views, dramatic reveals, speed ramps, focus pulls, and natural motion blur. Every scene should present a fresh perspective while maintaining perfect product consistency."""

_NARRATION_BASE = """NARRATION:
Generate a natural, conversational voice-over in {auto_language}. The voice should sound authentic, enthusiastic, and trustworthy, like someone sincerely sharing a useful recommendation rather than reading an advertisement.
Structure:
- First 3 seconds: instantly grab attention with a curiosity-driven hook.
- Middle: explain the most valuable benefits naturally.
- Final: leave viewers intrigued and encourage them to discover more without sounding promotional."""

_CTA_RULE_STRICT = """CTA RULE (STRICT):
Never use direct shopping instructions or sales commands.
Strictly avoid phrases including:
"cek keranjang"
"cek beg kuning"
"cek beg oren"
"klik link"
"klik bio"
"beli sekarang"
"order sekarang"
"checkout sekarang"
"langsung gas"
"jangan sampai kehabisan"
or any variation that directly asks viewers to purchase.
Instead, naturally end with one of these CTA styles:
- Express genuine curiosity.
- Invite viewers to find out more.
- Encourage them to experience the product themselves.
- Suggest comparing it with similar products.
- Encourage them to see why many people are talking about it.
- End with an engaging question related to the product.
Rotate CTA wording every generation so it never feels repetitive."""

_TEXT_ANIMATION = """TEXT ANIMATION:
Add pop-up animated emphasis sticker text on every word that sounds selling or interesting, written in {auto_language}, with text that is clear and easy to read. Ensure captions never block the product."""

_VISUAL_EFFECTS = """VISUAL EFFECTS:
Use premium commercial editing including subtle particles, light streaks, depth-of-field transitions, realistic reflections, motion graphics, dynamic masking, and cinematic transitions. Every effect should support the storytelling while keeping the product as the center of attention."""

_NEGATIVE_CONSTRAINTS = """NEGATIVE CONSTRAINTS (LOCKED):
No product deformation.
No packaging changes.
No incorrect colors.
No logo distortion.
No spelling mistakes.
No garbled, glitchy, warped, or unreadable characters in any on-screen text.
No random symbols or foreign/mixed alphabets in captions.
No long sentences rendered as on-screen text - captions must stay short and simple.
No duplicated products.
No AI artifacts.
No floating objects.
No blurry frames.
No warped labels.
No hallucinated accessories.
No extra fingers.
No unrealistic reflections.
No background clutter.
No flickering.
No unnecessary zooms that hide the product.
No nudity, sexual or suggestive content.
No exposed, unbuttoned, or see-through clothing.
No underwear worn as outerwear or clothing that reveals intimate body parts.
No TikTok, Shopee, or any other social media or e-commerce platform logo, icon, badge, or watermark anywhere in the video.
No app interface elements (buttons, icons, UI chrome) from any platform.
The video must stay completely neutral and free of any platform branding so it can be posted on any social media or marketplace platform."""

_AGENCY_QUALITY_STATEMENT = """The final video must look like a premium viral short-form vertical advertisement produced by a professional creative agency, optimized for maximum attention during the first 3 seconds and strong viewer retention through the entire 10-second duration."""

_LANGUAGE_MANDATORY = """LANGUAGE (MANDATORY - HIGHEST PRIORITY):
This instruction overrides every other instruction above. The spoken NARRATION/VOICE-OVER must be entirely in {auto_language}, spoken with the native accent and dialect of {auto_language} - NOT generic English. All on-screen animated captions must also be written in {auto_language}. These instructions are written in English only for clarity; they are NOT a request to narrate in English."""

_SAFE_NO_REAL_FACE_BLOCK = """ATURAN WAJAH & MODEL (WAJIB):
- Model manusia BOLEH tampil memakai/memperagakan produk. Wajah boleh terlihat penuh -- ini justru dianjurkan untuk produk fashion dan aksesori.
- Wajah model WAJIB wajah orang GENERIK hasil AI, dengan penampilan yang wajar untuk wilayah berbahasa {auto_language}.
- JANGAN menyalin, meniru, atau menganimasikan wajah orang yang ada di gambar referensi. Ganti dengan wajah generik yang BERBEDA. Wajah pada gambar referensi bukan bagian dari produk.
- JANGAN menampilkan tokoh publik, selebritas, atlet, politikus, atau wajah yang menyerupai orang terkenal mana pun.
- Yang WAJIB dipertahankan sama persis dari gambar referensi hanyalah PRODUKNYA -- bentuk, warna, logo, motif, dan tulisannya. Orangnya bebas diganti."""

_KLAUSA_NETRAL_PLATFORM = """STRICT NO-LOGO RULE (MANDATORY, HIGHEST PRIORITY, OVERRIDES ANY STYLE REFERENCE ABOVE):
every frame of the video and of its reference frame must be completely free of TikTok and Shopee logos and of any other app, marketplace, or social-media logo, icon, watermark, badge, app sticker, or app interface -- no like/comment/share/follow buttons, no shopping-cart or shopping-bag icons, no progress bars, no usernames, no hashtags, no phone-screen app mockups, no corner watermarks. The reference photo may contain seller watermarks, store logos, promotional stickers, price tags, banners, frames, or app screenshots placed ON TOP of the photo: these are NOT part of the product -- never copy them, show only the clean physical product in a clean scene. Only the brand name, logo, and label physically printed ON the product or its own packaging stay exactly as in the reference. Emphasis text and captions requested above are NOT affected by this rule."""

_PREMIUM_UGC_SOFT_SELL = f"""Create a 10-second high-retention promotional video for {{title}} in {{auto_language}}.

{_PRIMARY_RULE_LOCKED}

{_VIDEO_STYLE_BASE}

{_NARRATION_BASE}

{_CTA_RULE_STRICT}

{_TEXT_ANIMATION}

{_VISUAL_EFFECTS}

{_NEGATIVE_CONSTRAINTS}

{_AGENCY_QUALITY_STATEMENT}

{_LANGUAGE_MANDATORY}

{_SAFE_NO_REAL_FACE_BLOCK}

{_KLAUSA_NETRAL_PLATFORM}"""

# 30 Naskah Hook PDF Asli TungTung Poster (T01 - T30)
_PDF_TEMPLATES = [
    {"id": "T01", "cat": "Review / Unboxing", "hook": "reaksi spontan saat produk pertama kali terlihat, seolah kamera menangkap detik pertama", "body": "sebutkan 2 hal konkret yang terlihat atau terasa dari produk sebagai pengamatan pribadi", "cta": "ajakan santai ala teman yang merekomendasikan", "tone": "Autentik dan antusias tapi tidak berlebihan. Terdengar seperti orang sungguhan, bukan iklan."},
    {"id": "T02", "cat": "Review / Unboxing", "hook": "sebut bahwa produk ini yang bikin orang balik beli lagi", "body": "jelaskan 1-2 alasan konkret kenapa orang mengulang pembelian", "cta": "ajakan singkat untuk ikut mencoba", "tone": "Santai, penasaran, dekat. Seperti mengabari teman soal temuan bagus."},
    {"id": "T03", "cat": "Review / Unboxing", "hook": "posisikan diri sebagai orang yang sudah memakai produk ini cukup lama", "body": "sebutkan 1-2 hal yang baru terasa setelah dipakai berulang kali, bukan kesan sekilas", "cta": "rekomendasi jujur tanpa terdengar disponsori", "tone": "Teman tepercaya yang memberi saran nyata. Tidak terdengar seperti endorse."},
    {"id": "T04", "cat": "Review / Unboxing", "hook": "ketidakpercayaan bahwa barang semurah ini bisa sebagus ini", "body": "sebutkan 2 detail yang biasanya cuma ada di produk jauh lebih mahal", "cta": "ajakan cepat sebelum kehabisan", "tone": "Sedikit tidak percaya, seperti menemukan penawaran langka. Terasa seperti rahasia yang dibagi."},
    {"id": "T05", "cat": "Review / Unboxing", "hook": "posisi sebagai orang yang sudah membandingkan banyak pilihan sejenis", "body": "sebutkan 2 alasan konkret kenapa yang ini menang dibanding pilihan lain", "cta": "ajakan langsung tanpa hype", "tone": "Ahli tapi mudah didekati. Seperti pengulas produk yang dipercaya. Hindari kata-kata lebay."},
    {"id": "T06", "cat": "Review / Unboxing", "hook": "sebut bahwa orang-orang di sekitarmu ikut memakainya", "body": "sebutkan 1-2 alasan kenapa produk ini menular dari orang ke orang", "cta": "ajakan hangat tanpa tekanan", "tone": "Hangat, personal, nol tekanan jualan. Energi rekomendasi dari mulut ke mulut."},
    {"id": "T07", "cat": "Problem-Solution", "hook": "sapa langsung orang yang punya masalah spesifik yang dipecahkan produk ini", "body": "jelaskan masalahnya lalu bagaimana produk menyelesaikannya, dalam satu alur", "cta": "ajakan membantu, bukan menjual", "tone": "Tulus dan menolong. Seperti membagi tips hidup ke teman. Hindari klaim medis atau hukum."},
    {"id": "T08", "cat": "Problem-Solution", "hook": "penyesalan kenapa tidak tahu ini dari dulu", "body": "sebutkan masalah lama dan bagaimana produk ini menghentikannya", "cta": "ajakan singkat dan padat", "tone": "Energi kaget menemukan sesuatu. Pendek dan menghentak."},
    {"id": "T09", "cat": "Problem-Solution", "hook": "panggil langsung kelompok orang tertentu yang paling butuh produk ini", "body": "jelaskan kenapa kelompok itu paling terbantu, dengan 2 alasan konkret", "cta": "ajakan tenang dan jelas", "tone": "Informatif, berwibawa tenang. Seperti teman yang paham betul soal ini."},
    {"id": "T10", "cat": "Problem-Solution", "hook": "satu-satunya hal yang diubah, langsung dibingkai sebagai sebelum vs sesudah", "body": "gambarkan keadaan sebelum, lalu keadaan sesudah, tanpa membesar-besarkan", "cta": "ajakan jujur", "tone": "Gaya testimoni, terukur dan masuk akal. Jangan terdengar ajaib."},
    {"id": "T11", "cat": "Problem-Solution", "hook": "normalkan masalahnya supaya penonton merasa tidak sendirian", "body": "tunjukkan bahwa masalah itu wajar, lalu produk sebagai jalan keluar sederhana", "cta": "ajakan yang mengundang, bukan mendesak", "tone": "Empatik, memahami, merangkul."},
    {"id": "T12", "cat": "Problem-Solution", "hook": "keluhan soal uang yang sudah terbuang untuk solusi yang tidak berhasil", "body": "jelaskan kenapa yang dulu gagal, lalu apa yang berbeda dari produk ini", "cta": "ajakan lugas", "tone": "Sedikit kesal tapi akhirnya menolong. Energi orang sungguhan."},
    {"id": "T13", "cat": "Problem-Solution", "hook": "sebut bahwa pendekatan seperti ini yang biasanya disarankan untuk masalah tersebut", "body": "jelaskan pendekatannya lalu bagaimana produk ini menerapkannya", "cta": "ajakan tenang dan kredibel", "tone": "Berpengetahuan dan kredibel. Bingkai sebagai pendekatan yang disarankan, BUKAN klaim medis."},
    {"id": "T14", "cat": "Problem-Solution", "hook": "penyesalan waktu -- andai menemukan ini lebih cepat", "body": "ceritakan perjuangan panjangnya, lalu solusinya, lalu satu manfaat tak terduga", "cta": "ajakan langsung dan bersih", "tone": "Reflektif dan tulus. Unsur kejutan di akhir adalah kunci daya tariknya."},
    {"id": "T15", "cat": "Price & Value", "hook": "ketidakpercayaan pada harga dibanding kualitas yang terlihat", "body": "sebutkan 2 detail yang membuatnya terasa jauh lebih mahal dari harganya", "cta": "ajakan sebelum kehabisan", "tone": "Terkesan dan sedikit tak percaya. Seperti menemukan barang mewah dengan harga loak. Hindari pujian murahan."},
    {"id": "T16", "cat": "Price & Value", "hook": "bingkai ulang 'murah' sebagai pilihan cerdas, bukan barang kelas dua", "body": "tunjukkan bahwa yang dibayar mahal di tempat lain sebenarnya cuma nama", "cta": "ajakan percaya diri", "tone": "Energi pembeli cerdas. Anti bayar mahal cuma demi merek. Sedikit menyombong tapi menyenangkan."},
    {"id": "T17", "cat": "Price & Value", "hook": "bingkai 'daripada beli yang itu' sebagai pilihan yang lebih masuk akal", "body": "bandingkan nilai yang didapat, tanpa menyebut merek lain dan tanpa angka", "cta": "ajakan kalem", "tone": "Pembeli jeli. Bangga pada keputusan cerdas tanpa menggurui."},
    {"id": "T18", "cat": "Price & Value", "hook": "sudut hadiah -- terlihat mahal padahal tidak", "body": "sebutkan 2 hal yang bikin produk ini terlihat pantas jadi hadiah", "cta": "ajakan ceria", "tone": "Energi orang yang senang memberi hadiah. Riang."},
    {"id": "T19", "cat": "Price & Value", "hook": "keresahan bahwa harga-harga makin naik, lalu produk ini jadi pengecualian", "body": "tunjukkan bagaimana produk ini menahan pengeluaran tanpa mengorbankan kualitas", "cta": "ajakan melindungi dompet", "tone": "Peka soal pengeluaran, berpihak pada dompet penonton."},
    {"id": "T20", "cat": "Lifestyle / Aspirational", "hook": "hal kecil yang ternyata membuat perbedaan besar", "body": "gambarkan satu momen keseharian di mana perbedaan itu terasa", "cta": "ajakan halus", "tone": "Reflektif dan tulus. Perbaikan hidup tanpa dilebih-lebihkan."},
    {"id": "T21", "cat": "Lifestyle / Aspirational", "hook": "masukkan produk ke dalam rutinitas pagi yang tertata", "body": "tunjukkan bagaimana produk menyatu di rutinitas itu, bukan daftar fitur", "cta": "ajakan pelan", "tone": "Tenang, estetis, terasa sengaja ditata. Energi orang yang menikmati paginya."},
    {"id": "T22", "cat": "Lifestyle / Aspirational", "hook": "posisikan sebagai barang yang benar-benar dipakai sehari-hari, bukan sekadar dibeli", "body": "tunjukkan 1-2 momen pemakaian nyata yang membuktikan itu", "cta": "ajakan tanpa tekanan", "tone": "Terkurasi dan tepercaya. Tidak berusaha menjual segalanya."},
    {"id": "T23", "cat": "Lifestyle / Aspirational", "hook": "panggil komunitas atau penyuka hobi tertentu secara langsung", "body": "jelaskan kenapa produk ini masuk akal khusus untuk mereka", "cta": "ajakan sesama anggota komunitas", "tone": "Sesama anggota komunitas, bukan penjual ke pembeli. Suara orang dalam."},
    {"id": "T24", "cat": "Lifestyle / Aspirational", "hook": "posisikan diri sebagai orang yang sulit terkesan", "body": "jelaskan apa yang akhirnya membuat terkesan, dengan 2 detail konkret", "cta": "pujian yang akhirnya diberikan", "tone": "Selektif dan terukur. Pujiannya lebih berarti karena diberikan dengan enggan."},
    {"id": "T25", "cat": "Curiosity / Trending", "hook": "awalnya ragu pada produk yang sedang ramai, lalu membuktikannya sendiri", "body": "ceritakan apa yang ternyata benar setelah dicoba", "cta": "ajakan cepat", "tone": "Menyelidik, awalnya skeptis, berakhir jadi percaya."},
    {"id": "T26", "cat": "Curiosity / Trending", "hook": "sebut satu hal yang paling sering bikin orang terkejut dari produk ini", "body": "ungkap hal itu dan kenapa itu penting", "cta": "ajakan singkat", "tone": "Hype yang ditahan. Biarkan faktanya yang bicara."},
    {"id": "T27", "cat": "Curiosity / Trending", "hook": "sebagian besar orang belum tahu satu kegunaan produk ini", "body": "ungkap kegunaan tak terduga itu secara jelas, jangan digantung", "cta": "ajakan cepat", "tone": "Energi bocoran orang dalam. Seperti membagi tips rahasia."},
    {"id": "T28", "cat": "Curiosity / Trending", "hook": "produk ini sering keburu habis sebelum sempat dilihat orang", "body": "jelaskan kenapa cepat diburu, dengan 1-2 alasan konkret", "cta": "ajakan mendesak tapi wajar", "tone": "Seperti orang yang beruntung kebagian. Menciptakan keinginan lewat kelangkaan."},
    {"id": "T29", "cat": "Curiosity / Trending", "hook": "buka dengan sisi lucu atau tak terduga dari produk ini", "body": "lanjutkan dengan kegunaan aslinya supaya tetap menjual", "cta": "ajakan ringan", "tone": "Jenaka dan ringan. Humor lebih mudah dibagikan daripada jualan langsung."},
    {"id": "T30", "cat": "Curiosity / Trending", "hook": "hampir saja melewatkan produk ini, lalu ternyata menyesal kalau sampai terlewat", "body": "ceritakan apa yang hampir membuat ragu, lalu apa yang mengubah pikiran", "cta": "ajakan jujur", "tone": "Reflektif dan jujur. Alur 'hampir terlewat' sangat mudah dirasakan penonton."}
]

_ANGLE_VISUAL = {
    "Curiosity / Trending": "Tahan dulu bagian kunci produk di awal (terlihat sebagian/terhalang), baru diperlihatkan penuh saat pengungkapan. Gerakan kamera cepat, potongan tegas, tempo tinggi khas konten viral.",
    "Lifestyle / Aspirational": "Tempatkan produk di dalam momen keseharian yang nyaman dan tertata. Gerakan kamera pelan dan sinematik, pencahayaan alami dan hangat, tempo tenang.",
    "Price & Value": "Tampilkan produk secara utuh dan rapi seperti product showcase, lalu close-up detail yang membuktikan kualitasnya. Pencahayaan studio bersih, background simpel.",
    "Problem-Solution": "Tunjukkan kontras keadaan SEBELUM (berantakan/repot) lalu SESUDAH memakai produk (rapi/lega). Perpindahan tegas antara dua keadaan, pencahayaan sebelum lebih redup dan sesudah lebih terang.",
    "Review / Unboxing": "Buka dengan momen produk pertama kali terlihat jelas di kamera, lanjut close-up detail dari 1-2 angle. Gerakan kamera cepat tapi halus, pencahayaan cerah, tempo padat khas UGC review.",
    "Premium UGC / Soft-Sell": "Buka dengan tampilan produk yang estetik dan bersih, gerakan kamera halus cinematic push-in dan detail tekstur produk yang sharp.",
    "POV / Product Only": "Shoot entirely from the viewer's first-person point of view. Open with a close POV push-in toward the product, revealing its best detail with soft studio lighting."
}


_cat_rot_state = {"order": list(CATEGORIES), "index": 0}

def _get_next_category() -> str:
    """Ambil kategori prompt berikutnya secara rotasi acak tanpa pengulangan beruntun."""
    if not _cat_rot_state["order"] or _cat_rot_state["index"] >= len(_cat_rot_state["order"]):
        order = list(CATEGORIES)
        random.shuffle(order)
        _cat_rot_state["order"] = order
        _cat_rot_state["index"] = 0
    cat = _cat_rot_state["order"][_cat_rot_state["index"]]
    _cat_rot_state["index"] += 1
    return cat


def build_alipyou_prompt(title: str, category: str = "Random", auto_language: str = "Bahasa Indonesia", with_price: bool = False, harga: str = "") -> Dict[str, Any]:
    """
    Menghasilkan Prompt Kuncian Asli ALIPYOU AUTO POST (AffiliatePromptService.js).
    Mendukung mode acak rotasi otomatis untuk variasi maksimal.
    """
    if not category or any(w in str(category).lower() for w in ["random", "acak", "semua", "default"]):
        category = _get_next_category()
    elif category not in CATEGORIES:
        category = _get_next_category()

    # Pilih template PDF jika Review / Problem / Price / Lifestyle / Curiosity
    matching_pdfs = [t for t in _PDF_TEMPLATES if t["cat"] == category]
    chosen_pdf = random.choice(matching_pdfs) if matching_pdfs else None

    visual = _ANGLE_VISUAL.get(category, "Buka dengan momen produk pertama kali terlihat jelas di kamera, pencahayaan cerah, gerakan kamera cepat namun halus.")
    
    if category == "Premium UGC / Soft-Sell" or not chosen_pdf:
        prompt_text = _PREMIUM_UGC_SOFT_SELL.replace("{title}", title).replace("{auto_language}", auto_language)
        narration_text = f"Temukan kemudahan dan kualitas terbaik dari {title}. Desain praktis, material premium, dan sangat bermanfaat untuk keseharian Anda. Coba dan rasakan sendiri perbedaannya!"
    else:
        narration_structure = f"""Generate a natural, conversational voice-over in {auto_language}. ({chosen_pdf['id']}: {chosen_pdf['tone']})
Structure:
- First 3 seconds (HOOK): {chosen_pdf['hook']}
- Middle (BODY): {chosen_pdf['body']}
- Final (CTA): {chosen_pdf['cta']}
Total narasi maksimal 25 kata agar muat dalam 10 detik."""

        prompt_text = f"""Create a 10-second high-retention promotional video for {title} in {auto_language}.

{_PRIMARY_RULE_LOCKED}

VIDEO STYLE:
Create a premium short-form vertical style UGC advertisement with a fast-paced rhythm and excellent viewer retention. {visual} Use bright commercial lighting, smooth cinematic transitions, energetic camera movement, push-in shots, orbit shots, handheld movement, macro close-ups, side tracking, top-down views, dramatic reveals, speed ramps, focus pulls, and natural motion blur. Every scene should present a fresh perspective while maintaining perfect product consistency.

NARRATION:
{narration_structure}

{_CTA_RULE_STRICT}

{_TEXT_ANIMATION.replace('{auto_language}', auto_language)}

{_VISUAL_EFFECTS}

{_NEGATIVE_CONSTRAINTS}

{_AGENCY_QUALITY_STATEMENT}

{_LANGUAGE_MANDATORY.replace('{auto_language}', auto_language)}

{_SAFE_NO_REAL_FACE_BLOCK.replace('{auto_language}', auto_language)}

{_KLAUSA_NETRAL_PLATFORM}"""

        narration_text = f"Ssst... ini yang banyak orang belum tau tentang {title}. Bahannya beneran beda dari yang lain, kuat dan awet banget. Coba bandingin sendiri di rumah!"

    # Caption Shopee Video
    clean_short_title = title[:45].strip()
    caption = (
        f"Rekomendasi terbaik! ✨ {clean_short_title}\n\n"
        f"Kualitasnya beneran bagus dan bermanfaat banget. Checkout sekarang sebelum kehabisan stok promo ya! 👇\n\n"
        f"#racunshopee #shopeevideo #rekomendasiproduk #viral #fyp"
    )

    return {
        "category": category,
        "template_id": chosen_pdf["id"] if chosen_pdf else "UGC",
        "video_prompt": prompt_text,
        "voiceover": narration_text,
        "caption": caption
    }


def resolve_shopee_url(url_str: str) -> str:
    """Mengikuti shortlink Shopee (s.shopee.co.id, shp.ee, dsb.) sampai ke URL final."""
    url = (url_str or "").strip().strip("\"'")
    if any(s in url for s in ["shp.ee", "shope.ee", "s.shopee.co.id", "s.shopee.com.my"]):
        try:
            with httpx.Client(follow_redirects=True, timeout=12.0) as client:
                r = client.get(url, headers={"User-Agent": "facebookexternalhit/1.1"})
                return str(r.url)
        except Exception as e:
            _log.warning(f"Gagal resolve shortlink {url}: {e}")
    return url


def parse_shopee_ids(url: str) -> Tuple[Optional[str], Optional[str], str]:
    """Ekstraksi shop_id, item_id, dan URL canonical bersih."""
    shop_id, item_id = None, None
    m_i = re.search(r"i\.(\d+)\.(\d+)", url)
    if m_i:
        shop_id, item_id = m_i.group(1), m_i.group(2)
    else:
        m_slash = re.search(r"(?:product/|^)(\d{4,15})/(\d{4,15})", url)
        if m_slash:
            shop_id, item_id = m_slash.group(1), m_slash.group(2)
        else:
            m_shop = re.search(r"shopid=(\d+)", url, re.I)
            m_item = re.search(r"itemid=(\d+)", url, re.I)
            if m_shop and m_item:
                shop_id, item_id = m_shop.group(1), m_item.group(1)

    domain = ".com.my" if ".com.my" in url else ".co.id"
    canonical_url = f"https://shopee{domain}/product/{shop_id}/{item_id}" if (shop_id and item_id) else url
    return shop_id, item_id, canonical_url


def is_valid_photo(url_or_hash: str) -> bool:
    """Filter ketat: memastikan hanya foto produk murni (bukan video, preview, atau icon)."""
    if not url_or_hash:
        return False
    s = str(url_or_hash).lower().strip()
    video_blacklist = [".mp4", ".m3u8", ".webm", ".mov", ".avi", "video", "play_url", "preview_video"]
    if any(vb in s for vb in video_blacklist):
        return False
    non_photo = [".svg", "icon", "splash", "badge", "avatar", "logo", "watermark"]
    if any(np in s for np in non_photo):
        return False
    return True


def clean_title(raw_title: str) -> str:
    """Membersihkan judul produk dari embel-embel marketplace."""
    if not raw_title:
        return ""
    title = html_lib.unescape(raw_title)
    for suffix in [
        "| Shopee Indonesia",
        "| Shopee Malaysia",
        "Shopee Indonesia",
        "Shopee Malaysia",
        "- Shopee",
        "Situs Belanja Online Terlengkap & Terpercaya",
    ]:
        title = title.replace(suffix, "")
    title = re.sub(r"^\s*[|\-•:]+\s*", "", title)
    title = re.sub(r"\s*[|\-•:]+\s*$", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


class ShopeeHTMLMetaParser(HTMLParser):
    """Parser ringan dan tangguh untuk mengekstrak metadata OpenGraph & title dari HTML Shopee."""
    def __init__(self):
        super().__init__()
        self.meta: Dict[str, str] = {}
        self.title_tag: str = ""
        self._in_title: bool = False

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "meta":
            ad = dict(attrs)
            k = ad.get("property") or ad.get("name")
            c = ad.get("content")
            if k and c:
                self.meta[k.lower()] = c.strip()
        elif t == "title":
            self._in_title = True

    def handle_data(self, data):
        if self._in_title:
            self.title_tag += data

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False


DEFAULT_FALLBACK_IMAGE = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=700&q=85"


def extract_product_details(url_input: str, category: str = "Random") -> Dict[str, Any]:
    """
    Ekstraksi detail produk Shopee via Social Crawler SSR (bypass WAF tanpa login),
    menghasilkan bahan foto, metadata, dan Kuncian Prompt ALIPYOU AUTO POST asli.
    """
    resolved_url = resolve_shopee_url(url_input)
    shop_id, item_id, canonical_url = parse_shopee_ids(resolved_url)
    domain_prefix = "down-my" if ".com.my" in resolved_url else "down-id"
    auto_lang = "Bahasa Melayu" if ".com.my" in resolved_url else "Bahasa Indonesia"

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    raw_html = ""
    # Coba WhatsApp UA terlebih dahulu karena Shopee sering 403 terhadap FB hit
    for ua in [
        "WhatsApp/2.21.12.21 A",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]:
        try:
            headers["User-Agent"] = ua
            with httpx.Client(follow_redirects=True, timeout=12.0) as client:
                resp = client.get(resolved_url, headers=headers)
                if resp.status_code == 200 and len(resp.text) > 500:
                    raw_html = resp.text
                    break
        except Exception as e:
            _log.warning(f"Error fetching Shopee HTML with UA {ua}: {e}")

    # Ekstraksi OpenGraph Metadata via HTMLParser
    title = ""
    image = ""
    description = ""
    gallery_images: List[str] = []

    if raw_html:
        parser = ShopeeHTMLMetaParser()
        try:
            parser.feed(raw_html)
        except Exception as e:
            _log.warning(f"Error parsing HTML: {e}")

        raw_title = parser.meta.get("og:title") or parser.title_tag or parser.meta.get("title") or ""
        title = clean_title(raw_title)

        image = parser.meta.get("og:image") or ""
        raw_desc = parser.meta.get("description") or parser.meta.get("og:description") or ""
        description = html_lib.unescape(raw_desc).strip()

        # Ekstraksi seluruh hash foto produk galeri susercontent
        raw_hashes = re.findall(r'susercontent\.com/file/([a-zA-Z0-9_\-]+)', raw_html)
        seen = set()
        if image:
            gallery_images.append(image)
            m = re.search(r"file/([a-zA-Z0-9_\-]+)", image)
            if m:
                seen.add(m.group(1))

        for h in raw_hashes:
            if is_valid_photo(h) and h not in seen:
                seen.add(h)
                gallery_images.append(f"https://{domain_prefix}.img.susercontent.com/file/{h}")

    if not title or len(title) <= 2 or title.lower() in ("shopee", "shopping cart icon", "shopee indonesia", "shopee malaysia"):
        slug_match = re.search(r"shopee(?:\.co\.id|\.com\.my)/([^/?]+)-i\.\d+\.\d+", resolved_url)
        if slug_match:
            slug = slug_match.group(1).replace("-", " ").strip()
            title = clean_title(slug.title())
        elif item_id:
            title = f"Produk Shopee #{item_id}"
        else:
            title = "Produk Pilihan Rekomendasi"

    hero_image = image or (gallery_images[0] if gallery_images else DEFAULT_FALLBACK_IMAGE)

    # Generate Kuncian Prompt ASLI ALIPYOU AUTO POST
    prompt_data = build_alipyou_prompt(title, category=category, auto_language=auto_lang)

    return {
        "success": True,
        "title": title,
        "item_id": item_id,
        "shop_id": shop_id,
        "canonical_url": canonical_url,
        "image": hero_image,
        "gallery_images": gallery_images[:12],
        "description": description[:500] if description else "",
        "kuncian_prompt": prompt_data,
        "caption": prompt_data["caption"],
    }


def download_image_to_pc(image_url: str, filename: Optional[str] = None, open_folder: bool = True) -> Dict[str, Any]:
    """
    Mengunduh foto produk Shopee dan menyimpannya langsung ke folder Downloads komputer.
    Mendukung auto-reveal di Windows Explorer agar operator bisa langsung drag/upload ke Google Flow.
    """
    if not image_url or not str(image_url).startswith("http"):
        raise ValueError("URL gambar tidak valid")

    clean_fn = re.sub(r'[\\/*?:"<>|]', "", filename or f"shopee_foto_{int(time.time())}.jpg")
    if not clean_fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        clean_fn += ".jpg"

    # Simpan ke folder Downloads user
    downloads_dir = Path(os.path.expanduser("~")) / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target_path = downloads_dir / clean_fn

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://shopee.co.id/"
    }

    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        resp = client.get(image_url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Gagal mengunduh gambar (HTTP {resp.status_code})")
        target_path.write_bytes(resp.content)

    if open_folder and os.name == "nt":
        try:
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(target_path)])
        except Exception as e:
            _log.warning(f"Gagal membuka explorer: {e}")

    return {
        "ok": True,
        "path": str(target_path),
        "filename": clean_fn,
        "size_kb": round(len(resp.content) / 1024, 1)
    }


def resolve_flow_url(flow_url: str) -> Optional[str]:
    """
    Mengubah link share Google Flow (https://flow.google.com/shared/video/{id})
    menjadi URL direct stream MP4 via API publik Google aisandbox-pa.
    """
    if not flow_url or not str(flow_url).startswith("http"):
        return flow_url

    m = re.search(r"flow\.google\.com/shared/video/([a-f0-9\-]+)", flow_url)
    if not m:
        return flow_url

    shared_id = m.group(1)
    api_url = f"https://aisandbox-pa.googleapis.com/v1/flowMedia/{shared_id}:getSharedMedia?key={FLOW_API_KEY}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://flow.google.com/",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(api_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                primary = data.get("primaryMedia", {})
                video = primary.get("video", {})
                direct_url = (
                    video.get("generatedVideo", {}).get("fifeUrl")
                    or video.get("servingUrls", {}).get("gcsUrls", {}).get("videoUrl")
                )
                if direct_url:
                    return direct_url
    except Exception as e:
        _log.warning(f"Gagal resolve Flow Shared Link {flow_url}: {e}")

    return flow_url


def download_video_to_cache(url: str, cache_dir: str) -> str:
    """
    Mengunduh video (bisa link Google Flow atau direct MP4) ke direktori cache lokal.
    Mengembalikan path file lokal.
    """
    os.makedirs(cache_dir, exist_ok=True)
    real_url = resolve_flow_url(url) or url

    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = f"flow_video_{url_hash}.mp4"
    dest_path = os.path.join(cache_dir, filename)

    if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 1024:
        return dest_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://flow.google.com/",
    }

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        with client.stream("GET", real_url, headers=headers) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Gagal mengunduh video dari {url} (HTTP {response.status_code})")
            with open(dest_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=65536):
                    f.write(chunk)

    return dest_path
