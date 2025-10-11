# app.py
import streamlit as st
import pandas as pd
from io import BytesIO
import os

# try pdfplumber first (no Java), else try tabula (needs Java)
use_tabula = False
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import tabula
    use_tabula = True
except Exception:
    tabula = None

# --- PAGE SETTINGS ---
st.set_page_config(page_title="Invoice Analyzer Pro", layout="wide")
st.title("📄 Invoice Analyzer Pro – Discount & Effective Rate Calculator")

st.markdown("""
### ⚙️ Features
- Upload **any PDF invoice**
- Auto-extract **Item Name, Price, Paid Qty, Free Qty**
- Choose your **Discount %**
- Calculates:
  - ✅ Discounted Unit Price  
  - ✅ Effective rate  
  - ✅ Total Quantity  
- Export results to **Excel**
""")

uploaded_file = st.file_uploader("📤 Upload PDF Invoice", type=["pdf"])
discount_percent = st.number_input("💰 Enter Discount Percentage", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
discount_multiplier = (100 - discount_percent) / 100

def try_pdfplumber(file_bytes):
    try:
        import pdfplumber
        from io import BytesIO
        pdf = pdfplumber.open(BytesIO(file_bytes))
        all_tables = []
        for page in pdf.pages:
            tables = page.extract_tables()
            for t in tables:
                df = pd.DataFrame(t[1:], columns=t[0])
                all_tables.append(df)
        pdf.close()
        return all_tables
    except Exception as e:
        return []

def try_tabula(file_path_or_bytes):
    try:
        # tabula.read_pdf accepts file-like or path; if bytes, write temp file
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            import tempfile
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tf.write(file_path_or_bytes)
            tf.close()
            path = tf.name
            tables = tabula.read_pdf(path, pages="all", multiple_tables=True)
            os.unlink(path)
        else:
            tables = tabula.read_pdf(file_path_or_bytes, pages="all", multiple_tables=True)
        return tables or []
    except Exception as e:
        return []

if uploaded_file:
    try:
        st.info("🔍 Reading PDF... working on table extraction.")
        file_bytes = uploaded_file.read()

        tables = []
        # 1) pdfplumber
        if pdfplumber is not None:
            tables = try_pdfplumber(file_bytes)

        # 2) fallback tabula if nothing found and tabula available
        if (not tables) and (tabula is not None):
            tables = try_tabula(file_bytes)

        if not tables:
            st.error("❌ No readable table found. Try a different invoice PDF or enable Java for tabula.")
        else:
            df = tables[0].copy()
            # cleanup column names
            df.columns = [str(c).strip().title() for c in df.columns]

            # detect columns (more robust)
            col_map = {}
            for col in df.columns:
                c = col.lower()
                if "item" in c or "description" in c or "name" in c:
                    col_map["Item Name"] = col
                elif "price" in c or "rate" in c or "unit" in c:
                    col_map["Original Price"] = col
                elif "free" in c:
                    col_map["Free Qty"] = col
                elif ("qty" in c and "free" not in c) or ("quantity" in c and "free" not in c):
                    col_map["Paid Qty"] = col

            if len(col_map) < 3:
                st.warning("⚠️ Could not auto-detect all columns. Showing raw table — you can rename columns manually below.")
                st.dataframe(df, use_container_width=True)
                st.markdown("**If column names detected incorrectly, rename them here:**")
                new_names = {}
                for needed in ["Item Name", "Original Price", "Paid Qty", "Free Qty"]:
                    choice = st.selectbox(f"Select column for `{needed}` (or leave blank):", [""] + list(df.columns))
                    if choice:
                        new_names[choice] = needed
                if new_names:
                    df = df.rename(columns=new_names)
            else:
                df = df.rename(columns={v: k for k, v in col_map.items()})

            # Coerce numeric columns
            for c in ["Original Price", "Paid Qty", "Free Qty"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[^\d\.\-]', '', regex=True), errors="coerce").fillna(0)
                else:
                    df[c] = 0

            # Calculations
            df["Discounted Unit Price"] = df["Original Price"] * discount_multiplier
            df["Total Qty"] = df["Paid Qty"] + df["Free Qty"]
            # avoid division by zero
            df["Effective Rate"] = df.apply(lambda r: round((r["Paid Qty"] * r["Discounted Unit Price"]) / r["Total Qty"], 2) if r["Total Qty"]>0 else round(r["Discounted Unit Price"],2), axis=1)
            df = df.round(2)

            st.success("✅ Processed invoice.")
            st.dataframe(df, use_container_width=True)

            output = BytesIO()
            df.to_excel(output, index=False, sheet_name="Invoice Analysis")
            output.seek(0)

            st.download_button("📥 Download Excel File", data=output, file_name="invoice_analysis.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.markdown("### 📊 Summary")
            st.write(f"**Discount Applied:** {discount_percent}%")
            st.write(f"**Total Items:** {len(df)}")
            st.write(f"**Total Paid Qty:** {int(df['Paid Qty'].sum())}")
            st.write(f"**Total Free Qty:** {int(df['Free Qty'].sum())}")
            st.write(f"**Total Value (After Discount):** Rs. {df['Discounted Unit Price'].sum():,.2f}")

    except Exception as e:
        st.error(f"⚠️ Error while processing PDF: {e}")
