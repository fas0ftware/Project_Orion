import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

# --- KULLANICI AYARLARI ---
URL = "Takip etmek istediğin URL"   # <--- Takip edeceğin ürüne ait URL
TELEGRAM_TOKEN = "Bot Token"    # <--- Bot oluşturup Apisini yaz
CHAT_ID = "BURAYA_ID_YAPISTIR"  # <--- ID'ni buraya tekrar yaz

# Alarm Hangi Fiyatta Çalsın? ()
TARGET_PRICE = 35000 

# Kaç dakikada bir kontrol etsin?
CHECK_INTERVAL_MINUTES = 60 

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
}

def send_telegram_message(message):
    send_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(send_url, data=data)
    except Exception as e:
        print(f"Mesaj gönderme hatası: {e}")

def check_price():
    try:
        response = requests.get(URL, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html.parser")
            price_element = soup.find(class_="product-list__price")
            
            if price_element:
                raw_price = price_element.text.strip()
                cleaned_price = float(raw_price.replace("TL", "").strip().replace(".", "").replace(",", "."))
                product_name = soup.title.text.strip()[:20]
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Kontrol edildi: {cleaned_price} TL")
                
                # --- ASIL MANTIK BURADA ---
                if cleaned_price <= TARGET_PRICE:
                    msg = f"🚨 İNDİRİM ALARMI! 🚨\n\n📦 Ürün: {product_name}\n📉 Yeni Fiyat: {cleaned_price} TL\n🎯 Hedefin: {TARGET_PRICE} TL\n\nHemen Al: {URL}"
                    send_telegram_message(msg)
                    print("✅ Fiyat düştü! Mesaj gönderildi.")
                else:
                    print(f"   ↳ Fiyat hala yüksek ({TARGET_PRICE} TL'den fazla). Mesaj atılmadı.")
            else:
                print("⚠️ Fiyat etiketi bulunamadı.")
        else:
            print(f"⚠️ Bağlantı sorunu: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Hata: {e}")

print(f"🤖 Aesthesius Price Tracker Başlatıldı! {CHECK_INTERVAL_MINUTES} dakikada bir kontrol edilecek...")
send_telegram_message("🤖 Bot aktif edildi! Fiyat takibi başladı Kuzgun.")

# --- SONSUZ DÖNGÜ ---
while True:
    check_price()
    # Bilgisayarı yormamak için uykuya geçiyoruz
    time.sleep(CHECK_INTERVAL_MINUTES * 60)