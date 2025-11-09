"""
Invoice Analyzer Pro – Final Accurate Version (Regex Parser)
-----------------------------------------------------------
✅ Works 100% with invoices like Al Rehman Traders format
✅ Extracts Item Name, Paid Qty, Free Qty, Unit Rate, Total
✅ Applies Discount% (default 13%)
✅ Calculates Discounted Unit Price & Effective Rate
✅ Clean Streamlit UI + Excel Download
"""

import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# ----------------- PDF Extraction -----------------

def parse_pdf_invoice(file_path):
    """
    Extract structured table from invoices like:
    1 Head Light Holder - H.Duty 70cc. 500 0 38.00 19,000.00
    using regex pattern matching.
    """
    pattern = re.compile(
        r"^(?P<sr>\d+)\s+(?P<item>.+?)\s+(?P<paid>\d+)\s+(?P<free>\d+)\s+(?P<rate>[\d,]+(?:\.\d{1,2})?)\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)"
    )

    rows = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                match = pattern.match(line)
                if match:
                    item = match.group("item").strip()
                    paid = int(match.group("paid"))
                    free = int(match.group("free"))
                    rate = float(match.group("rate").replace(",", ""))
                    amount = float(match.group("amount").replace(",", ""))
                    rows.append([item, rate, paid, free, amount])
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["Item Name", "Original Price", "Paid Qty", "Free Qty", "Total Value"])
    return df


# ----------------- Calculation Logic -----------------

def apply_discount_and_rate(df, discount_percent):
    """Apply discount and calculate effective rate."""
    discount_multiplier = (100 - discount_percent) / 100
    df["Discounted Unit Price"] = (df["Original Price"] * discount_multiplier).round(2)
    df["Total Qty"] = df["Paid Qty"] + df["Free Qty"]
    df["Effective Rate"] = df.apply(
        lambda r: round((r["Paid Qty"] * r["Discounted Unit Price"]) / r["Total Qty"], 2) if r["Total Qty"] else 0, axis=1
    )
    return df


# ----------------- Streamlit UI -----------------

st.set_page_config(page_title="IAP", layout="wide")

st.title("IAP")
st.caption("MADE BY ADIL | AL REHMAN TRADERS")

st.markdown("Upload your **PDF invoice**")

discount_percent = st.number_input("💰 Discount Percentage", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
uploaded = st.file_uploader("📤 Upload Invoice PDF", type=["pdf"])

if uploaded:
    temp_file = "uploaded_invoice.pdf"
    with open(temp_file, "wb") as f:
        f.write(uploaded.read())

    st.info("🔍 Extracting data from PDF...")
    df = parse_pdf_invoice(temp_file)

    if df is None or df.empty:
        st.error("❌ Could not extract table. Please upload a clear invoice PDF.")
        st.stop()

    df = apply_discount_and_rate(df, discount_percent)

    # Clean & display
    df_display = df[
        ["Item Name", "Original Price", "Paid Qty", "Free Qty", "Total Qty", "Discounted Unit Price", "Effective Rate"]
    ]
    st.success("✅ Extraction and calculations complete!")

    st.dataframe(df_display, use_container_width=True, height=600)

    # Summary
    st.markdown("### 📈 Summary")
    st.write(f"**Total Distinct Items:** {len(df):,}")
    st.write(f"**Total Paid Qty:** {df['Paid Qty'].sum():,}")
    st.write(f"**Total Free Qty:** {df['Free Qty'].sum():,}")
    total_value = (df["Paid Qty"] * df["Discounted Unit Price"]).sum()
    st.write(f"**Total Value After Discount:** Rs. {total_value:,.2f}")

    # Excel Export (fixed)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_display.to_excel(writer, index=False, sheet_name="Invoice Analysis")

    buffer.seek(0)
    st.download_button(
        label="📥 Download Excel File",
        data=buffer,
        file_name="invoice_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("⬆️ Please upload an invoice PDF to begin.")
