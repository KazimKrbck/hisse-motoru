import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re
import google.generativeai as genai
from PIL import Image
from datetime import datetime

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Alpha-Hunt Motoru", layout="wide")

# --- GÜVENLİK / ŞİFRE EKRANI ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if not st.session_state["authenticated"]:
        st.title("🔒 Kilitli Ekran")
        st.warning("Bu uygulama Kâzım Karabacak'a aittir. Lütfen giriş yapın.")
        pwd = st.text_input("Uygulama Şifresi", type="password")
        if st.button("Giriş Yap"):
            if "APP_PASSWORD" in st.secrets and pwd == st.secrets["APP_PASSWORD"]:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Hatalı şifre!")
        st.stop()

check_password()

# --- BAŞLIK ---
st.title("Alpha-Hunt: Tarihsel & Güncel Ucuzluk Motoru [KazimKrbck]")
st.markdown("Analiz: **RsRank İdealite** + **Güncel F/K** + **Tarihsel Fiyat Ucuzluğu** (Fiyat/500G Ort).")

# --- PARAMETRELER ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

if bist_mode:
    default_tickers = "THYAO, TUPRS, KCHOL, EREGL, FROTO, SISE, BIMAS, ASELS"
    default_bench = "XU100.IS"
    default_dxy = "TRY=X" 
else:
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AMD, NFLX, AVGO"
    default_bench = "^GSPC"
    default_dxy = "DX-Y.NYB"

# Gemini Görüntü Okuma
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
uploaded_file = st.sidebar.file_uploader("Hisse Listesi Resmi Yükle", type=["png", "jpg", "jpeg"])

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = default_tickers

if uploaded_file and st.sidebar.button("✨ Resmi Oku"):
    with st.spinner("Gemini inceliyor..."):
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            img = Image.open(uploaded_file)
            prompt = "Resimdeki tickerları bul. SADECE büyük harflerle, virgülle ayrılmış liste ver. Örn: AAPL, MSFT"
            response = model.generate_content([prompt, img])
            st.session_state.current_tickers = response.text.strip()
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Hata: {str(e)[:40]}")

st.sidebar.markdown("---")
tickers_input = st.sidebar.text_area("Hisse Sembolleri", st.session_state.current_tickers, height=120)
bench_ticker = st.sidebar.text_input("Endeks", default_bench)
dxy_ticker = st.sidebar.text_input("Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("LookBack (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers][:100]

# --- FONKSİYONLAR VE CACHE ---
def calc_roc(series, periods):
    return series.pct_change(periods=periods) * 100

def calc_weighted_rs(series):
    return (0.4 * calc_roc(series, 63) + 0.2 * calc_roc(series, 126) + 
            0.2 * calc_roc(series, 189) + 0.2 * calc_roc(series, 252))

@st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
def fetch_price_data(all_ticks):
    return yf.download(all_ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400, max_entries=150, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    pe_val, sector = np.nan, "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        t_obj = yf.Ticker(sym)
        info = t_obj.info
        sector = info.get('sector', info.get('industry', 'Bilinmiyor'))
        pe_val = info.get('trailingPE', info.get('forwardPE', np.nan)) if is_bist else info.get('forwardPE', info.get('trailingPE', np.nan))
        if pd.notna(pe_val) and pe_val > 0:
            return pe_val, sector, f"✅ {sym}: Yahoo OK", "success"
    except: pass
    if not is_bist:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=5)
            if sector == "Bilinmiyor":
                m = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
                if m: sector = m.group(1)
            m_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            if m_fwd and m_fwd.group(1) != '-': pe_val = float(m_fwd.group(1))
            if sector != "Bilinmiyor" or pd.notna(pe_val):
                return pe_val, sector, f"🔄 {sym}: Finviz OK", "success"
        except: pass
    return pe_val, sector, f"❌ {sym}: Veri Yok", "error"

# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = []
    with st.spinner("Fiyatlar indiriliyor..."):
        all_to_fetch = tickers + [bench_ticker, dxy_ticker]
        data = fetch_price_data(all_to_fetch).ffill().dropna(subset=[bench_ticker])
        p_idx, p_dxy = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_dxy > 0, p_idx / p_dxy, p_idx), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench)
        idx_ret = p_idx.pct_change()

    with st.spinner("Temel veriler çekiliyor..."):
        f_data = {}
        for s in tickers:
            pe, sec, msg, tp = fetch_fundamental_data(s, bist_mode)
            f_data[s] = {"pe": pe, "sec": sec}
            debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            time.sleep(0.1)

    with st.spinner("Sonuçlar hesaplanıyor..."):
        results = []
        for s in tickers:
            if s not in data.columns or data[s].isnull().all(): continue
            inf = f_data.get(s, {"pe": np.nan, "sec": "Bilinmiyor"})
            p_close = data[s]
            is_ipo = p_close.dropna().count() < lookback
            
            # İDEALİTE
            stk_rs = calc_weighted_rs(p_close)
            diff = (stk_rs - bench_rs).tail(lookback)
            rs_ratio = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            ret, iret = p_close.pct_change().tail(252), idx_ret.tail(252)
            beta = (ret.corr(iret) * (ret.std() / iret.std())) if iret.std() > 0 else 1.0
            ideal = (rs_ratio + (rs_ratio / max(0.1, beta))) / 2.0
            
            # TARİHSEL UCUZLUK (Fiyat / 500G Ortalama)
            if is_ipo:
                hist_chp = -999
            else:
                curr_price = p_close.dropna().iloc[-1]
                hist_avg = p_close.dropna().tail(lookback).mean()
                hist_chp = curr_price / hist_avg
            
            results.append({
                "Hisse": s.replace(".IS", ""), "Sektör": inf["sec"],
                "Saf Oran": rs_ratio, "Beta": beta, "İdealite": ideal,
                "Güncel F/K": inf["pe"],
                "Tarihsel Ucuzluk": hist_chp
            })

    if results:
        df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.dataframe(df.style.background_gradient(cmap='RdYlGn_r', subset=['Tarihsel Ucuzluk'], vmin=0.7, vmax=1.3).format({
            "Saf Oran": "{:.2f}", "Beta": "{:.2f}", "İdealite": "{:.2f}",
            "Güncel F/K": lambda x: f"{x:.2f}" if pd.notna(x) else "-",
            "Tarihsel Ucuzluk": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
        }, na_rep="Veri Yok"), use_container_width=True, height=800)
        with st.expander("Loglar"):
            for l in debug_logs: st.write(l)
