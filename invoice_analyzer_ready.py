"""
Invoice Analyzer Pro – Final Fixed Version
------------------------------------------
✅ Reads invoice PDFs (tabula / pdfplumber fallback)
✅ Detects item name, unit price, paid qty, free qty
✅ Applies Discount%
✅ Calculates Discounted Unit Price & Effective Rate
✅ Clean DataFrame Output + Excel Export (Fixed)
"""

import streamlit as st
import pandas as pd
import io
import os
import sys
from pathlib import Path

# Optional imports
try:
    import tabula
except Exception:
    tabula = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None

# ----------------- Helper Functions -----------------

def ensure_java_env():
    """Auto-detect portable Java folder (for tabula)"""
    base_path = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    java_folder = base_path / "java"
    if java_folder.exists():
        bin_path = java_folder / "bin"
        os.environ["JAVA_HOME"] = str(java_folder)
        os.environ["PATH"] = str(bin_path) + os.pathsep + os.environ.get("PATH", "")
        return True
    return False


def clean_table(df):
    """Clean raw table and remove empty/junk rows"""
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.reset_index(drop=True)
    return df


def parse_tabula(file_path):
    """Try reading PDF tables with tabula"""
    if not tabula:
        return None
    try:
        tables = tabula.read_pdf(file_path, pages="all", multiple_tables=True)
        if not tables:
            return None
        tables = [t for t in tables if not t.empty]
        if not tables:
            return None
        df = max(tables, key=lambda x: x.shape[0])
        return clean_table(df)
    except Exception:
        return None


def parse_pdfplumber(file_path):
    """Fallback PDF text parser"""
    if not pdfplumber:
        return None
    rows = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    parts = line.strip().split()
                    if len(parts) < 4:
                        continue
                    # detect numeric parts
                    nums = [p.replace(",", "") for p in parts if any(ch.isdigit() for ch in p)]
                    if len(nums) < 2:
                        continue
                    # crude pattern: last few tokens numeric
                    try:
                        paid = int(float(nums[-2]))
                        free = int(float(nums[-1]))
                        price = float(nums[0])
                        item = " ".join(parts[:-3])
                        rows.append([item, price, paid, free])
                    except Exception:
                        continue
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["Item Name", "Original Price", "Paid Qty", "Free Qty"])
        return df
    except Exception:
        return None


def normalize_columns(df):
    """Normalize and rename columns"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Item Name", "Original Price", "Paid Qty", "Free Qty"])

    df.columns = [str(c).lower().strip() for c in df.columns]
    rename_map = {}
    for c in df.columns:
        if "item" in c or "name" in c:
            rename_map[c] = "Item Name"
        elif "price" in c or "unit" in c or "rate" in c:
            rename_map[c] = "Original Price"
        elif "free" in c:
            rename_map[c] = "Free Qty"
        elif "qty" in c:
            rename_map[c] = "Paid Qty"

    df = df.rename(columns=rename_map)
    for col in ["Item Name", "Original Price", "Paid Qty", "Free Qty"]:
        if col not in df.columns:
            df[col] = 0

    df["Item Name"] = df["Item Name"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    for c in ["Original Price", "Paid Qty", "Free Qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df = df[df["Item Name"].str.len() > 2]
    return df[["Item Name", "Original Price", "Paid Qty", "Free Qty"]]


# ----------------- Streamlit App -----------------

st.set_page_config(page_title="Invoice Analyzer Pro", layout="wide")
st.title("📊 Invoice Analyzer Pro – Final Fixed Version")

st.markdown("""
Upload your PDF invoice to automatically calculate **Discounted Unit Price** and **Effective Rate**.  
Works with most invoice tables (Tabula + fallback PDF text parser).
""")

discount_percent = st.number_input("💰 Discount (%)", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
discount_multiplier = (100.0 - discount_percent) / 100.0

uploaded_file = st.file_uploader("📤 Upload Invoice PDF", type=["pdf"])

if uploaded_file:
    temp_path = "uploaded_invoice.pdf"
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.read())

    st.info("⏳ Reading PDF... please wait")

    # Try tabula first
    df = parse_tabula(temp_path)
    if df is not None:
        st.success("✅ Table extracted successfully using Tabula.")
    else:
        st.warning("⚠️ Tabula failed. Trying fallback parser (pdfplumber)...")
        df = parse_pdfplumber(temp_path)
        if df is not None:
            st.success("✅ Fallback parser extracted data successfully.")
        else:
            st.error("❌ Could not extract usable data from this PDF.")
            st.stop()

    df = normalize_columns(df)

    # --- Calculations ---
    df["Discounted Unit Price"] = (df["Original Price"] * discount_multiplier).round(2)
    df["Total Qty"] = (df["Paid Qty"] + df["Free Qty"]).astype(int)
    df["Effective Rate"] = df.apply(
        lambda r: round((r["Paid Qty"] * r["Discounted Unit Price"]) / r["Total Qty"], 2) if r["Total Qty"] else 0, axis=1
    )

    # Clean output
    df = df[df["Original Price"] > 0]
    display_cols = ["Item Name", "Original Price", "Paid Qty", "Free Qty", "Total Qty", "Discounted Unit Price", "Effective Rate"]

    st.subheader("📄 Invoice Data")
    st.dataframe(df[display_cols], use_container_width=True)

    # --- Summary ---
    st.subheader("📈 Summary")
    st.write(f"**Discount Applied:** {discount_percent}%")
    st.write(f"**Total Items:** {len(df)}")
    st.write(f"**Sum Paid Qty:** {df['Paid Qty'].sum():,.0f}")
    st.write(f"**Sum Free Qty:** {df['Free Qty'].sum():,.0f}")
    total_value = (df["Paid Qty"] * df["Discounted Unit Price"]).sum()
    st.write(f"**Total Value After Discount:** Rs. {total_value:,.2f}")

    # --- Excel Export (Fixed Version) ---
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df[display_cols].to_excel(writer, index=False, sheet_name="Invoice Analysis")

    buffer.seek(0)
    st.download_button(
        label="📥 Download Excel (.xlsx)",
        data=buffer,
        file_name="invoice_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
