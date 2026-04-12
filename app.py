import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import re

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

# FİNANSAL VERİ KAZIMA (SCRAPING) MOTORU
def get_pe_data(sym, debug_logs):
    """Önce Yahoo'yu dener, başarısız olursa Finviz'den kazır."""
    pe_val = np.nan
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 1. DENEME: YFINANCE (Yahoo)
    try:
        info = yf.Ticker(sym).info
        pe_val = info.get('forwardPE', info.get('trailingPE', np.nan))
        if pd.notna(pe_val) and pe_val > 0:
            debug_logs.append(f"✅ {sym}: Veri Yahoo'dan başarıyla çekildi ({pe_val}).")
            return pe_val
        else:
            debug_logs.append(f"⚠️ {sym}: Yahoo veriyi boş (None) veya negatif gönderdi.")
    except Exception as e:
        debug_logs.append(f"❌ {sym}: Yahoo bağlantı hatası -> {str(e)[:50]}")

    # 2. DENEME: FINVIZ (Yedek Motor)
    debug_logs.append(f"🔄 {sym}: Finviz yedek motoru devreye giriyor...")
    try:
        url = f"https://finviz.com/quote.ashx?t={sym}"
        res = requests.get(url, headers=headers, timeout=5)
        
        # Sitenin kaynak kodundan F/K satırını bulma
        match_fwd = re.search(r'Forward P/E.*?<b>(.*?)</b>', res.text)
        match_pe = re.search(r'>P/E<.*?<b>(.*?)</b>', res.text)
        
        if match_fwd and match_fwd.group(1) != '-':
            pe_val = float(match_fwd.group(1))
            debug_logs.append(f"✅ {sym}: Veri FINVIZ'den (Forward P/E) kurtarıldı ({pe_val}).")
            return pe_val
        elif match_pe and match_pe.group(1) != '-':
            pe_val = float(match_pe.group(1))
            debug_logs.append(f"✅ {sym}: Veri FINVIZ'den (Standart P/E) kurtarıldı ({pe_val}).")
            return pe_val
        else:
            debug_logs.append(f"❌ {sym}: Finviz'de de F/K verisi bulunamadı (Şirket zararda olabilir).")
    except Exception as e:
        debug_logs.append(f"❌ {sym}: Finviz motoru da başarısız oldu -> {str(e)[:50]}")
        
    return np.nan

# --- VERİ ÇEKME VE İŞLEME ---
if st.sidebar.button("Analizi Başlat"):
    debug_logs = [] # Hata kayıtlarını tutacağımız liste
    
    with st.spinner("1/2: Fiyat verileri indiriliyor (Teknik Analiz)..."):
        all_tickers = tickers + [bench_ticker, dxy_ticker]
        data = yf.download(all_tickers, period="4y", interval="1d")["Close"]
        data = data.ffill().dropna(subset=[bench_ticker])
        
        p_index = data[bench_ticker]
        p_curr = data[dxy_ticker]
        adj_bench_series = pd.Series(np.where(p_curr > 0, p_index / p_curr, p_index), index=data.index)
        
        bench_rs = calc_weighted_rs(adj_bench_series)
        index_ret = calc_roc(p_index, 1)

    with st.spinner("2/2: Temel veriler Çift Motorlu Sistemle (Yahoo + Finviz) çekiliyor..."):
        progress_bar = st.progress(0)
        fundamental_data = {}
        
        for i, sym in enumerate(tickers):
            # Çift motorlu fonksiyonumuzu çağırıyoruz
            fundamental_data[sym] = get_pe_data(sym, debug_logs)
            
            time.sleep(0.3) # Sunucuları yormamak için kısa bekleme
            progress_bar.progress((i + 1) / len(tickers))
        
        progress_bar.empty()

    with st.spinner("Isı Haritası Oluşturuluyor..."):
        results = []
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
            
            # --- DEBUG (HATA AYIKLAMA) BÖLÜMÜ ---
            st.markdown("---")
            with st.expander("🛠️ Hata Ayıklama (Debug) Konsolu - F/K Neden 'None' Çıkıyor? (Tıkla Aç)"):
                st.write("Aşağıda sistemin arka planda Yahoo ve Finviz sunucularıyla yaptığı konuşmalar yer almaktadır:")
                for log in debug_logs:
                    if "✅" in log:
                        st.success(log)
                    elif "⚠️" in log or "🔄" in log:
                        st.warning(log)
                    else:
                        st.error(log)
                        
        else:
            st.error("Veri işlenemedi. Lütfen sembolleri kontrol edin.")
