import streamlit as st
import xml.etree.ElementTree as ET
import re
from io import BytesIO
from datetime import datetime

# Helper to safely extract text
def get_text(parent, xpath, ns, default=""):
    elem = parent.find(xpath, ns)
    return elem.text.strip() if elem is not None and elem.text else default

# Կազմակերպությունների ցանկ
PAYER_OPTIONS = {
    "Importante LLC": {"PAYERACC": "1570075735510200", "TAXCODE": "1800232459"},
    "Fullstreet LLC":   {"PAYERACC": "1570071837240100", "TAXCODE": "1800505444"},
    "Companeros LLC":  {"PAYERACC": "1570065841128400", "TAXCODE": "1800510675"},
    "Westparks LLC":   {"PAYERACC": "1570094754410100", "TAXCODE": "1800520342"},
    "CJ":               {"PAYERACC": "1570098200832000", "TAXCODE": "1800522974"},
    "Santino":          {"PAYERACC": "1570098200832000", "TAXCODE": "1800522974"},
    "Primefood LLC":    {"PAYERACC": "1570075401620100", "TAXCODE": "1800222826"},
}

# === Web UI ===
st.set_page_config(page_title="XML Invoice ➜ Bank Payment", layout="centered")
st.title("📄 Invoice XML ➜ 🏦 Bank Payment XML")

payer_name    = st.selectbox("Ընտրեք վճարող կազմակերպությունը", list(PAYER_OPTIONS.keys()))
payer_data    = PAYER_OPTIONS[payer_name]
PAYERACC      = st.text_input("🏦 Վճարողի հաշիվը (PAYERACC)", value=payer_data["PAYERACC"])
TAXCODE       = st.text_input("🧾 Վճարողի ՀՎՀՀ (TAXCODE)", value=payer_data["TAXCODE"])
uploaded_file = st.file_uploader("📤 Վերբեռնեք Tax Service-ի `input.xml` ֆայլը", type="xml")

if uploaded_file:
    try:
        tree = ET.parse(uploaded_file)
        root = tree.getroot()

        NS = {"tp": "http://www.taxservice.am/tp3/invoice/definitions"}
        ET.register_namespace('', NS["tp"])

        # Ստուգում վճարողի TIN
        buyer_tin = get_text(root, ".//tp:BuyerInfo/tp:Taxpayer/tp:TIN", NS)
        if buyer_tin and not buyer_tin.endswith(TAXCODE[-8:]):
            st.markdown(
                """
                <div style="background-color:#ffcccc;color:red;padding:1rem;border:2px solid red;border-radius:5px;font-weight:bold;animation:blink 1s linear infinite;">
                    ⚠️ <strong>Warning</strong>: Ներբեռնել եք այլ վճարողի XML ֆայլ
                </div>
                <style>@keyframes blink {50% {opacity:0;}}</style>
                """,
                unsafe_allow_html=True
            )

        export_root = ET.Element("As_Import-Export_File")
        payord_block = ET.SubElement(export_root, "PayOrd", CAPTION="Documents (Payment Inside of RA)")
        docnum_counter = 1
        invoices = root.findall(".//tp:SignableData", NS)

        processed = []
        # 1) Մշակում adjustment invoices
        for inv in invoices:
            adj_flag  = get_text(inv, ".//tp:GeneralInfo/tp:AdjustmentAccount", NS)
            diff_flag = get_text(inv, ".//tp:GeneralInfo/tp:AdjustmentDiffFlag", NS)
            if adj_flag.lower() != "true" or diff_flag != "-1":
                continue
            adj_tin = get_text(inv, ".//tp:SupplierInfo/tp:Taxpayer/tp:TIN", NS)
            adj_bank = get_text(inv, ".//tp:SupplierInfo/tp:Taxpayer/tp:BankAccount/tp:BankAccountNumber", NS)
            adj_total = float(get_text(inv, ".//tp:GoodsInfo/tp:Total/tp:TotalPrice", NS, "0").replace(",", "."))
            adj_details = get_text(inv, ".//tp:InvoiceNumber/tp:Series", NS) + get_text(inv, ".//tp:InvoiceNumber/tp:Number", NS)

            # Base matches
            base_matches = []
            for base in invoices:
                if base is inv: continue
                btin = get_text(base, ".//tp:SupplierInfo/tp:Taxpayer/tp:TIN", NS)
                bbank = get_text(base, ".//tp:SupplierInfo/tp:Taxpayer/tp:BankAccount/tp:BankAccountNumber", NS)
                if btin == adj_tin and bbank == adj_bank:
                    det = get_text(base, ".//tp:InvoiceNumber/tp:Series", NS) + get_text(base, ".//tp:InvoiceNumber/tp:Number", NS)
                    total = float(get_text(base, ".//tp:GoodsInfo/tp:Total/tp:TotalPrice", NS, "0").replace(",", "."))
                    base_matches.append((base, det, total))
            if not base_matches:
                continue

            base_matches.sort(key=lambda x: x[2])
            matched = base_matches.copy(); remainder = []
            sum_total = sum(x[2] for x in matched)
            while len(matched) > 1 and sum_total - matched[0][2] >= adj_total:
                s = matched.pop(0); sum_total -= s[2]; remainder.append(s)
            while len(matched) > 9:
                p = matched.pop(0); sum_total -= p[2]; remainder.append(p)

            amount_str = f"{sum_total - adj_total:.2f}"
            details_aggr = ", ".join([d for (_, d, _) in matched] + [adj_details])
            first = matched[0][0]
            beneficiary = re.sub(r"[\"«»()（）]", "", get_text(first, ".//tp:SupplierInfo/tp:Taxpayer/tp:Name", NS))
            benacc = get_text(first, ".//tp:SupplierInfo/tp:Taxpayer/tp:BankAccount/tp:BankAccountNumber", NS).replace(" ", "")[:16]

            ET.SubElement(payord_block, "PayOrd", {
                "DOCNUM": f"{docnum_counter:02d}{datetime.now().strftime('%H%M')}",
                "PAYERACC": PAYERACC,
                "TAXCODE": TAXCODE,
                "BENACC": benacc,
                "BENEFICIARY": beneficiary,
                "AMOUNT": amount_str,
                "CURRENCY": "AMD",
                "DETAILS": details_aggr
            })
            docnum_counter += 1
            processed.append(inv)
            processed += [b for (b, _, _) in matched]
            for base, det, tot in remainder:
                rbenef = re.sub(r"[\"«»()（）]", "", get_text(base, ".//tp:SupplierInfo/tp:Taxpayer/tp:Name", NS))
                rba = get_text(base, ".//tp:SupplierInfo/tp:Taxpayer/tp:BankAccount/tp:BankAccountNumber", NS).replace(" ", "")[:16]
                ET.SubElement(payord_block, "PayOrd", {
                    "DOCNUM": f"{docnum_counter:02d}{datetime.now().strftime('%H%M')}",
                    "PAYERACC": PAYERACC,
                    "TAXCODE": TAXCODE,
                    "BENACC": rba,
                    "BENEFICIARY": rbenef,
                    "AMOUNT": f"{tot:.2f}",
                    "CURRENCY": "AMD",
                    "DETAILS": det
                })
                docnum_counter += 1
                processed.append(base)

        # 2) Remaining invoices
        for invoice in invoices:
            if invoice in processed:
                continue
            series = get_text(invoice, ".//tp:InvoiceNumber/tp:Series", NS)
            number = get_text(invoice, ".//tp:InvoiceNumber/tp:Number", NS)
            serial = f"{series}{number}"
            benacc = get_text(invoice, ".//tp:SupplierInfo/tp:Taxpayer/tp:BankAccount/tp:BankAccountNumber", NS).replace(" ", "")[:16]
            raw_name = get_text(invoice, ".//tp:SupplierInfo/tp:Taxpayer/tp:Name", NS)
            total_raw = get_text(invoice, ".//tp:GoodsInfo/tp:Total/tp:TotalPrice", NS, "0")
            details = serial
            tin = get_text(invoice, ".//tp:SupplierInfo/tp:Taxpayer/tp:TIN", NS)

            if tin == "00024873":
                add = invoice.find('.//tp:SupplierInfo/tp:Taxpayer/tp:AdditionalData', NS)
                if add is not None and add.text:
                    m = re.search(r"նշելով\s*(\S+)", add.text)
                    if m:
                        details = f"{m.group(1).strip()}, {serial}"
            elif tin == "01520882":
                add = invoice.find('.//tp:BuyerInfo/tp:Taxpayer/tp:AdditionalData', NS)
                if add is not None and add.text:
                    m = re.search(r"(Բաժանորդի քարտի համար\s*[0-9]+)(?=:)", add.text)
                    if m:
                        details = f"{m.group(1).strip()}, {serial}"
            elif tin == "02655115":
                add = invoice.find('.//tp:BuyerInfo/tp:Taxpayer/tp:AdditionalData', NS)
                if add is not None and add.text:
                    m = re.search(r"(Քարտի համար\s*[\d-]+)(?=:)", add.text)
                    if m:
                        details = f"{m.group(1).strip()}, {serial}"
            elif tin == "02500052":
                add_elem = invoice.find('.//tp:GeneralInfo/tp:AdditionalData', NS)
                if add_elem is not None and add_elem.text:
                        additional = add_elem.text.strip()
                        details = f"{additional}, {serial}"   

            elif tin == "00046317":
                add = invoice.find('.//tp:BuyerInfo/tp:Taxpayer/tp:AdditionalData', NS)
                if add is not None and add.text:
                    m = re.search(r"(Բաժանորդի համարը`\s*[0-9]+)(?=:)", add.text)
                    if m:
                        details = f"{m.group(1).strip()}, {serial}"                     
            try:
                tot = float(total_raw.replace(",", "."))
                amount = f"{int(tot)}.{int(tot*10)%10}0"
            except:
                amount = "0.00"

            ET.SubElement(payord_block, "PayOrd", {
                "DOCNUM": f"{docnum_counter:02d}{datetime.now().strftime('%H%M')}",
                "PAYERACC": PAYERACC,
                "TAXCODE": TAXCODE,
                "BENACC": benacc,
                "BENEFICIARY": raw_name,
                "AMOUNT": amount,
                "CURRENCY": "AMD",
                "DETAILS": details
            })
            docnum_counter += 1

        # Output file
        output = BytesIO()
        ET.ElementTree(export_root).write(output, encoding="utf-16", xml_declaration=True)
        output.seek(0)
        st.success("✅ Վճարումների ֆայլը պատրաստ է ներբեռնումի համար։")
        st.download_button("⬇️ Ներբեռնել output.xml", data=output, file_name="output.xml", mime="application/xml")

        total_payments = docnum_counter - 1
        total_amount = sum(float(p.attrib.get("AMOUNT", "0")) for p in payord_block.findall("PayOrd"))
        st.info(f"📌 Կազմվել է {total_payments} վճարում։")
        st.info(f"💰 Ընդհանուր գումարը՝ {total_amount:,.2f} AMD։")

    except Exception as e:
        st.error(f"Ֆայլը մշակելիս սխալ՝ {e}")