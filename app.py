import streamlit as st
import yfinance as yf
from yahooquery import Ticker as YQTicker
import pandas as pd
import numpy as np
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import google.generativeai as genai
from PIL import Image
from datetime import datetime

# --- 1. SAYFA AYARLARI VE GÜVENLİK ---
st.set_page_config(page_title="Alpha-Hunt Motoru", layout="wide", initial_sidebar_state="expanded")

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔒 Kilitli Ekran")
        pwd = st.text_input("Uygulama Şifresi", type="password")
        if st.button("Giriş Yap"):
            if "APP_PASSWORD" in st.secrets and pwd == st.secrets["APP_PASSWORD"]:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Hatalı şifre!")
        st.stop()

check_password()

st.title("🦅 Alpha-Hunt: Çift Katmanlı Değerleme & RS Motoru")
st.info(f"⏱️ **Sistem Hazır.** | 🖥️ Son Güncelleme: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- 2. HAYALET OTURUM (STEALTH SESSION) VE KORUMALAR ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
]

def get_stealth_session():
    session = requests.Session()
    # 429 veya 500'lü hatalarda 3 kez tekrar dener, aralarda bekler
    retry = Retry(connect=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

if "http_session" not in st.session_state:
    st.session_state.http_session = get_stealth_session()

# --- 3. GİRDİLER VE GEMINI YZ YAPISI ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 BIST Modu", value=False)

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = "THYAO, TUPRS, KCHOL, EREGL" if bist_mode else "AAPL, MSFT, NVDA, AVGO, META, TSLA, CVNA, PLTR, SHOP, HOOD"

uploaded_file = st.sidebar.file_uploader("Resim Yükle", type=["png", "jpg", "jpeg"])
if uploaded_file and "GEMINI_API_KEY" in st.secrets:
    if st.sidebar.button("✨ Resmi Oku"):
        with st.spinner("Yapay Zeka resmi inceliyor..."):
            try:
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(["Tickerları virgülle ver. Başka hiçbir kelime yazma.", Image.open(uploaded_file)])
                st.session_state.current_tickers = response.text.strip()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"YZ Bağlantı Hatası: {e}")

tickers_input = st.sidebar.text_area("Hisseler", st.session_state.current_tickers, height=150)
bench_ticker = st.sidebar.text_input("Endeks", "XU100.IS" if bist_mode else "^GSPC")
dxy_ticker = st.sidebar.text_input("DXY/Kur", "TRY=X" if bist_mode else "DX-Y.NYB")
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers]
tickers = list(dict.fromkeys(tickers)) # Çift yazılanları temizle

# --- 4. ÇAPRAZ KONTROLLÜ VERİ MOTORU ---
@st.cache_data(ttl=3600)
def get_prices(ticks): 
    return yf.download(ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400)
def get_advanced_fundamentals(sym, is_bist):
    sec = "Bilinmiyor"
    f_pe, ps, peg, roe = np.nan, np.nan, np.nan, np.nan
    
    # Adım 1: Yfinance & YahooQuery
    try:
        yq_info = YQTicker(sym).summary_detail.get(sym, {})
        if isinstance(yq_info, dict):
            f_pe = yq_info.get('forwardPE', np.nan)
        
        info = yf.Ticker(sym).info
        sec = info.get('sector', 'Bilinmiyor')
        if pd.isna(f_pe): f_pe = info.get('forwardPE', np.nan)
        ps = info.get('priceToSalesTrailing12Months', np.nan)
        peg = info.get('pegRatio', np.nan)
        roe = info.get('returnOnEquity', np.nan)
        if pd.notna(roe): roe = roe * 100 
    except: pass

    # Adım 2: Finviz Fallback (Hayalet Modu ile sadece ABD Hisseleri)
    if not is_bist and (pd.isna(ps) or pd.isna(peg) or pd.isna(roe) or pd.isna(f_pe)):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            }
            res = st.session_state.http_session.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=10)
            
            if res.status_code == 200:
                if pd.isna(f_pe):
                    m = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
                    if m and m.group(1) != '-': f_pe = float(m.group(1))
                if pd.isna(ps):
                    m = re.search(r'P/S.*?<b>(.*?)</b>', res.text)
                    if m and m.group(1) != '-': ps = float(m.group(1))
                if pd.isna(peg):
                    m = re.search(r'PEG.*?<b>(.*?)</b>', res.text)
                    if m and m.group(1) != '-': peg = float(m.group(1))
                if pd.isna(roe):
                    m = re.search(r'ROE.*?<b>(.*?)[%]</b>', res.text)
                    if m and m.group(1) != '-': roe = float(m.group(1))
        except: pass

    # Anlamsız/Hatalı verileri temizle
    if pd.notna(f_pe) and (f_pe <= 0 or f_pe > 900): f_pe = np.nan
    if pd.notna(ps) and (ps <= 0 or ps > 500): ps = np.nan
    
    return f_pe, ps, peg, roe, sec

def calculate_alpha_score(ps, peg, roe):
    # P/S Puanı (%40)
    p_ps = 0
    if pd.notna(ps):
        p_ps = 100 if ps < 1.5 else (80 if ps < 3 else (50 if ps < 6 else 20))
    # PEG Puanı (%30)
    p_peg = 0
    if pd.notna(peg):
        p_peg = 100 if peg < 1 else (75 if peg < 1.5 else (40 if peg < 2.5 else 10))
    # ROE Puanı (%30)
    p_roe = 0
    if pd.notna(roe):
        p_roe = 100 if roe > 25 else (80 if roe > 15 else (50 if roe > 5 else 0))
        
    score = (p_ps * 0.4) + (p_peg * 0.3) + (p_roe * 0.3)
    return score if (pd.notna(ps) or pd.notna(peg) or pd.notna(roe)) else np.nan

# --- 5. ANALİZ DÖNGÜSÜ (CHUNKING & BEKLEME) ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    with st.spinner("Piyasa fiyatlamaları indiriliyor..."):
        data = get_prices(tickers + [bench_ticker, dxy_ticker]).ffill().dropna(subset=[bench_ticker])
        p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
    
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(tickers)
    for i, s in enumerate(tickers):
        status_text.text(f"Analiz ediliyor: {s} ({i+1}/{total})")
        
        f_pe, ps, peg, roe, sec = get_advanced_fundamentals(s, bist_mode)
        alpha = calculate_alpha_score(ps, peg, roe)
        
        # Dinamik Ban Koruması
        time.sleep(random.uniform(1.0, 2.5))
        if (i + 1) % 15 == 0:
            status_text.text("Sunucular soğutuluyor... (15 hisse tamamlandı)")
            time.sleep(5.0)
        
        if s in data.columns:
            p_close = data[s].dropna()
            if len(p_close) > 63:
                rs = (p_close.pct_change(63).tail(lookback).sum()) 
                beta = p_close.pct_change().corr(p_idx.pct_change())
                ideal = rs / max(0.1, beta)
                hist_chp = p_close.iloc[-1] / p_close.tail(lookback).mean() if len(p_close) >= lookback else -999
            else:
                rs, beta, ideal, hist_chp = 0, 1, 0, -999
        else:
            ideal, hist_chp = 0, -999

        results.append({
            "Hisse": s.replace(".IS", ""), "Sektör": sec, "İdealite (RS Rank)": ideal,
            "Teknik Ucuzluk": hist_chp, "Alpha Puanı": alpha, "Güncel P/S": ps,
            "Fwd PEG": peg, "ROE (%)": roe, "İleri F/K": f_pe
        })
        progress_bar.progress((i + 1) / total)
    
    status_text.empty()
    progress_bar.empty()

    # --- 6. GÖRSELLEŞTİRME VE TABLOLAR ---
    # İdealite'ye (RS Rank) göre diz, her iki tablonun satır paritesini koru
    df_master = pd.DataFrame(results).sort_values("İdealite (RS Rank)", ascending=False).reset_index(drop=True)
    df_master.index += 1
    
    df_alpha = df_master[["Hisse", "Alpha Puanı", "Güncel P/S", "Fwd PEG", "ROE (%)", "İleri F/K"]]
    df_momentum = df_master[["Hisse", "Sektör", "İdealite (RS Rank)", "Teknik Ucuzluk"]]

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🌟 Tablo 2: Alpha Puanı & Temel Değerler")
        styled_alpha = (df_alpha.style
                        .set_properties(**{'text-align': 'left'})
                        .background_gradient(cmap='Greens', subset=['Alpha Puanı'], vmin=0, vmax=100)
                        .background_gradient(cmap='RdYlGn_r', subset=['Güncel P/S'], vmin=1, vmax=8)
                        .background_gradient(cmap='RdYlGn_r', subset=['Fwd PEG'], vmin=0.5, vmax=3.0)
                        .background_gradient(cmap='RdYlGn', subset=['ROE (%)'], vmin=-10, vmax=40)
                        .format({
                            "Alpha Puanı": "{:.0f}", "Güncel P/S": "{:.2f}x", "Fwd PEG": "{:.2f}",
                            "ROE (%)": "{:.1f}%", "İleri F/K": "{:.1f}"
                        }, na_rep="Veri Yok"))
        # Dinamik yükseklik: height parametresi silindi
        st.dataframe(styled_alpha, use_container_width=True)

    with col2:
        st.subheader("🔥 Tablo 1: İdealite & Teknik (RS Rank)")
        styled_momentum = (df_momentum.style
                           .set_properties(**{'text-align': 'left'})
                           .background_gradient(cmap='RdYlGn_r', subset=['Teknik Ucuzluk'], vmin=0.7, vmax=1.3)
                           .format({
                               "İdealite (RS Rank)": "{:.2f}",
                               "Teknik Ucuzluk": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
                           }, na_rep="Veri Yok"))
        st.dataframe(styled_momentum, use_container_width=True)

    # --- 7. ÇIKTILAR ---
    st.divider()
    prefix = "BIST:" if bist_mode else "NASDAQ:"
    c3, c4 = st.columns(2)
    with c3:
        st.success("**TV Takip Listesi (Tümü)**")
        st.code(",".join([f"{prefix}{sym}" for sym in df_master["Hisse"].tolist()]), language="text")
    with c4:
        st.info("**TV Isı Haritası Girdisi (İlk 38)**")
        st.code(" \n".join([f"{i+1}. {sym}" for i, sym in enumerate(df_master["Hisse"].head(38))]), language="text")
