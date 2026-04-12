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
st.title("🔥 İdealite ve F/K Isı Haritası (Yapay Zeka Destekli)")
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

# Şifreyi Streamlit kasasından al, yoksa kutu göster
if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 Gemini API Anahtarı gizli kasadan güvenle yüklendi!")
else:
    gemini_api_key = st.sidebar.text_input("Gemini API Anahtarı (Zorunlu)", type="password", help="aistudio.google.com adresinden ücretsiz alabilirsiniz.")

uploaded_file = st.sidebar.file_uploader("Hisse Listesi Resmi Yükle", type=["png", "jpg", "jpeg"])

# Otomatik doldurma için hafıza (Session State) ayarı
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
                
                # Gemini'nin bulduğu hisseleri kutuya yazdırıyoruz
                st.session_state.current_tickers = response.text.strip()
                st.sidebar.success("Hisseler başarıyla çekildi! Aşağıdan analizi başlatabilirsiniz.")
            except Exception as e:
                st.sidebar.error(f"Yapay Zeka Hatası: Lütfen API anahtarınızı kontrol edin. ({str(e)[:40]})")

st.sidebar.markdown("---")

# Hisselerin girildiği ana kutu
tickers_input = st.sidebar.text_area("Hisse Sembolleri (Virgülle ayırın, Maks 100)", st.session_state.current_tickers, height=150)

bench_ticker = st.sidebar.text_input("Piyasa Endeksi", default_bench)
dxy_ticker = st.sidebar.text_input("Kur/Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("Alan Oranı Geriye Bakış (Gün)", value=500)

# Sembolleri temizle ve BIST modu açıksa .IS ekle
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

def get_pe_data(sym, debug_logs, is_bist):
    pe_val = np.nan
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 1. YFINANCE (Yahoo)
    try:
        session = requests.Session()
        session.headers.update(headers)
        info = yf.Ticker(sym, session=session).info
        
        if is_bist:
            pe_val = info.get('trailingPE', info.get('forwardPE', np.nan))
        else:
            pe_val = info.get('forwardPE', info.get('trailingPE', np.nan))
            
        if pd.notna(pe_val) and pe_val > 0:
            debug_logs.append(f"✅ {sym}: Veri Yahoo'dan çekildi ({pe_val:.2f}).")
            return pe_val
        else:
            debug_logs.append(f"⚠️ {sym}: Yahoo veriyi boş gönderdi.")
    except Exception as e:
        debug_logs.append(f"❌ {sym}: Yahoo hatası.")

    # 2. FINVIZ
    if is_bist:
        return np.nan
        
    debug_logs.append(f"🔄 {sym}: Finviz yedek motoru devreye giriyor...")
    try:
        url = f"https://finviz.com/quote.ashx?t={sym}"
        res = requests.get(url, headers=headers, timeout=5)
        match_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
        match_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
        
        if match_fwd and match_fwd.group(1) != '-':
            pe_val = float(match_fwd.group(1))
            debug_logs.append(f"✅ {sym}: Veri FINVIZ'den kurtarıldı ({pe_val}).")
            return pe_val
        elif match_pe and match_pe.group(1) != '-':
            pe_val = float(match_pe.group(1))
            debug_logs.append(f"✅ {sym}: Veri FINVIZ'den kurtarıldı ({pe_val}).")
            return pe_val
    except Exception as e:
        debug_logs.append(f"❌ {sym}: Finviz başarısız.")
        
    return np.nan

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

    with st.spinner("2/2: Temel veriler (F/K) çekiliyor..."):
        progress_bar = st.progress(0)
        fundamental_data = {}
        
        for i, sym in enumerate(tickers):
            fundamental_data[sym] = get_pe_data(sym, debug_logs, bist_mode)
            time.sleep(0.3) 
            progress_bar.progress((i + 1) / len(tickers))
        
        progress_bar.empty()

    with st.spinner("Isı Haritası Oluşturuluyor..."):
        results = []
        valid_pes = [v for v in fundamental_data.values() if not np.isnan(v)]
        avg_basket_pe = np.median(valid_pes) if valid_pes else 10.0
        
        for sym in tickers:
            if sym not in data.columns or data[sym].isnull().all():
                continue
                
            p_close = data[sym]
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
            
            pe_val = fundamental_data.get(sym, np.nan)
            cheapness_ratio = pe_val / avg_basket_pe if not np.isnan(pe_val) else np.nan
            
            display_sym = sym.replace(".IS", "") if bist_mode else sym
            
            results.append({
                "Hisse": display_sym,
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
            
            styled_df = df_sorted.style.background_gradient(
                cmap='RdYlGn_r', 
                subset=['Ucuzluk Skoru (x)'], 
                vmin=0.5, 
                vmax=2.0  
            ).format({
                "Ucuzluk Skoru (x)": "{:.2f}",
                "F/K Değeri": "{:.2f}"
            }, na_rep="Veri Yok")
            
            st.dataframe(styled_df, use_container_width=True, height=600)
            
            st.markdown("---")
            with st.expander("🛠️ Hata Ayıklama Konsolu (Tıkla Aç)"):
                for log in debug_logs:
                    if "✅" in log:
                        st.success(log)
                    elif "⚠️" in log or "🔄" in log:
                        st.warning(log)
                    else:
                        st.error(log)
        else:
            st.error("Veri işlenemedi. Lütfen sembolleri kontrol edin.")
