import streamlit as st
import pandas as pd
import pdfplumber
from io import BytesIO

st.set_page_config(page_title="Invoice Analyzer Pro", layout="wide")
st.title("📄 Invoice Analyzer Pro – Discount & Effective Rate Calculator")

st.markdown("""
### ⚙️ Features
- Upload **any PDF invoice**
- Auto-extract **Item Name, Price, Paid Qty, Free Qty**
- Choose your **Discount %**
- Calculates:
  - ✅ Discounted Unit Price  
  - ✅ Effective Rate  
  - ✅ Total Quantity  
- Export results to **Excel** with one click
""")

uploaded_file = st.file_uploader("📤 Upload PDF Invoice", type=["pdf"])
discount_percent = st.number_input("💰 Enter Discount Percentage", min_value=0.0, max_value=100.0, value=13.0, step=0.5)
discount_multiplier = (100 - discount_percent) / 100

if uploaded_file:
    try:
        st.info("🔍 Reading PDF... Please wait.")
        df_list = []

        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    df_list.append(pd.DataFrame(table[1:], columns=table[0]))

        if not df_list:
            st.error("❌ No readable table found in this PDF. Make sure it has a proper tabular format.")
        else:
            df = pd.concat(df_list, ignore_index=True)
            df.columns = [c.strip().title() for c in df.columns]

            col_map = {}
            for col in df.columns:
                if "Item" in col: col_map["Item Name"] = col
                elif "Price" in col: col_map["Original Price"] = col
                elif "Qty" in col and "Free" not in col: col_map["Paid Qty"] = col
                elif "Free" in col: col_map["Free Qty"] = col

            if len(col_map) < 4:
                st.error("⚠️ Could not detect all required columns (Item, Price, Paid Qty, Free Qty). Check PDF layout.")
            else:
                df = df.rename(columns={v: k for k, v in col_map.items()})
                import re

def clean_number(x):
    if isinstance(x, str):
        x = re.sub(r"[^\d.]", "", x)  # removes commas, Rs., spaces etc.
    try:
        return float(x)
    except:
        return 0

for c in ["Original Price", "Paid Qty", "Free Qty"]:
    df[c] = df[c].apply(clean_number)


                df["Discounted Unit Price"] = df["Original Price"] * discount_multiplier
                df["Total Qty"] = df["Paid Qty"] + df["Free Qty"]
                df["Effective Rate"] = (df["Paid Qty"] * df["Discounted Unit Price"]) / df["Total Qty"]
                df = df.round(2)

                st.success("✅ Successfully processed your invoice!")
                st.dataframe(df, use_container_width=True)

                output = BytesIO()
                df.to_excel(output, index=False, sheet_name="Invoice Analysis")
                output.seek(0)

                st.download_button(
                    label="📥 Download Excel File",
                    data=output,
                    file_name="invoice_analysis.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                st.markdown("### 📊 Summary")
                st.write(f"**Discount Applied:** {discount_percent}%")
                st.write(f"**Total Items:** {len(df)}")
                st.write(f"**Total Paid Qty:** {df['Paid Qty'].sum():,.0f}")
                st.write(f"**Total Free Qty:** {df['Free Qty'].sum():,.0f}")
                st.write(f"**Total Value (After Discount):** Rs. {df['Discounted Unit Price'].sum():,.2f}")

    except Exception as e:
        st.error(f"⚠️ Error while processing PDF: {e}")
