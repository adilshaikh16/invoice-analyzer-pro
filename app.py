# app.py - Invoice Analyzer Pro v3 (Minimal: Item Name | Unit Price | Effective Unit Price)
import streamlit as st
import pandas as pd
import pdfplumber
from io import BytesIO
import re
import numpy as np

st.set_page_config(page_title="Invoice Analyzer Pro v3", layout="wide")
st.title("📄 Invoice Analyzer Pro — V3 (Item | Unit Price | Effective Unit Price)")

st.markdown("""
Upload a PDF invoice. The app will:
- Auto-detect item name, price and quantity (if qty available)
- Compute **Unit Price** (if price is total and qty exists, it will divide)
- Apply discount and show **Effective Unit Price**
""")

# ---------- helpers ----------
def clean_number_raw(x):
    """Return cleaned string of digits and dot, or empty string."""
    if pd.isna(x):
        return ""
    s = str(x)
    # keep digits and dot and minus
    s = re.sub(r"[^\d.\-]", "", s)
    # handle repeated dots like "1.234.56" -> keep first dot only
    if s.count(".") > 1:
        parts = s.split(".")
        s = parts[0] + "." + "".join(parts[1:])
    return s

def to_float_safe(x):
    try:
        s = clean_number_raw(x)
        if s == "":
            return np.nan
        return float(s)
    except:
        return np.nan

def column_numeric_stats(series):
    vals = series.map(to_float_safe)
    num_non_na = vals.notna().sum()
    total = len(series)
    prop_numeric = (num_non_na / total) if total>0 else 0
    median = float(np.nanmedian(vals)) if num_non_na>0 else np.nan
    std = float(np.nanstd(vals)) if num_non_na>0 else np.nan
    return prop_numeric, median, std, vals

def choose_item_column(df):
    # choose the column with lowest numeric proportion and highest average string length
    best_col = None
    best_score = -999
    for col in df.columns:
        series = df[col].astype(str).fillna("")
        prop_num, _, _, _ = column_numeric_stats(series)
        avg_len = series.map(len).mean()
        score = (1 - prop_num) * 0.6 + (avg_len / 100) * 0.4
        if score > best_score:
            best_score = score
            best_col = col
    return best_col, best_score

def choose_price_column(df):
    # choose column with highest numeric proportion and median > 0
    best_col = None
    best_prop = -1
    for col in df.columns:
        prop_num, median, std, vals = column_numeric_stats(df[col])
        if prop_num > best_prop and (not np.isnan(median)) and median > 0:
            best_prop = prop_num
            best_col = col
    return best_col, best_prop

def choose_qty_column(df, exclude_cols=[]):
    # choose column with numeric ints and small median (practical qty)
    best_col = None
    best_score = -1
    for col in df.columns:
        if col in exclude_cols: 
            continue
        prop_num, median, std, vals = column_numeric_stats(df[col])
        if prop_num < 0.3:
            continue
        # prefer columns with integer-like median and moderate size
        score = prop_num
        if not np.isnan(median) and median < 10000:  # heuristic
            score += 0.5
        if not np.isnan(std) and std < median*2 + 1:
            score += 0.2
        if score > best_score:
            best_score = score
            best_col = col
    return best_col, best_score

# ---------- UI ----------
uploaded_file = st.file_uploader("📤 Upload PDF Invoice (single file)", type=["pdf"])
discount_percent = st.number_input("💰 Discount Percentage (applies to unit price)", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
discount_multiplier = (100 - discount_percent) / 100

if uploaded_file:
    try:
        st.info("🔍 Reading PDF and extracting tables...")
        df_list = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                # extract multiple tables per page if present
                tables = page.extract_tables()
                if tables:
                    for t in tables:
                        if not t or len(t) < 2:
                            continue
                        header = [str(h).strip() for h in t[0]]
                        rows = t[1:]
                        if len(rows) == 0:
                            continue
                        temp = pd.DataFrame(rows, columns=header)
                        df_list.append(temp)

        if not df_list:
            st.error("❌ No tables detected in PDF. Try a different invoice (or a clearer PDF).")
        else:
            raw = pd.concat(df_list, ignore_index=True)
            # normalize headers
            raw.columns = [str(c).strip() for c in raw.columns]
            raw.replace("", pd.NA, inplace=True)

            # drop columns that are completely empty
            raw = raw.loc[:, raw.notna().any(axis=0)]

            # basic cleanup rows that are all null/empty
            raw = raw[~(raw.isna().all(axis=1))]
            raw = raw.reset_index(drop=True)

            # Auto-detect columns
            item_col, item_conf = choose_item_column(raw)
            price_col, price_conf = choose_price_column(raw)
            qty_col, qty_conf = choose_qty_column(raw, exclude_cols=[item_col, price_col])

            st.write("### 🔎 Auto-detected columns (confidence)")
            st.write(f"- Item column: **{item_col}** (score {item_conf:.2f})")
            st.write(f"- Price column: **{price_col}** (prop {price_conf:.2f})")
            st.write(f"- Qty column: **{qty_col}** (score {qty_conf:.2f})")

            manual_override_needed = False
            # if confidence low, allow manual mapping
            if price_conf < 0.4 or item_conf < 0.4:
                manual_override_needed = True

            st.markdown("---")
            st.write("If auto-detection seems wrong, choose columns manually below (press Apply):")

            cols = list(raw.columns)
            sel_item = st.selectbox("Select Item Name column", options=["--Auto--"] + cols, index=0)
            sel_price = st.selectbox("Select Price column (may be unit or total)", options=["--Auto--"] + cols, index=0)
            sel_qty = st.selectbox("Select Quantity column (if available)", options=["--Auto--"] + ["None"] + cols, index=0)

            if sel_item != "--Auto--":
                item_col = sel_item
            if sel_price != "--Auto--":
                price_col = sel_price
            if sel_qty != "--Auto--" and sel_qty != "None":
                qty_col = sel_qty
            elif sel_qty == "None":
                qty_col = None

            if not item_col or not price_col:
                st.error("Item or Price column not detected. Please select them manually above.")
            else:
                # Create working df
                work = pd.DataFrame()
                work["Item Name"] = raw[item_col].astype(str).fillna("").map(lambda s: s.strip())
                work["Price_Raw"] = raw[price_col]

                if qty_col:
                    work["Qty_Raw"] = raw[qty_col]
                else:
                    work["Qty_Raw"] = pd.NA

                # Clean numeric conversions
                work["Price_Num"] = work["Price_Raw"].map(to_float_safe)
                work["Qty_Num"] = work["Qty_Raw"].map(lambda x: int(to_float_safe(x)) if not pd.isna(to_float_safe(x)) else np.nan)

                # Heuristic: if price looks like total (many prices >> qty) and qty exists -> compute unit price = Price/Qty
                unit_prices = []
                use_division = False
                if work["Qty_Num"].notna().sum() > 0:
                    # compute price/qty where possible
                    ratios = []
                    for p, q in zip(work["Price_Num"], work["Qty_Num"]):
                        if not pd.isna(p) and not pd.isna(q) and q != 0:
                            ratios.append(p / q)
                    if len(ratios) >= 1:
                        median_ratio = np.median(ratios)
                        std_ratio = np.std(ratios)
                        # if median_ratio is reasonable and ratios have low relative std -> implies Price was total
                        if std_ratio / (median_ratio + 1e-9) < 0.6:
                            use_division = True
                # compute unit price
                def compute_unit(p, q):
                    if pd.isna(p):
                        return np.nan
                    if use_division and (not pd.isna(q)) and q != 0:
                        return p / q
                    else:
                        return p

                work["Unit_Price_Raw"] = work.apply(lambda r: compute_unit(r["Price_Num"], r["Qty_Num"]), axis=1)

                # final numeric cleaning and rounding
                work["Unit Price"] = work["Unit_Price_Raw"].map(lambda x: round(float(x), 2) if not pd.isna(x) else 0.0)
                work["Effective Unit Price"] = (work["Unit Price"] * discount_multiplier).map(lambda x: round(float(x), 2))

                # Remove empty items
                work = work[work["Item Name"].str.strip() != ""].reset_index(drop=True)

                # If everything zeros or suspicious, show raw for debugging
                if work["Unit Price"].sum() == 0:
                    st.warning("⚠️ Detected that all Unit Prices are 0 — please check column mappings or upload a clearer invoice PDF.")
                    st.write("Raw extracted table (first 20 rows):")
                    st.dataframe(raw.head(20), use_container_width=True)

                # Final output (only required 3 columns)
                result = work[["Item Name", "Unit Price", "Effective Unit Price"]].copy()
                # tidy types
                result["Unit Price"] = result["Unit Price"].astype(float)
                result["Effective Unit Price"] = result["Effective Unit Price"].astype(float)

                st.markdown("### ✅ Result (clean)")
                st.dataframe(result, use_container_width=True)

                # Downloads
                excel_buffer = BytesIO()
                csv_buffer = BytesIO()
                result.to_excel(excel_buffer, index=False, sheet_name="InvoiceV3")
                result.to_csv(csv_buffer, index=False)
                excel_buffer.seek(0)
                csv_buffer.seek(0)

                colx, coly = st.columns([1,1])
                with colx:
                    st.download_button("📥 Download Excel (.xlsx)", data=excel_buffer, file_name="invoice_v3.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                with coly:
                    st.download_button("📄 Download CSV", data=csv_buffer, file_name="invoice_v3.csv", mime="text/csv")

    except Exception as e:
        st.error(f"⚠️ Error while processing PDF: {e}")
