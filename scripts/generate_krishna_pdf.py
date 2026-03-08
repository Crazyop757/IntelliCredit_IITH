from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

OUTPUT = "data/raw/krishna_textile_annual_report.pdf"

doc = SimpleDocTemplate(OUTPUT, pagesize=A4,
    rightMargin=inch, leftMargin=inch,
    topMargin=inch, bottomMargin=inch)

styles = getSampleStyleSheet()
story  = []

def add(text, style='Normal', space=12):
    story.append(Paragraph(text, styles[style]))
    story.append(Spacer(1, space))

# ── COVER ──────────────────────────────────────────────────
add("KRISHNA TEXTILE INDUSTRIES PRIVATE LIMITED", 'Heading1')
add("CIN: U17111MH2008PTC183456", 'Normal')
add("Annual Report 2023-24", 'Heading2')
add("Plot No. 45, MIDC Industrial Area, Bhiwandi, Thane, Maharashtra - 421302")
add("Email: accounts@krishnatextile.in")
story.append(Spacer(1, 30))

# ── DIRECTORS REPORT ───────────────────────────────────────
add("BOARD OF DIRECTORS", 'Heading2')
directors = [
    ["Name",                    "Designation"],
    ["Rajesh Kumar Sharma",     "Managing Director"],
    ["Priya Rajesh Sharma",     "Whole Time Director"],
    ["Vinod Prakash Mehta",     "Director"],
    ["Sunita Vinod Mehta",      "Independent Director"],
]
t = Table(directors, colWidths=[3*inch, 3*inch])
t.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
    ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
    ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
    ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
    ('FONTSIZE',   (0,0), (-1,-1), 10),
    ('PADDING',    (0,0), (-1,-1), 8),
]))
story.append(t)
story.append(Spacer(1, 20))

# ── DIRECTORS REPORT TEXT ──────────────────────────────────
add("DIRECTORS REPORT", 'Heading2')
add("""Dear Members, Your Directors have pleasure in presenting the 16th Annual Report 
of Krishna Textile Industries Private Limited together with the Audited Financial 
Statements for the financial year ended 31st March 2024. The company is engaged in 
manufacturing of synthetic textile fabrics and yarn. During the year under review, 
the company achieved a turnover of Rs. 37,16,00,000 (Rupees Thirty Seven Crore 
Sixteen Lakhs). The company operates from its manufacturing facility at Bhiwandi, 
Maharashtra with an installed capacity of 120 looms.""")

add("""FINANCIAL HIGHLIGHTS: The total revenue from operations for FY 2023-24 stood 
at Rs. 37.16 Crore as compared to Rs. 34.20 Crore in FY 2022-23, registering a 
growth of 8.66%. EBITDA for the year was Rs. 4.82 Crore representing an EBITDA 
margin of 12.97%. Profit After Tax (PAT) for the year was Rs. 1.24 Crore.""")

add("""WORKING CAPITAL: The company avails working capital facilities from State Bank 
of India amounting to Rs. 8.00 Crore and from HDFC Bank Limited amounting to Rs. 
5.00 Crore. Total outstanding debt as of 31st March 2024 stands at Rs. 12.80 Crore. 
The company's current ratio stands at 1.12 and Debt to Equity ratio is 2.34.""")

add("""OPERATIONS: The company's factory is currently operating at approximately 
72% of installed capacity. Raw material procurement is primarily from Shree Fabrics 
Private Limited and Mehta Synthetics Limited, both located in the Bhiwandi textile 
cluster. The company exports approximately 35% of its production to buyers in 
UAE and Bangladesh through its export arm Krishna Exports.""")

story.append(Spacer(1, 20))

# ── AUDITORS REPORT ───────────────────────────────────────
add("INDEPENDENT AUDITORS REPORT", 'Heading2')
add("To the Members of Krishna Textile Industries Private Limited")
add("""OPINION: We have audited the accompanying financial statements of Krishna 
Textile Industries Private Limited which comprise the Balance Sheet as at 31st 
March 2024, the Statement of Profit and Loss, and the Cash Flow Statement for 
the year then ended. In our opinion and to the best of our information, the 
aforesaid financial statements give the information required by the Companies Act 
2013 and give a true and fair view of the state of affairs of the Company.""")

add("""KEY AUDIT MATTERS: During the course of our audit, we observed that the 
company has certain related party transactions with Krishna Exports, a proprietorship 
concern of the Managing Director, which require careful scrutiny. The transactions 
aggregating to Rs. 33.60 Crore during the year represent a significant concentration 
of revenue from a single related party. We are unable to independently verify the 
commercial substance of all such transactions without additional documentation. 
The management has represented that all transactions are at arm's length basis.""")

add("""EMPHASIS OF MATTER: We draw attention to the fact that the company has 
experienced 5 instances of cheque dishonour during the year ended 31st March 2024. 
Additionally, the Input Tax Credit claimed in GSTR-3B appears to be in excess of 
the credit available as per GSTR-2A by a material amount. The management has 
represented that reconciliation is in progress. Our opinion is not modified in 
respect of these matters.""")

story.append(Spacer(1, 20))

# ── BALANCE SHEET ─────────────────────────────────────────
add("BALANCE SHEET AS AT 31ST MARCH 2024", 'Heading2')
add("(All figures in Rupees Lakhs unless stated otherwise)")

bs_data = [
    ["LIABILITIES",                         "FY 2023-24",  "FY 2022-23"],
    ["Equity Share Capital",                "35.00",        "35.00"],
    ["Reserves and Surplus",                "53.20",        "40.40"],
    ["Total Equity (Net Worth)",            "88.20",        "75.40"],
    ["Long Term Borrowings (SBI TL)",       "62.50",        "75.80"],
    ["Short Term Borrowings (WC Limits)",   "128.00",       "115.00"],
    ["Trade Payables",                      "48.30",        "42.10"],
    ["Other Current Liabilities",           "18.50",        "15.20"],
    ["Total Liabilities",                   "345.50",       "323.50"],
    ["ASSETS",                              "",             ""],
    ["Fixed Assets (Net Block)",            "98.40",        "108.20"],
    ["Capital Work in Progress",            "12.00",        "5.00"],
    ["Inventories",                         "85.60",        "78.30"],
    ["Trade Receivables",                   "92.40",        "84.50"],
    ["Cash and Bank Balances",              "30.20",        "22.80"],
    ["Short Term Loans and Advances",       "26.90",        "24.70"],
    ["Total Assets",                        "345.50",       "323.50"],
]

t2 = Table(bs_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
t2.setStyle(TableStyle([
    ('BACKGROUND', (0,0),  (-1,0),  colors.darkblue),
    ('TEXTCOLOR',  (0,0),  (-1,0),  colors.white),
    ('FONTNAME',   (0,0),  (-1,0),  'Helvetica-Bold'),
    ('BACKGROUND', (0,9),  (-1,9),  colors.grey),
    ('TEXTCOLOR',  (0,9),  (-1,9),  colors.white),
    ('FONTNAME',   (0,9),  (-1,9),  'Helvetica-Bold'),
    ('GRID',       (0,0),  (-1,-1), 0.5, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,8),  [colors.white, colors.lightgrey]),
    ('ROWBACKGROUNDS', (0,10),(-1,-1), [colors.white, colors.lightgrey]),
    ('FONTSIZE',   (0,0),  (-1,-1), 9),
    ('PADDING',    (0,0),  (-1,-1), 6),
    ('ALIGN',      (1,0),  (-1,-1), 'RIGHT'),
]))
story.append(t2)
story.append(Spacer(1, 20))

# ── P&L ───────────────────────────────────────────────────
add("STATEMENT OF PROFIT AND LOSS FOR FY 2023-24", 'Heading2')
add("(All figures in Rupees Lakhs)")

pl_data = [
    ["Particulars",                          "FY 2023-24",  "FY 2022-23"],
    ["Revenue from Operations",              "3716.00",      "3420.00"],
    ["Other Income",                         "18.40",        "12.20"],
    ["Total Revenue",                        "3734.40",      "3432.20"],
    ["Cost of Raw Materials Consumed",       "2680.20",      "2490.10"],
    ["Employee Benefit Expenses",            "150.00",       "138.00"],
    ["Finance Costs (Interest)",             "185.40",       "198.20"],
    ["Depreciation",                         "98.60",        "102.40"],
    ["Other Expenses",                       "481.80",       "442.30"],
    ["Total Expenses",                       "3596.00",      "3371.00"],
    ["Profit Before Tax (PBT)",              "138.40",       "61.20"],
    ["Tax Expense",                          "14.20",        "8.10"],
    ["Profit After Tax (PAT)",               "124.20",       "53.10"],
    ["EBITDA",                               "422.40",       "361.80"],
    ["EBITDA Margin",                        "11.37%",       "10.57%"],
]

t3 = Table(pl_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
t3.setStyle(TableStyle([
    ('BACKGROUND', (0,0),  (-1,0),  colors.darkblue),
    ('TEXTCOLOR',  (0,0),  (-1,0),  colors.white),
    ('FONTNAME',   (0,0),  (-1,0),  'Helvetica-Bold'),
    ('GRID',       (0,0),  (-1,-1), 0.5, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
    ('FONTSIZE',   (0,0),  (-1,-1), 9),
    ('PADDING',    (0,0),  (-1,-1), 6),
    ('ALIGN',      (1,0),  (-1,-1), 'RIGHT'),
    ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
    ('FONTNAME',   (0,-2), (-1,-2), 'Helvetica-Bold'),
]))
story.append(t3)
story.append(Spacer(1, 20))

# ── KEY RATIOS ────────────────────────────────────────────
add("KEY FINANCIAL RATIOS", 'Heading2')
ratios_data = [
    ["Ratio",                       "FY 2023-24",  "FY 2022-23",  "Benchmark"],
    ["Current Ratio",               "1.12",         "1.08",         "> 1.33"],
    ["Debt to Equity Ratio",        "2.34",         "2.53",         "< 2.00"],
    ["Interest Coverage Ratio",     "1.75",         "1.31",         "> 2.00"],
    ["DSCR",                        "1.12",         "0.98",         "> 1.25"],
    ["Net Profit Margin",           "3.34%",        "1.55%",        "> 5.00%"],
    ["Return on Net Worth (RONW)",  "14.08%",       "7.04%",        "> 15%"],
    ["Debtors Turnover (days)",     "90",           "90",           "< 60 days"],
    ["Inventory Turnover (days)",   "115",          "115",          "< 90 days"],
]

t4 = Table(ratios_data, colWidths=[2.5*inch, 1.2*inch, 1.2*inch, 1.1*inch])
t4.setStyle(TableStyle([
    ('BACKGROUND', (0,0),  (-1,0),  colors.darkblue),
    ('TEXTCOLOR',  (0,0),  (-1,0),  colors.white),
    ('FONTNAME',   (0,0),  (-1,0),  'Helvetica-Bold'),
    ('GRID',       (0,0),  (-1,-1), 0.5, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
    ('FONTSIZE',   (0,0),  (-1,-1), 9),
    ('PADDING',    (0,0),  (-1,-1), 6),
    ('ALIGN',      (1,0),  (-1,-1), 'CENTER'),
    ('TEXTCOLOR',  (3,1),  (3,-1),  colors.red),
]))
story.append(t4)
story.append(Spacer(1, 20))

# ── RELATED PARTY ─────────────────────────────────────────
add("RELATED PARTY TRANSACTIONS", 'Heading2')
add("""The company has entered into transactions with Krishna Exports, a proprietorship 
firm owned by Mr. Rajesh Kumar Sharma (Managing Director). Total sales to Krishna 
Exports during FY 2023-24 amounted to Rs. 33,60,00,000 representing 90.42% of 
total revenue. The Board considers these transactions to be at arm's length. 
However, the high concentration of revenue from a related party poses a significant 
business continuity risk. No independent valuation of these transactions has been 
obtained.""")

# ── CASH FLOW ─────────────────────────────────────────────
add("CASH FLOW STATEMENT", 'Heading2')
cf_data = [
    ["Particulars",                              "Amount (Rs. Lakhs)"],
    ["Net Profit Before Tax",                    "138.40"],
    ["Add: Depreciation",                        "98.60"],
    ["Add: Finance Costs",                       "185.40"],
    ["Changes in Working Capital",               "(142.30)"],
    ["Cash from Operating Activities (A)",       "280.10"],
    ["Purchase of Fixed Assets",                 "(85.80)"],
    ["Cash from Investing Activities (B)",       "(85.80)"],
    ["Repayment of Term Loan",                   "(68.40)"],
    ["Interest Paid",                            "(185.40)"],
    ["Cash from Financing Activities (C)",       "(253.80)"],
    ["Net Increase in Cash (A+B+C)",             "(59.50)"],
    ["Opening Cash Balance",                     "381.70"],
    ["Closing Cash Balance",                     "322.20"],
]

t5 = Table(cf_data, colWidths=[4*inch, 2*inch])
t5.setStyle(TableStyle([
    ('BACKGROUND', (0,0),  (-1,0),  colors.darkblue),
    ('TEXTCOLOR',  (0,0),  (-1,0),  colors.white),
    ('FONTNAME',   (0,0),  (-1,0),  'Helvetica-Bold'),
    ('GRID',       (0,0),  (-1,-1), 0.5, colors.grey),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
    ('FONTSIZE',   (0,0),  (-1,-1), 9),
    ('PADDING',    (0,0),  (-1,-1), 6),
    ('ALIGN',      (1,0),  (1,-1),  'RIGHT'),
]))
story.append(t5)

doc.build(story)
print(f"Annual Report PDF created: {OUTPUT}")
print(f"File size: {__import__('os').path.getsize(OUTPUT)/1024:.1f} KB")
