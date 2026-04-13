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
st.set_page_config(page_title="Hisse Sıralama Motoru", layout="wide")

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
st.title("Alpha-Hunt: Çift Ucuzluk & RsRank Motoru [KazimKrbck]")
st.markdown("Analiz: **Temel Büyüme** (F/K Oranı) + **Teknik Ortalamaya Dönüş** (Fiyat/500G Ort).")

# --- PARAMETRELER ---
st.sidebar.header("Parametreler")
bist_mode = st.sidebar.checkbox("🇹🇷 Borsa İstanbul (BIST) Modu", value=False)

if bist_mode:
    default_tickers = "THYAO, TUPRS, KCHOL, EREGL, FROTO, SISE, BIMAS, ASELS"
    default_bench = "XU100.IS"
    default_dxy = "TRY=X" 
else:
    default_tickers = "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, AMD"
    default_bench = "^GSPC"
    default_dxy = "DX-Y.NYB"

exclude_finance = st.sidebar.checkbox("Banka, Finans, Kripto, Kumar Hariç Tut", value=True)

# Gemini Bölümü
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
uploaded_file = st.sidebar.file_uploader("Resimden Hisse Çek", type=["png", "jpg", "jpeg"])
if "current_tickers" not in st.session_state: st.session_state.current_tickers = default_tickers

if uploaded_file and st.sidebar.button("✨ Resmi Oku"):
    img = Image.open(uploaded_file)
    model = genai.GenerativeModel('gemini-2.5-flash')
    resp = model.generate_content(["Sadece tickerları virgülle ver. Örn: AAPL, TSLA", img])
    st.session_state.current_tickers = resp.text.strip()
    st.rerun()

tickers_input = st.sidebar.text_area("Semboller", st.session_state.current_tickers, height=120)
bench_ticker = st.sidebar.text_input("Endeks", default_bench)
dxy_ticker = st.sidebar.text_input("Likidite (DXY)", default_dxy)
lookback = st.sidebar.number_input("Geriye Bakış (Gün)", value=500)

raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
tickers = [t + ".IS" if bist_mode and not t.endswith(".IS") else t for t in raw_tickers][:100]

# --- CACHE VE VERİ ÇEKME ---
@st.cache_data(ttl=3600, max_entries=2, show_spinner=False)
def fetch_price_data(all_ticks):
    return yf.download(all_ticks, period="4y", interval="1d", progress=False)["Close"]

@st.cache_data(ttl=86400, max_entries=150, show_spinner=False)
def fetch_fundamental_data(sym, is_bist):
    trail, fwd, sector = np.nan, np.nan, "Bilinmiyor"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        info = yf.Ticker(sym).info
        sector = info.get('sector', info.get('industry', 'Bilinmiyor'))
        trail, fwd = info.get('trailingPE', np.nan), info.get('forwardPE', np.nan)
        if pd.notna(trail) and (trail <= 0 or trail > 500): trail = np.nan
        if pd.notna(fwd) and (fwd <= 0 or fwd > 500): fwd = np.nan
        if (pd.notna(trail) or pd.notna(fwd)) and sector != "Bilinmiyor":
            return trail, fwd, sector, f"✅ {sym}: Yahoo OK", "success"
    except: pass
    if not is_bist:
        try:
            res = requests.get(f"https://finviz.com/quote.ashx?t={sym}", headers=headers, timeout=5)
            if sector == "Bilinmiyor":
                m = re.search(r'f=sec_[^>]+>([^<]+)</a>', res.text)
                if m: sector = m.group(1)
            m_p = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            m_f = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
            if m_p and m_p.group(1) != '-': trail = float(m_p.group(1))
            if m_f and m_f.group(1) != '-': fwd = float(m_f.group(1))
            return trail, fwd, sector, f"🔄 {sym}: Finviz OK", "success"
        except: pass
    return trail, fwd, sector, f"❌ {sym}: Veri Yok", "error"

# --- ANALİZ MOTORU ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = []
    with st.spinner("Veriler İndiriliyor..."):
        data = fetch_price_data(tickers + [bench_ticker, dxy_ticker]).ffill().dropna(subset=[bench_ticker])
        idx_ret = data[bench_ticker].pct_change()
        adj_bench = pd.Series(np.where(data[dxy_ticker] > 0, data[bench_ticker] / data[dxy_ticker], data[bench_ticker]), index=data.index)
        
        # RsRank (Bench)
        roc_adj = (0.4 * adj_bench.pct_change(63) + 0.2 * adj_bench.pct_change(126) + 
                   0.2 * adj_bench.pct_change(189) + 0.2 * adj_bench.pct_change(252)) * 100

        f_data = {}
        for s in tickers:
            t, f, sec, msg, tp = fetch_fundamental_data(s, bist_mode)
            f_data[s] = {"trail": t, "fwd": f, "sec": sec}
            debug_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            time.sleep(0.1)

    with st.spinner("Skorlar Hesaplanıyor..."):
        results = []
        bl = ["bank", "financial", "credit", "crypto", "gambling", "banka", "finans", "sigorta", "yatırım"]
        for s in tickers:
            if s not in data.columns or data[s].isnull().all(): continue
            inf = f_data.get(s, {"trail": np.nan, "fwd": np.nan, "sec": "Bilinmiyor"})
            if exclude_finance and any(b in inf["sec"].lower() for b in bl): continue

            # İdealite
            stk_roc = (0.4 * data[s].pct_change(63) + 0.2 * data[s].pct_change(126) + 
                       0.2 * data[s].pct_change(189) + 0.2 * data[s].pct_change(252)) * 100
            diff = (stk_roc - roc_adj).tail(lookback)
            rs = diff[diff > 0].sum() / (abs(diff[diff <= 0].sum()) if diff[diff <= 0].sum() != 0 else 0.0001)
            
            ret, iret = data[s].pct_change().tail(252), idx_ret.tail(252)
            beta = (ret.corr(iret) * (ret.std() / iret.std())) if iret.std() > 0 else 1.0
            ideal = (rs + (rs / max(0.1, beta))) / 2.0

            # Çift Ucuzluk
            t_pe, f_pe = inf["trail"], inf["fwd"]
            growth_chp = f_pe / t_pe if pd.notna(t_pe) and pd.notna(f_pe) and t_pe > 0 else np.nan
            hist_chp = data[s].iloc[-1] / data[s].tail(lookback).mean() if len(data[s]) >= lookback else -999

            results.append({
                "Hisse": s.replace(".IS", ""), "Sektör": inf["sec"], "Saf Oran": rs, "Beta": beta,
                "İdealite": ideal, "Geçmiş F/K": t_pe,
                "Temel Ucuzluk (Büyüme)": growth_chp, "Teknik Ucuzluk (Tarihsel)": hist_chp
            })

    if results:
        res_df = pd.DataFrame(results).sort_values("İdealite", ascending=False).reset_index(drop=True)
        st.dataframe(res_df.style.background_gradient(cmap='RdYlGn_r', subset=['Temel Ucuzluk (Büyüme)'], vmin=0.5, vmax=1.5)
                     .background_gradient(cmap='RdYlGn_r', subset=['Teknik Ucuzluk (Tarihsel)'], vmin=0.7, vmax=1.3).format({
            "Saf Oran": "{:.2f}", "Beta": "{:.2f}", "İdealite": "{:.2f}", "Geçmiş F/K": "{:.2f}",
            "Temel Ucuzluk (Büyüme)": "{:.2f}", 
            "Teknik Ucuzluk (Tarihsel)": lambda x: "IPO" if x == -999 else (f"{x:.2f}" if pd.notna(x) else "Veri Yok")
        }, na_rep="Veri Yok"), use_container_width=True, height=800)
        with st.expander("Loglar"):
            for l in debug_logs: st.write(l)
