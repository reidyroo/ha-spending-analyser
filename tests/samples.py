"""Sample statement strings shared across test modules."""

MIDATA_CSV = (
    "Transaction Date,Transaction Type,Sort Code,Account Number,"
    "Transaction Description,Debit Amount,Credit Amount,Balance\n"
    "15/05/2026,DEB,00-00-00,12345678,COSTA COFFEE READING,13.45,,1234.56\n"
    "14/05/2026,DEB,00-00-00,12345678,AMAZON.CO.UK,42.99,,1248.01\n"
    "01/05/2026,CR,00-00-00,12345678,SALARY,,2000.00,\n"
)

FIRST_DIRECT_CSV = (
    "Date,Description,Amount,Balance\n"
    "13/05/2026,SUPERMARKET,-65.40,1234.56\n"
    "12/05/2026,SALARY,2000.00,1300.00\n"
)

NEWDAY_JL_CSV = (
    "Date,Description,Note,Amount(GBP)\n"
    "15/05/2026,Costa Coffee,COSTA COFFEE 43011071 READING GBR,13.45\n"
    "14/05/2026,Amazon,AMAZON.CO.UK PAYMENTS LONDON GBR,42.99\n"
    "10/05/2026,Refund,AMAZON REFUND,-5.00\n"
)

BARCLAYS_CSV = (
    "Date,Type,Merchant/Description,Debit/Credit,Balance\n"
    "15/04/2026,MAS,Costco Wholesale,-£123.74,£52.49\n"
    "07/04/2026,DD,NATIONWIDE B S,-£596.43,-£746.10\n"
    "07/04/2026,CR,SALARY,\"£2,160.00\",\"£2,346.99\"\n"
)

BARCLAYS_CSV_PREAMBLE = (
    "Account Number:,12345678,,,\n"
    ",,,,\n"
    "Date,Type,Merchant/Description,Debit/Credit,Balance\n"
    "15/04/2026,MAS,Costco Wholesale,\"-£123.74\",£52.49\n"
    "07/04/2026,CR,SALARY,\"£2,160.00\",\"£2,346.99\"\n"
    ",,,,\n"
    "Arranged Overdraft Limit,17/05/2026,£0.00,,\n"
)

ANZ_CSV = (
    "Date,Amount,Description\n"
    "15/05/2026,-65.40,Woolworths\n"
    "14/05/2026,2000.00,Salary\n"
)

NAB_CSV = (
    "Date,Amount,Account Number,Description,Merchant Name,Merchant City,"
    "Merchant State,BSB Number,Transaction Type,Currency Amount,Currency Rate,"
    "Original Currency,Conversion Charge\n"
    "15/05/2026,-65.40,123-456 7890123,Supermarket purchase,Woolworths,Sydney,"
    "NSW,032-001,EFTPOS,65.40,1.0,AUD,0.00\n"
)

WESTPAC_CSV = (
    "BSB,Account Number,Transaction Date,Narration,Cheque Number,Debit,Credit,Balance,Transaction Type\n"
    "032-001,123456,15/05/2026,EFTPOS WOOLWORTHS,,65.40,,1234.56,EFTPOS\n"
    "032-001,123456,01/05/2026,SALARY,,,,1300.00,CREDIT\n"
)

OFX_SGML = (
    "OFXHEADER:100\nDATA:OFXSGML\n\n"
    "<OFX>\n"
    "<STMTTRN>\n<TRNTYPE>DEBIT\n<DTPOSTED>20260515120000\n"
    "<TRNAMT>-42.50\n<FITID>TXN001\n<NAME>COSTA COFFEE\n<MEMO>Coffee shop\n"
    "</STMTTRN>\n"
    "<STMTTRN>\n<TRNTYPE>CREDIT\n<DTPOSTED>20260501\n"
    "<TRNAMT>2000.00\n<FITID>TXN002\n<NAME>SALARY\n"
    "</STMTTRN>\n"
    "</OFX>\n"
)

OFX_XML = (
    '<?xml version="1.0"?>\n'
    "<OFX><STMTTRNRS><STMTRS><BANKTRANLIST>\n"
    "<STMTTRN><TRNTYPE>DEBIT</TRNTYPE>"
    "<DTPOSTED>20260515</DTPOSTED>"
    "<TRNAMT>-42.50</TRNAMT>"
    "<FITID>X1</FITID>"
    "<NAME>COSTA COFFEE</NAME></STMTTRN>\n"
    "</BANKTRANLIST></STMTRS></STMTTRNRS></OFX>\n"
)

QIF_CONTENT = (
    "!Type:Bank\n"
    "D15/05/2026\nT-42.50\nPCosta Coffee\n^\n"
    "D01/05/2026\nT2000.00\nPSalary\n^\n"
)
