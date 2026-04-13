import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re
import google.generativeai as genai
from PIL import Image

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Hisse Sıralama Motoru", layout="wide")
st.title("Hisse RsRank bazlı İdealite ve LookBack kadar Ortalama F/K bazlı ucuzluk Isı Haritası (Yapay Zeka Destekli) [KazimKrbck]")
st.markdown("Likidite ayarlı teknik metrikler, normalize edilmiş F/K haritası ve **Gemini Görüntü Okuma** sistemi.")

# --- GİRDİLER VE GEMINI YAPAY ZEKA ---
st.sidebar.header("Parametreler")

bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False, help="Türk hisseleri için otomatik .IS uzantısı ekler.")

if bist_mode:
    default_tickers = "THYAO, TUPRS, KCHOL, AKBNK, ISCTR, EREGL, FROTO, SISE, BIMAS, ASELS"
    default_bench = "XU100.IS"
    default_dxy = "TRY=X" 
else:
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, INTC, AMD, NFLX"
    default_bench = "^GSPC"
    default_dxy = "DX-Y.NYB"

# --- GEMINI GÖRÜNTÜ OKUMA BÖLÜMÜ ---
st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Resimden Hisse Çıkarma")

if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 Gemini API Anahtarı gizli kasadan güvenle yüklendi!")
else:
    gemini_api_key = st.sidebar.text_input("Gemini API Anahtarı (Zorunlu)", type="password", help="aistudio.google.com adresinden ücretsiz alabilirsiniz.")

uploaded_file = st.sidebar.file_uploader("Hisse Listesi Resmi Yükle", type=["png", "jpg", "jpeg"])

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = default_tickers

if uploaded_file is not None and gemini_api_key:
    if st.sidebar.button("✨ Resmi Oku ve Listeyi Doldur"):
        with st.spinner("Gemini resmi inceliyor, hisseleri buluyor..."):
            try:
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                img = Image.open(uploaded_file)
                
                prompt = """
                Bu resimde bir borsa/hisse tarama tablosu veya listesi var. 
                Senden tek istediğim, resimdeki hisse senedi sembollerini (ticker) bulman.
                Bana SADECE büyük harflerle, aralarında virgül ve boşluk olan bir liste ver.
                Örnek çıktı: AAPL, MSFT, TSLA
                Başka hiçbir cümle, açıklama veya kelime yazma! Sadece semboller.
                """
                response = model.generate_content([prompt, img])
                
                st.session_state.current_tickers = response.text.strip()
                st.sidebar.success("Hisseler başarıyla çekildi! Aşağıdan analizi başlatabilirsiniz.")
            except Exception as e:
                st.sidebar.error(f"Yapay Zeka Hatası: Lütfen API anahtarınızı kontrol edin. ({str(e)[:40]})")

st.sidebar.markdown("---")

tickers_input = st.sidebar.text_area("Hisse Sembolleri (Virgülle ayırın, Maks 100)", st.session_state.current_tickers, height=150)

bench_ticker = st.sidebar.text_input("Piyasa Endeksi", default_bench)
dxy_ticker = st.sidebar.text_input("Kur/Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("Alan Oranı Geriye Bakış (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = []
for t in raw_tickers:
    if bist_mode and not t.endswith(".IS"):
        tickers.append(t + ".IS")
    else:
        tickers.append(t)

if len(tickers) > 100:
    st.sidebar.warning("100'den fazla hisse girdiniz. Performans için sadece ilk 100 hisse işlenecek.")
    tickers = tickers[:100]

# --- HESAPLAMA FONKSİYONLARI ---
def calc_roc(series, periods):
    return series.pct_change(periods=periods) * 100

def calc_weighted_rs(series):
    return (0.4 * calc_roc(series, 63) +
            0.2 * calc_roc(series, 126) +
            0.2 * calc_roc(series, 189) +
            0.2 * calc_roc(series, 252))

# ÖNBELLEKLEME EKLENDİ (TTL: 86400 saniye = 1 Gün). Veriler 1 gün boyunca API'ye gitmeden hafızadan okunur.
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    pe_val = np.nan
    sector = "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 1. YFINANCE (Yahoo)
    try:
        ticker_obj = yf.Ticker(sym)
        info = ticker_obj.info
        
        sector = info.get('sector', info.get('industry', 'Bilinmiyor'))
        
        if is_bist:
            pe_val = info.get('trailingPE', info.get('forwardPE', np.nan))
        else:
            pe_val = info.get('forwardPE', info.get('trailingPE', np.nan))
            
        if pd.notna(pe_val) and pe_val > 0 and sector != "Bilinmiyor":
            return pe_val, sector, f"✅ {sym}: Veri Yahoo'dan çekildi.", "success"
    except Exception:
        pass # Hata mesajını Finviz denemesinden sonraya bırakıyoruz

    # 2. FINVIZ (Yedek Motor)
    if is_bist:
        return np.nan, sector, f"⚠️ {sym}: BIST hissesi için Yahoo eksik veri gönderdi.", "warning"
        
    try:
        url = f"https://finviz.com/quote.ashx?t={sym}"
        res = requests.get(url, headers=headers, timeout=5)
        
        if sector == "Bilinmiyor":
            match_sec = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
            if match_sec:
                sector = match_sec.group(1)
        
        if np.isnan(pe_val):
            match_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            match_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            
            if match_fwd and match_fwd.group(1) != '-':
                pe_val = float(match_fwd.group(1))
            elif match_pe and match_pe.group(1) != '-':
                pe_val = float(match_pe.group(1))
        
        if sector != "Bilinmiyor" or not np.isnan(pe_val):
            return pe_val, sector, f"🔄 {sym}: Eksikler FINVIZ üzerinden kurtarıldı.", "success"
        else:
            return pe_val, sector, f"❌ {sym}: Veri bulunamadı.", "error"
            
    except Exception:
        return pe_val, sector, f"❌ {sym}: Finviz bağlantı hatası.", "error"


# --- VERİ ÇEKME VE İŞLEME ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = [] 
    
    with st.spinner("1/2: Fiyat verileri indiriliyor (Teknik Analiz)..."):
        all_tickers = tickers + [bench_ticker, dxy_ticker]
        data = yf.download(all_tickers, period="4y", interval="1d")["Close"]
        data = data.ffill().dropna(subset=[bench_ticker])
        
        p_index = data[bench_ticker]
        p_curr = data[dxy_ticker]
        
        adj_bench_series = pd.Series(np.where(p_curr > 0, p_index / p_curr, p_index), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench_series)
        index_ret = calc_roc(p_index, 1)

    with st.spinner("2/2: Temel veriler (F/K ve Sektör) çekiliyor (Önbellekli Sistem)..."):
        progress_bar = st.progress(0)
        fundamental_data = {}
        
        for i, sym in enumerate(tickers):
            pe, sec, log_msg, log_type = fetch_fundamental_data(sym, bist_mode)
            fundamental_data[sym] = {"pe": pe, "sector": sec}
            
            # Logları arayüz için topluyoruz
            if log_type == "success":
                debug_logs.append(log_msg)
            elif log_type == "warning":
                debug_logs.append(log_msg)
            else:
                debug_logs.append(log_msg)
                
            progress_bar.progress((i + 1) / len(tickers))
        
        progress_bar.empty()

    with st.spinner("Isı Haritası Oluşturuluyor..."):
        results = []
        valid_pes = [d["pe"] for d in fundamental_data.values() if not np.isnan(d["pe"])]
        avg_basket_pe = np.median(valid_pes) if valid_pes else 10.0
        
        for sym in tickers:
            if sym not in data.columns or data[sym].isnull().all():
                continue
                
            p_close = data[sym]
            
            # --- IPO FİLTRESİ ---
            valid_days = p_close.dropna().count()
            is_ipo = valid_days < lookback
            
            if is_ipo:
                debug_logs.append(f"⚠️ {sym}: {valid_days} günlük veri var. Kriter altı olduğu için IPO işaretlendi.")
            
            stock_rs = calc_weighted_rs(p_close)
            
            diff = (stock_rs - bench_rs).tail(lookback)
            navy_area = diff[diff > 0].sum()
            fuchsia_area = abs(diff[diff <= 0].sum())
            rs_ratio = navy_area / (0.0001 if fuchsia_area == 0 else fuchsia_area)
            
            stock_ret = calc_roc(p_close, 1).tail(252)
            index_ret_252 = index_ret.tail(252)
            corr = stock_ret.corr(index_ret_252)
            
            beta = (corr * (stock_ret.std() / index_ret_252.std())) if index_ret_252.std() > 0 else 1.0
            beta_adj_score = rs_ratio / (0.1 if beta <= 0.1 else beta)
            ideal_score = (rs_ratio + beta_adj_score) / 2.0
            
            f_info = fundamental_data.get(sym, {"pe": np.nan, "sector": "Bilinmiyor"})
            pe_val = f_info["pe"]
            sector_val = f_info["sector"]
            
            # Eğer IPO ise Ucuzluk Skoruna gizli bir -999 atıyoruz (Formatta yakalamak için)
            if is_ipo:
                cheapness_ratio = -999 
            else:
                cheapness_ratio = pe_val / avg_basket_pe if not np.isnan(pe_val) else np.nan
            
            display_sym = sym.replace(".IS", "") if bist_mode else sym
            
            results.append({
                "Hisse": display_sym,
                "Sektör": sector_val,
                "Saf Oran (P/N)": round(rs_ratio, 2),
                "Beta Skor": round(beta_adj_score, 2),
                "İdealite": round(ideal_score, 2),
                "F/K Değeri": round(pe_val, 2) if not np.isnan(pe_val) else np.nan,
                "Ucuzluk Skoru (x)": cheapness_ratio
            })

        if results:
            df_results = pd.DataFrame(results)
            st.markdown(f"**Sepet Medyan F/K:** `{round(avg_basket_pe, 2)}` *(Referans değer)*")
            
            df_sorted = df_results.sort_values(by="İdealite", ascending=False).reset_index(drop=True)
            
            # Lambda ile -999'u yakalayıp "IPO" yazdırıyoruz, aksi halde sadece skoru yazıyoruz
            styled_df = df_sorted.style.background_gradient(
                cmap='RdYlGn_r', 
                subset=['Ucuzluk Skoru (x)'], 
                vmin=0.5, 
                vmax=2.0  
            ).format({
                "Ucuzluk Skoru (x)": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok"),
                "F/K Değeri": "{:.2f}"
            }, na_rep="Veri Yok")
            
            st.dataframe(styled_df, use_container_width=True, height=1150)
            
            st.markdown("---")
            with st.expander("🛠️ Hata Ayıklama Konsolu (Tıkla Aç)"):
                for log in debug_logs:
                    if "✅" in log or "🔄" in log:
                        st.success(log)
                    elif "⚠️" in log:
                        st.warning(log)
                    else:
                        st.error(log)
        else:
            st.error("Veri işlenemedi. Lütfen sembolleri kontrol edin.")
