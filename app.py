import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Hisse Sıralama Motoru", layout="wide")
st.title("🔥 İdealite ve F/K Isı Haritası")
st.markdown("Likidite ayarlı teknik metrikler ve normalize edilmiş F/K haritası.")

# --- GİRDİLER ---
st.sidebar.header("Parametreler")
tickers_input = st.sidebar.text_area("Hisse Sembolleri (Virgülle ayırın, Maks 100)", "AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, INTC, AMD, NFLX")
bench_ticker = st.sidebar.text_input("Piyasa Endeksi", "^GSPC")
dxy_ticker = st.sidebar.text_input("Kur/Likidite (DXY)", "DX-Y.NYB")
lookback = st.sidebar.number_input("Alan Oranı Geriye Bakış (Gün)", value=500)

# Sembolleri temizle ve max 100 ile sınırla
tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
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

# --- VERİ ÇEKME VE İŞLEME ---
if st.sidebar.button("Analizi Başlat"):
    with st.spinner("1/2: Fiyat verileri indiriliyor (Geçmiş 4 Yıl)..."):
        all_tickers = tickers + [bench_ticker, dxy_ticker]
        
        # TradingView mantığı: Sadece "Close" kullan ve tatil boşluklarını doldur
        data = yf.download(all_tickers, period="4y", interval="1d")["Close"]
        data = data.ffill().dropna(subset=[bench_ticker])
        
        p_index = data[bench_ticker]
        p_curr = data[dxy_ticker]
        adj_bench_series = pd.Series(np.where(p_curr > 0, p_index / p_curr, p_index), index=data.index)
        
        bench_rs = calc_weighted_rs(adj_bench_series)
        index_ret = calc_roc(p_index, 1)

    with st.spinner("2/2: Temel veriler (F/K) çekiliyor... (Lütfen bekleyin)"):
        progress_bar = st.progress(0)
        fundamental_data = {}
        
        for i, sym in enumerate(tickers):
            try:
                info = yf.Ticker(sym).info
                # 1. Önce İleriye Dönük F/K dene, yoksa Geçmiş F/K al (B Planı)
                pe_val = info.get('forwardPE', info.get('trailingPE', np.nan))
                
                # Negatif F/K (Zarar eden şirket) temizle
                if pe_val is not None and pe_val > 0:
                    fundamental_data[sym] = pe_val
                else:
                    fundamental_data[sym] = np.nan
            except:
                fundamental_data[sym] = np.nan
                
            # Yahoo bizi bot sanmasın diye yarım saniye mola
            time.sleep(0.5) 
            progress_bar.progress((i + 1) / len(tickers))
        
        progress_bar.empty()

    with st.spinner("Isı Haritası Oluşturuluyor..."):
        results = []
        
        # Sepet F/K Ortalamasını Hesapla
        valid_pes = [v for v in fundamental_data.values() if not np.isnan(v)]
        avg_basket_pe = np.median(valid_pes) if valid_pes else 15.0
        
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
            
            # Ucuzluk Oranı = Hisse F/K'sı / Sepet Medyan F/K'sı
            cheapness_ratio = pe_val / avg_basket_pe if not np.isnan(pe_val) else np.nan
            
            results.append({
                "Hisse": sym,
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
        else:
            st.error("Veri işlenemedi. Lütfen sembolleri kontrol edin.")
