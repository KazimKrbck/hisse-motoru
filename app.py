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
st.title("Hisseler için RsRank bazlı İdealite ve LookBack Ortalama Fiyat/Kazanç bazlı Ucuzluk Isı Haritası       [KazimKrbck]")
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

# Şifreyi Streamlit kasasından al, yoksa manuel giriş kutusu göster
if "GEMINI_API_KEY" in st.secrets:
    gemini_api_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("🔑 Gemini API Anahtarı gizli kasadan yüklendi!")
else:
    gemini_api_key = st.sidebar.text_input("Gemini API Anahtarı (Zorunlu)", type="password")

uploaded_file = st.sidebar.file_uploader("Hisse Listesi Resmi Yükle", type=["png", "jpg", "jpeg"])

if "current_tickers" not in st.session_state:
    st.session_state.current_tickers = default_tickers

if uploaded_file is not None and gemini_api_key:
    if st.sidebar.button("✨ Resmi Oku ve Listeyi Doldur"):
        with st.spinner("Gemini resmi inceliyor..."):
            try:
                genai.configure(api_key=gemini_api_key)
                # En güncel model ismini kullanıyoruz
                model = genai.GenerativeModel('gemini-2.5-flash')
                img = Image.open(uploaded_file)

                prompt = "Resimdeki borsa sembollerini bul. Sadece büyük harflerle, aralarında virgül olan bir liste ver. Örn: AAPL, MSFT"
                response = model.generate_content([prompt, img])

                st.session_state.current_tickers = response.text.strip()
                st.sidebar.success("Hisseler başarıyla çekildi!")
            except Exception as e:
                st.sidebar.error(f"Hata: {str(e)[:50]}")

st.sidebar.markdown("---")

# Hisselerin girildiği ana kutu
tickers_input = st.sidebar.text_area("Hisse Sembolleri", st.session_state.current_tickers, height=150)
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

# --- HESAPLAMA VE MOTORLAR ---
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

    try:
        session = requests.Session()
        session.headers.update(headers)
        info = yf.Ticker(sym, session=session).info
        pe_val = info.get('trailingPE', info.get('forwardPE', np.nan)) if is_bist else info.get('forwardPE', info.get('trailingPE', np.nan))

        if pd.notna(pe_val) and pe_val > 0:
            debug_logs.append(f"✅ {sym}: Yahoo OK.")
            return pe_val
    except:
        pass

    if not is_bist: # ABD hissesiyse Finviz yedek motoru
        try:
            url = f"https://finviz.com/quote.ashx?t={sym}"
            res = requests.get(url, headers=headers, timeout=5)
            match = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text) or re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
            if match and match.group(1) != '-':
                pe_val = float(match.group(1))
                debug_logs.append(f"✅ {sym}: Finviz OK.")
                return pe_val
        except:
            pass
    return np.nan

# --- ANALİZ TETİKLEYİCİ ---
if st.sidebar.button("🚀 Analizi Başlat", type="primary"):
    debug_logs = [] 
    with st.spinner("Veriler işleniyor..."):
        all_tickers = tickers + [bench_ticker, dxy_ticker]
        data = yf.download(all_tickers, period="4y", interval="1d")["Close"]
        data = data.ffill().dropna(subset=[bench_ticker])

        p_index, p_curr = data[bench_ticker], data[dxy_ticker]
        adj_bench = pd.Series(np.where(p_curr > 0, p_index / p_curr, p_index), index=data.index)
        bench_rs = calc_weighted_rs(adj_bench)
        index_ret = calc_roc(p_index, 1)

        fundamental_data = {sym: get_pe_data(sym, debug_logs, bist_mode) for sym in tickers}

        results = []
        valid_pes = [v for v in fundamental_data.values() if not np.isnan(v)]
        avg_basket_pe = np.median(valid_pes) if valid_pes else 15.0

        for sym in tickers:
            if sym not in data.columns: continue
            p_close = data[sym]
            stock_rs = calc_weighted_rs(p_close)
            diff = (stock_rs - bench_rs).tail(lookback)
            rs_ratio = diff[diff > 0].sum() / (0.0001 if abs(diff[diff <= 0].sum()) == 0 else abs(diff[diff <= 0].sum()))

            stock_ret, index_ret_252 = calc_roc(p_close, 1).tail(252), index_ret.tail(252)
            beta = (stock_ret.corr(index_ret_252) * (stock_ret.std() / index_ret_252.std())) if index_ret_252.std() > 0 else 1.0
            beta_adj = rs_ratio / (0.1 if beta <= 0.1 else beta)

            pe_val = fundamental_data.get(sym, np.nan)
            results.append({
                "Hisse": sym.replace(".IS", "") if bist_mode else sym,
                "Saf Oran (P/N)": round(rs_ratio, 2),
                "Beta Skor": round(beta_adj, 2),
                "İdealite": round((rs_ratio + beta_adj) / 2.0, 2),
                "F/K Değeri": round(pe_val, 2) if not np.isnan(pe_val) else np.nan,
                "Ucuzluk Skoru (x)": pe_val / avg_basket_pe if not np.isnan(pe_val) else np.nan
            })

        if results:
            df = pd.DataFrame(results).sort_values(by="İdealite", ascending=False).reset_index(drop=True)
            st.markdown(f"**Sepet Medyan F/K:** `{round(avg_basket_pe, 2)}`")

            # --- TABLO ŞEKİLLENDİRME ---
            styled_df = df.style.background_gradient(cmap='RdYlGn_r', subset=['Ucuzluk Skoru (x)'], vmin=0.5, vmax=2.0)\
                .format({"Ucuzluk Skoru (x)": "{:.2f}", "F/K Değeri": "{:.2f}"}, na_rep="Veri Yok")\
                .set_properties(**{'text-align': 'left'})\
                .set_table_styles([{'selector': 'th', 'props': [('text-align', 'left')]}])

            st.dataframe(styled_df, use_container_width=False, height=600)
