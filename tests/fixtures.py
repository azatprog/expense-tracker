"""Synthetic statement text in the layout pdfplumber extracts from each bank's PDF.
Names, numbers and amounts are made up."""

BOA_CHECKING = """\
Bank of America, N.A.
for September 26, 2026 to October 27, 2026 Account number: 1111 2222 3333
Ending balance on October 27, 2026 $1,000.00
Deposits and other additions 3,012.11
ATM and debit card subtractions -30.97
Other subtractions -2,270.00
Checks -0.00
Service fees -30.00
JANE DOE ! Account # 1111 2222 3333 ! September 26, 2026 to October 27, 2026
Deposits and other additions
Date Description Amount
10/05/26 ACME CORP DES:PAYROLL ID:XXXXXXXXX INDN:DOE, JANE CO 3,000.00
ID:1234567890 PPD
10/15/26 CHECKCARD 1014 COMCAST / XFINITY 8002662278 TX 5543286628720294563 12.11
Total deposits and other additions $3,012.11
Withdrawals and other subtractions
ATM and debit card subtractions
Date Description Amount
10/01/26 COSTCO WHSE #1 10/01 #000224743 PURCHASE COSTCO WHSE #14 STAFFORD TX -20.97
continued on the next page
Cash back deals are better than ever.
JANE DOE ! Account # 1111 2222 3333 ! September 26, 2026 to October 27, 2026
Withdrawals and other subtractions - continued
ATM and debit card subtractions - continued
Date Description Amount
10/16/26 CHECKCARD 1014 HCTRA EZ TAG REBI 2818753279 TX 55500366288932093305556 -10.00
RECURRING
Total ATM and debit card subtractions -$30.97
Other subtractions
Date Description Amount
10/13/26 AMERICAN EXPRESS DES:ACH PMT ID:M5304 INDN:JANE DOE CO ID:1133133497 -150.00
WEB
10/13/26 APPLECARD GSBANK DES:PAYMENT ID:62592634 INDN:Jane Doe CO ID:9999999999 -80.00
WEB
10/14/26 Mobile Banking payment to CRD 9999 Confirmation# abc123 -40.00
10/27/26 MOVE SALES INC DES:Rent-dr ID:69973418 INDN:Jane Doe CO ID:4522284225 -2,000.00
WEB
Total other subtractions -$2,270.00
Service fees
Date Transaction description Amount
10/11/26 Wire Transfer Fee -30.00
Total service fees -$30.00
Note your Ending Balance already reflects the subtraction of Service Fees.
"""

APPLE_CARD = """\
Statement
Jane Doe, jane@example.com Sep 1 — Sep 30, 2026
Your September Balance Minimum Payment
as of Sep 30, 2026 Payment Due Due By
$80.00 $25.00 Oct 31, 2026
Payments
Date Description Amount
09/09/2026 ACH Deposit Internet transfer from account ending in 3333 -$500.00
Total payments for this period -$500.00
Transactions
Date Description Daily Cash Amount
09/04/2026 UBER *EATS 1455 MARKET ST 8005928996 94103 CA USA 2% $1.00 $50.00
09/05/2026 KELSEY-SEYBOLD CLINIC 11511 SHADOW CREEK PKWY PEARLAND 77584 TX USA 2% $0.40 $20.00
3% Daily Cash at Uber 1% $0.50
09/06/2026 HOUSE OF SPORT RETURN 24600 Katy Fwy Katy 77494 TX USA 2% -$0.10 -$5.00
09/07/2026 PAY*SOMESCHOOL 1 MAIN ST HOUSTON 77031 TX USA (RETURN) -$10.00
Daily Cash Adjustment -1% $0.10
Total Daily Cash this month $1.30
Total charges, credits and returns $55.10
Apple Card Monthly Installments
Dates Description Daily Cash Amounts
07/24/2026 Apple Store SUGAR LAND TX $609.00
TRANSACTION #05acb8bc038d
This month’s installment: $15.00
Final installment: Jul 31, 2027
Total financed $609.00
Apple Card is issued by Goldman Sachs Bank USA, Salt Lake City Branch.
"""

AMEX = """\
Blue Cash Preferred® from American Express
Prepared for
JANE DOE
Account Ending 1-23456
Closing Date 10/07/26
New Balance $150.00
Less Payments/Credits $100.00
Plus New Charges $160.00
Plus Fees $0.00
Plus I nterest Charged $0.00
Payments Details
*Indicates posting date
JANE DOE
Card Ending 1-23456
Date Description Amount
09/08/26* MOBILE PAYMENT - THANK YOU -$90.00
Credits Details
*I ndicates posting date
JANE DOE
Card Ending 1-23456
Date Description Amount
09/14/26 T.J. MAXX #1434 000001434 -$10.00
RICHMOND TX
8009266299
New Charges Summary
Category Account Details Total
New Charges Details
JANE DOE
Card Ending 1-23456
Date Description Amount
09/06/26 AMAZON MARKETPLACE NA PA AMZN.COM/BILL WA $60.00
MERCHANDISE
09/10/26 T.J. MAXX #1434 000001434 RICHMOND TX $40.00
8009266299
09/12/26 H-E-B #749 000000000580635 RICHMOND TX $60.00
8009874438
Fees
Total Fees for this Period $0.00
Days in Billing Period: 31
"""

BOA_CREDIT = """\
Bank of America
Account# 4444 5555 6666 9999
September 9 - October 8, 2026
New Balance Total $40.00
Payments and Other Credits -$100.00
Purchases and Adjustments $40.00
Fees Charged $0.00
Interest Charged $0.00
Transactions
Payments and Other Credits
10/05 10/05 PAYMENT FROM CHK 3333 CONF#zpx5zkqlm 4966 9999 -100.00
TOTAL PAYMENTS AND OTHER CREDITS FOR THIS PERIOD -$100.00
Purchases and Adjustments
09/09 09/10 SCHOOLCAFE HOUSTON TX 2647 9999 30.00
09/16 09/16 GEXA ENERGY HOUSTON TX 1652 9999 10.00
TOTAL PURCHASES AND ADJUSTMENTS FOR THIS PERIOD $40.00
Interest Charged
10/08 10/08 INTEREST CHARGED ON PURCHASES 0.00
TOTAL INTEREST CHARGED FOR THIS PERIOD $0.00
"""
