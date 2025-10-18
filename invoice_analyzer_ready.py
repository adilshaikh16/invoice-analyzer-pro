"""
Invoice Analyzer Pro - Ready Version
- Upload PDF invoice
- Auto-extract item, price, paid qty, free qty (best-effort)
- Apply discount% (default 13%)
- Compute Discounted Unit Price & Effective Rate
- Show table & export Excel (.xlsx)

Requirements:
pip install streamlit pandas tabula-py pdfplumber openpyxl
Java runtime is required for tabula-py.
"""

import streamlit as st
import pandas as pd
import io
import sys
import os
from pathlib import Path

# Try imports that may not be present
try:
    import tabula
except Exception:
    tabula = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None

# ----------------- Helper functions -----------------
def ensure_java_env():
    """
    If there is a 'java' folder beside the script/exe, add it to PATH & set JAVA_HOME.
    This helps tabula when bundling portable Java.
    """
    base_path = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    java_folder = base_path / "java"
    if java_folder.exists():
        bin_path = java_folder / "bin"
        os.environ["JAVA_HOME"] = str(java_folder)
        os.environ["PATH"] = str(bin_path) + os.pathsep + os.environ.get("PATH", "")
        return True
    return False

def try_tabula_pdf(file_path):
    """Attempt to read tables using tabula-py. Returns list of DataFrames or []"""
    if tabula is None:
        return []
    try:
        # tabula returns list of DataFrames
        tables = tabula.read_pdf(file_path, pages="all", multiple_tables=True, guess=True)
        if not isinstance(tables, list):
            tables = [tables]
        # Filter out empty frames
        tables = [t for t in tables if isinstance(t, pd.DataFrame) and t.shape[0] > 0]
        return tables
    except Exception as e:
        return []

def fallback_pdfplumber_parse(file_path):
    """
    Very simple fallback: extract all text, try to detect lines with numbers, and build table.
    This is heuristic — works for consistent invoice layouts.
    """
    if pdfplumber is None:
        return pd.DataFrame()
    rows = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    # Heuristic: look for lines that contain at least two numbers (price & qty)
                    parts = line.strip().split()
                    nums = [p.replace(',', '') for p in parts if any(ch.isdigit() for ch in p)]
                    if len(nums) >= 2:
                        rows.append(line)
        # Try to parse rows into columns: item name (start) , price (first numeric), paid qty (next numeric), free qty (maybe next)
        parsed = []
        for r in rows:
            tokens = r.split()
            # extract numeric tokens (float/int) positions
            numeric_indices = [i for i,t in enumerate(tokens) if any(ch.isdigit() for ch in t)]
            if not numeric_indices:
                continue
            # assume last 3 numeric tokens are: Gross/Unit/Qty pattern — we try to pick price and paid/free qty
            # We'll attempt: price = tokens[numeric_indices[0]], paid = tokens[numeric_indices[-2]], free = tokens[numeric_indices[-1]]
            try:
                # item = tokens before first numeric token
                first_num_idx = numeric_indices[0]
                item_name = " ".join(tokens[:first_num_idx])
                # choose price and qty heuristically:
                # price -> numeric token closest to start
                price_token = tokens[numeric_indices[0]]
                # paid qty -> second last numeric (if exists)
                if len(numeric_indices) >= 2:
                    paid_token = tokens[numeric_indices[-2]]
                else:
                    paid_token = tokens[numeric_indices[0]]
                # free qty -> last numeric
                free_token = tokens[numeric_indices[-1]]
                # clean numbers
                def clean_num(s):
                    return float(s.replace(',', '').replace('Rs.', '').replace('PKR', ''))
                price = clean_num(price_token)
                paid = int(clean_num(paid_token))
                free = int(clean_num(free_token))
                parsed.append([item_name, price, paid, free])
            except Exception:
                continue
        df = pd.DataFrame(parsed, columns=["Item Name", "Original Price", "Paid Qty", "Free Qty"])
        return df
    except Exception:
        return pd.DataFrame()

def detect_and_prepare_df(df):
    """
    Given a dataframe (from tabula or manual), try to find relevant columns and normalize them.
    Returns standardized DF with columns: Item Name, Original Price, Paid Qty, Free Qty
    """
    if df is None or df.size == 0:
        return pd.DataFrame(columns=["Item Name", "Original Price", "Paid Qty", "Free Qty"])
    # standardize column names
    col_map = {}
    cols = [str(c) for c in df.columns]
    for c in cols:
        lc = c.lower()
        if "item" in lc or "name" in lc or "make" in lc:
            col_map[c] = "Item Name"
        elif "price" in lc or "unit" in lc or "rate" in lc:
            col_map[c] = "Original Price"
        elif "free" in lc:
            col_map[c] = "Free Qty"
        elif "qty" in lc and "free" not in lc:
            col_map[c] = "Paid Qty"
        elif "gross" in lc or "net amount" in lc:
            # sometimes gross amount column exists; skip
            pass
    # If mapping incomplete, try to guess based on data types
    df2 = df.copy()
    df2.columns = cols
    # If no Item Name found, assume first text column is item
    if "Item Name" not in col_map:
        # find first column with mostly non-numeric strings
        for c in cols:
            sample = df2[c].astype(str).head(10).tolist()
            non_num_count = sum(1 for s in sample if any(ch.isalpha() for ch in s))
            if non_num_count >= 5:
                col_map[c] = "Item Name"
                break
    # If no Original Price found, pick numeric column that looks like price (max value <= 1000000)
    if "Original Price" not in col_map:
        for c in cols:
            try:
                s = pd.to_numeric(df2[c].astype(str).str.replace(',', ''), errors='coerce')
                if s.notna().sum() >= 3 and s.max() < 10000000 and s.min() >= 0:
                    col_map[c] = "Original Price"
                    break
            except Exception:
                continue
    # If no Paid Qty found, pick small integer-like numeric column
    if "Paid Qty" not in col_map:
        for c in cols:
            try:
                s = pd.to_numeric(df2[c].astype(str).str.replace(',', ''), errors='coerce')
                # qty tends to be integer and not too large
                if s.notna().sum() >= 3 and s.dropna().apply(float.is_integer).sum() >= 1 and s.max() < 100000:
                    col_map[c] = "Paid Qty"
                    break
            except Exception:
                continue
    # If no Free Qty found, default to 0
    # Build new df
    normalized = pd.DataFrame()
    for orig_col, new_col in col_map.items():
        normalized[new_col] = df2[orig_col]
    # Ensure columns exist
    if "Free Qty" not in normalized.columns:
        normalized["Free Qty"] = 0
    # If any numeric columns are strings, convert
    for c in ["Original Price", "Paid Qty", "Free Qty"]:
        if c in normalized.columns:
            normalized[c] = pd.to_numeric(normalized[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        else:
            normalized[c] = 0
    # Item Name cleanup
    if "Item Name" in normalized.columns:
        normalized["Item Name"] = normalized["Item Name"].astype(str).str.strip()
    else:
        normalized["Item Name"] = "Unknown Item"
    normalized = normalized[["Item Name", "Original Price", "Paid Qty", "Free Qty"]]
    return normalized

# ----------------- Streamlit UI -----------------
st.set_page_config(page_title="Invoice Analyzer - Ready", layout="wide")
st.title("📄 Invoice Analyzer - Ready (Offline-friendly)")
st.markdown("Upload your invoice PDF. The app will auto-extract items, apply discount and calculate effective rates. If tabula (Java) is not available it will attempt a fallback parsing.")

# Optional: allow local run detection for java
java_found = ensure_java_env()
if java_found:
    st.info("Portable Java detected and set for this session.")

uploaded_file = st.file_uploader("Upload PDF invoice", type=["pdf"])

discount_percent = st.number_input("Discount Percent (%)", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
discount_multiplier = (100.0 - float(discount_percent)) / 100.0

if uploaded_file:
    # Save uploaded to a temp path for tabula/pdfplumber reading
    temp_path = Path("temp_uploaded_invoice.pdf")
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    st.info("Processing PDF — trying tabula first (best extraction).")
    tables = try_tabula_pdf(str(temp_path))
    df_final = pd.DataFrame()
    if tables:
        st.success(f"Tabula found {len(tables)} tables. Using the largest table heuristically.")
        # pick the table with max rows
        tables_sorted = sorted(tables, key=lambda x: x.shape[0], reverse=True)
        candidate = tables_sorted[0]
        df_normalized = detect_and_prepare_df(candidate)
        df_final = df_normalized
    else:
        st.warning("Tabula couldn't extract usable tables. Trying fallback parser (pdfplumber)...")
        df_fb = fallback_pdfplumber_parse(str(temp_path))
        if df_fb is not None and not df_fb.empty:
            st.success("Fallback parser produced a table (best-effort).")
            df_final = df_fb
        else:
            st.error("Could not extract table from this PDF. Try with a clearer PDF or ensure invoice uses tabular format.")
            df_final = pd.DataFrame(columns=["Item Name", "Original Price", "Paid Qty", "Free Qty"])

    # Now compute calculations if df_final not empty
    if not df_final.empty:
        # ensure numeric
        for c in ["Original Price", "Paid Qty", "Free Qty"]:
            df_final[c] = pd.to_numeric(df_final[c], errors="coerce").fillna(0)

        df_final["Discounted Unit Price"] = (df_final["Original Price"].astype(float) * discount_multiplier).round(2)
        df_final["Total Qty"] = (df_final["Paid Qty"].astype(float) + df_final["Free Qty"].astype(float)).astype(int)
        # Avoid division by zero
        def eff_rate(row):
            if row["Total Qty"] == 0:
                return 0.0
            return round((row["Paid Qty"] * row["Discounted Unit Price"]) / row["Total Qty"], 2)
        df_final["Effective Rate"] = df_final.apply(eff_rate, axis=1)

        # Reorder columns for display
        display_cols = ["Item Name", "Original Price", "Paid Qty", "Free Qty", "Total Qty", "Discounted Unit Price", "Effective Rate"]
        st.success("✅ Calculations complete.")
        st.dataframe(df_final[display_cols].reset_index(drop=True), use_container_width=True)

        # Summary section
        st.markdown("### Summary")
        st.write(f"**Discount applied:** {discount_percent}%")
        st.write(f"**Total distinct items:** {len(df_final)}")
        st.write(f"**Sum Paid Qty:** {int(df_final['Paid Qty'].sum())}")
        st.write(f"**Sum Free Qty:** {int(df_final['Free Qty'].sum())}")
        sum_after_discount = (df_final["Discounted Unit Price"] * df_final["Paid Qty"]).sum()
        st.write(f"**Total value after discount (Paid Qty only):** {sum_after_discount:,.2f}")

        # Export to Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_final[display_cols].to_excel(writer, index=False, sheet_name="Invoice Analysis")
            writer.save()
        buffer.seek(0)

        st.download_button(
            label="📥 Download Excel (.xlsx)",
            data=buffer,
            file_name="invoice_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No data to calculate.")
