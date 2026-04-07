"""
TaxMind Module 1 — Document Ingestion & Field Extraction Engine
---------------------------------------------------------------
Handles: Digital PDFs, Scanned PDFs, Images (JPG/PNG), XLSX bank statements, GSTR JSON, Tally XML
Extracts: GSTIN, Invoice No, Date, Taxable Value, CGST, SGST, IGST, HSN codes, Line items
Scores:   Per-field confidence score (0.0 - 1.0)
"""

import re
import json
import fitz          # PyMuPDF — for PDF text extraction
import pytesseract   # Tesseract OCR wrapper
import pandas as pd
import xml.etree.ElementTree as ET

from PIL import Image, ImageFilter, ImageEnhance
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class ExtractedField:
    value: Optional[str]
    confidence: float          # 0.0 to 1.0
    flagged: bool = False      # True if below threshold or failed validation

@dataclass
class LineItem:
    description: str
    hsn_code: Optional[str]
    quantity: Optional[str]
    rate: Optional[str]
    amount: Optional[str]
    taxable_value: Optional[str]
    gst_rate: Optional[str]

@dataclass
class ExtractionResult:
    filename: str
    doc_type: str              # digital_pdf / scanned_pdf / image / xlsx / json / xml
    source_type: str           # invoice / bank_statement / gstr_json / tally_xml

    # Core invoice fields
    supplier_gstin: ExtractedField = None
    buyer_gstin:    ExtractedField = None
    invoice_number: ExtractedField = None
    invoice_date:   ExtractedField = None
    taxable_value:  ExtractedField = None
    cgst:           ExtractedField = None
    sgst:           ExtractedField = None
    igst:           ExtractedField = None
    total_amount:   ExtractedField = None
    hsn_code:       ExtractedField = None

    line_items: list = field(default_factory=list)
    raw_text:   str  = ""
    errors:     list = field(default_factory=list)

    @property
    def overall_confidence(self):
        fields = [
            self.supplier_gstin, self.invoice_number,
            self.invoice_date, self.taxable_value,
            self.cgst, self.sgst, self.total_amount,
        ]
        valid = [f.confidence for f in fields if f and f.value]
        return round(sum(valid) / len(valid), 2) if valid else 0.0

    @property
    def needs_review(self):
        return self.overall_confidence < 0.80

    def to_dict(self):
        return asdict(self)


# ── GSTIN validation ─────────────────────────────────────────────────────────

GSTIN_PATTERN = re.compile(
    r'\b(\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1})\b'
)

def validate_gstin(gstin: str) -> bool:
    """Validate GSTIN using checksum algorithm."""
    if not gstin or len(gstin) != 15:
        return False
    if not GSTIN_PATTERN.match(gstin):
        return False
    # State code check (01-38 valid)
    state = int(gstin[:2])
    if not (1 <= state <= 38):
        return False
    return True


# ── Regex field extractors ────────────────────────────────────────────────────

def extract_gstins(text: str) -> list[str]:
    return GSTIN_PATTERN.findall(text)

def extract_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r'(?:Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\/\-_]{3,20})',
        r'(?:Bill\s*(?:No\.?|Number)\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\/\-_]{3,20})',
        r'(?:Inv\.?\s*No\.?\s*[:\-]?\s*)([A-Z0-9][A-Z0-9\/\-_]{3,20})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def extract_date(text: str) -> Optional[str]:
    patterns = [
        r'\b(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})\b',
        r'\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b',
        r'\b(\d{4})[\/\-](\d{2})[\/\-](\d{2})\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return None

def extract_amounts(text: str) -> dict:
    """Extract CGST, SGST, IGST, taxable value, and total from text."""
    result = {}

    amount_patterns = {
        # Match CGST/SGST/IGST followed by optional rate then Rs/amount — amount must be >100 to avoid capturing rates
        "cgst":          r'(?:CGST|Central\s*GST)\s*(?:@\s*[\d\.]+\s*%\s*)?[:\-]?\s*(?:Rs\.?|INR|₹)\s*([\d,]{3,}(?:\.\d{1,2})?)',
        "sgst":          r'(?:SGST|State\s*GST)\s*(?:@\s*[\d\.]+\s*%\s*)?[:\-]?\s*(?:Rs\.?|INR|₹)\s*([\d,]{3,}(?:\.\d{1,2})?)',
        "igst":          r'(?:IGST|Integrated\s*GST)\s*(?:@\s*[\d\.]+\s*%\s*)?[:\-]?\s*(?:Rs\.?|INR|₹)\s*([\d,]{3,}(?:\.\d{1,2})?)',
        "taxable_value": r'(?:Taxable\s*(?:Value|Amount)|Taxable)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]{3,}(?:\.\d{1,2})?)',
        "total_amount":  r'(?:Total\s*(?:Invoice\s*Value|Amount|Value)|Grand\s*Total|Invoice\s*Total)\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]{3,}(?:\.\d{1,2})?)',
    }

    for key, pattern in amount_patterns.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", "").strip()
            try:
                result[key] = float(raw)
            except ValueError:
                pass

    return result

def extract_hsn(text: str) -> Optional[str]:
    """Extract HSN/SAC code (4, 6, or 8 digits)."""
    patterns = [
        r'(?:HSN\s*(?:Code|/SAC)?|SAC\s*(?:Code)?)\s*[:\-]?\s*(\d{4,8})',
        r'\bHSN\s*[:\-]?\s*(\d{4,8})\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


# ── Confidence scoring ────────────────────────────────────────────────────────

CONFIDENCE_THRESHOLD = 0.80

def score_gstin(gstin: Optional[str], ocr_conf: float = 1.0) -> ExtractedField:
    if not gstin:
        return ExtractedField(None, 0.0, True)
    base = 0.85 if validate_gstin(gstin) else 0.35
    conf = round(min(base * ocr_conf, 1.0), 2)
    return ExtractedField(gstin, conf, conf < CONFIDENCE_THRESHOLD)

def score_text_field(value: Optional[str], ocr_conf: float = 1.0, base: float = 0.85) -> ExtractedField:
    if not value:
        return ExtractedField(None, 0.0, True)
    conf = round(min(base * ocr_conf, 1.0), 2)
    return ExtractedField(value, conf, conf < CONFIDENCE_THRESHOLD)

def score_amount(value: Optional[float], ocr_conf: float = 1.0) -> ExtractedField:
    if value is None:
        return ExtractedField(None, 0.0, True)
    # Sanity check — amounts shouldn't be negative or absurdly large
    if value < 0 or value > 1e8:
        return ExtractedField(str(value), 0.30, True)
    conf = round(min(0.88 * ocr_conf, 1.0), 2)
    str_val = f"₹ {value:,.2f}"
    return ExtractedField(str_val, conf, conf < CONFIDENCE_THRESHOLD)


# ── Document type classifier ──────────────────────────────────────────────────

def classify_document(filepath: str) -> tuple[str, str]:
    """Returns (doc_type, source_type)"""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext == ".xlsx" or ext == ".csv":
        return "xlsx", "bank_statement"
    if ext == ".json":
        return "json", "gstr_json"
    if ext == ".xml":
        return "xml", "tally_xml"
    if ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return "image", "invoice"

    if ext == ".pdf":
        doc = fitz.open(filepath)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) > 150:
            return "digital_pdf", "invoice"
        else:
            return "scanned_pdf", "invoice"

    return "unknown", "unknown"


# ── Image preprocessing ───────────────────────────────────────────────────────

def preprocess_image(image: Image.Image) -> Image.Image:
    """Enhance image quality before OCR — handles low-res scans."""
    # Convert to grayscale
    image = image.convert("L")
    # Increase contrast
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)
    # Sharpen
    image = image.filter(ImageFilter.SHARPEN)
    # Upscale small images (Tesseract works better at 300 DPI)
    w, h = image.size
    if w < 1000:
        scale = 1000 / w
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return image


# ── OCR runners ───────────────────────────────────────────────────────────────

def ocr_image(image: Image.Image) -> tuple[str, float]:
    """Run Tesseract OCR on a PIL image. Returns (text, avg_confidence)."""
    image = preprocess_image(image)

    # Get text + confidence data
    data = pytesseract.image_to_data(
        image,
        lang="eng",
        config="--psm 6 --oem 3",
        output_type=pytesseract.Output.DICT
    )

    words, confs = [], []
    for word, conf in zip(data["text"], data["conf"]):
        if str(conf) != "-1" and word.strip():
            words.append(word)
            confs.append(int(conf))

    text = " ".join(words)
    avg_conf = (sum(confs) / len(confs) / 100) if confs else 0.5
    return text, round(avg_conf, 2)

def extract_from_image_file(filepath: str) -> tuple[str, float]:
    img = Image.open(filepath)
    return ocr_image(img)

def extract_from_scanned_pdf(filepath: str) -> tuple[str, float]:
    """Convert each PDF page to image and OCR it."""
    doc = fitz.open(filepath)
    all_text, all_confs = [], []
    for page in doc:
        # Render page at 300 DPI
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text, conf = ocr_image(img)
        all_text.append(text)
        all_confs.append(conf)
    doc.close()
    combined = "\n".join(all_text)
    avg = round(sum(all_confs) / len(all_confs), 2) if all_confs else 0.5
    return combined, avg

def extract_from_digital_pdf(filepath: str) -> tuple[str, float]:
    """Directly extract text from a digital PDF — no OCR needed."""
    doc = fitz.open(filepath)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text, 0.99  # Near-perfect confidence for digital PDFs


# ── Structured format parsers ─────────────────────────────────────────────────

def parse_xlsx_bank_statement(filepath: str) -> ExtractionResult:
    """Parse bank statement XLSX. Maps common bank column formats."""
    result = ExtractionResult(
        filename=Path(filepath).name,
        doc_type="xlsx",
        source_type="bank_statement"
    )
    try:
        df = pd.read_excel(filepath, header=None)
        # Find header row (look for date/amount keywords)
        header_row = 0
        for i, row in df.iterrows():
            row_str = " ".join(str(v).lower() for v in row.values)
            if any(k in row_str for k in ["date", "amount", "debit", "credit", "narration", "description"]):
                header_row = i
                break

        df = pd.read_excel(filepath, header=header_row)
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Normalize column names across different bank formats
        col_map = {
            "txn date": "date", "transaction date": "date", "value date": "date",
            "withdrawal amt.": "debit", "withdrawal amount": "debit", "debit": "debit",
            "deposit amt.": "credit", "deposit amount": "credit", "credit": "credit",
            "description": "narration", "particulars": "narration", "narration": "narration",
            "balance": "balance",
        }
        df = df.rename(columns={c: col_map.get(c, c) for c in df.columns})
        df = df.dropna(how="all")

        # Convert to line items
        for _, row in df.iterrows():
            item = LineItem(
                description=str(row.get("narration", row.get("description", ""))),
                hsn_code=None,
                quantity=None,
                rate=None,
                amount=str(row.get("debit") or row.get("credit", "")),
                taxable_value=None,
                gst_rate=None,
            )
            result.line_items.append(item)

        result.raw_text = df.to_string()
    except Exception as e:
        result.errors.append(f"XLSX parse error: {e}")
    return result

def parse_gstr_json(filepath: str) -> ExtractionResult:
    """Parse GSTR-1 / GSTR-2B JSON export from GST portal."""
    result = ExtractionResult(
        filename=Path(filepath).name,
        doc_type="json",
        source_type="gstr_json"
    )
    try:
        with open(filepath) as f:
            data = json.load(f)

        # Extract filing GSTIN
        gstin = data.get("gstin", data.get("ctin", ""))
        if gstin:
            result.supplier_gstin = score_gstin(gstin, 1.0)

        # Parse B2B invoices (standard GSTR schema)
        invoices = data.get("b2b", [])
        for supplier in invoices:
            supplier_gstin = supplier.get("ctin", "")
            for inv in supplier.get("inv", []):
                item = LineItem(
                    description=f"Invoice {inv.get('inum', '')}",
                    hsn_code=None,
                    quantity=None,
                    rate=None,
                    amount=str(inv.get("val", "")),
                    taxable_value=str(inv.get("itms", [{}])[0].get("itm_det", {}).get("txval", "")),
                    gst_rate=str(inv.get("itms", [{}])[0].get("itm_det", {}).get("rt", "")),
                )
                result.line_items.append(item)

        result.raw_text = json.dumps(data, indent=2)
    except Exception as e:
        result.errors.append(f"GSTR JSON parse error: {e}")
    return result

def parse_tally_xml(filepath: str) -> ExtractionResult:
    """Parse Tally Prime XML export."""
    result = ExtractionResult(
        filename=Path(filepath).name,
        doc_type="xml",
        source_type="tally_xml"
    )
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        for voucher in root.iter("VOUCHER"):
            v_type = voucher.find("VOUCHERTYPENAME")
            if v_type is not None and "purchase" in v_type.text.lower():
                inv_no = voucher.find("VOUCHERNUMBER")
                date   = voucher.find("DATE")
                amount = voucher.find("AMOUNT")

                item = LineItem(
                    description=f"Voucher {inv_no.text if inv_no is not None else ''}",
                    hsn_code=None,
                    quantity=None,
                    rate=None,
                    amount=amount.text if amount is not None else "",
                    taxable_value=None,
                    gst_rate=None,
                )
                result.line_items.append(item)

        result.raw_text = ET.tostring(root, encoding="unicode")
    except Exception as e:
        result.errors.append(f"Tally XML parse error: {e}")
    return result


# ── Main field extraction from raw text ──────────────────────────────────────

def extract_fields_from_text(text: str, ocr_confidence: float, filename: str, doc_type: str) -> ExtractionResult:
    """Given raw text from OCR or PDF, extract all invoice fields."""
    result = ExtractionResult(
        filename=filename,
        doc_type=doc_type,
        source_type="invoice",
        raw_text=text,
    )

    # GSTINs — first one is usually supplier, second is buyer
    gstins = extract_gstins(text)
    if len(gstins) >= 1:
        result.supplier_gstin = score_gstin(gstins[0], ocr_confidence)
    if len(gstins) >= 2:
        result.buyer_gstin = score_gstin(gstins[1], ocr_confidence)

    # Invoice number
    inv_no = extract_invoice_number(text)
    result.invoice_number = score_text_field(inv_no, ocr_confidence, base=0.88)

    # Date
    date = extract_date(text)
    result.invoice_date = score_text_field(date, ocr_confidence, base=0.90)

    # Amounts
    amounts = extract_amounts(text)
    result.taxable_value = score_amount(amounts.get("taxable_value"), ocr_confidence)
    result.cgst          = score_amount(amounts.get("cgst"),          ocr_confidence)
    result.sgst          = score_amount(amounts.get("sgst"),          ocr_confidence)
    result.igst          = score_amount(amounts.get("igst"),          ocr_confidence)
    result.total_amount  = score_amount(amounts.get("total_amount"),  ocr_confidence)

    # HSN code
    hsn = extract_hsn(text)
    result.hsn_code = score_text_field(hsn, ocr_confidence, base=0.80)

    return result


# ── Master pipeline entry point ───────────────────────────────────────────────

def process_document(filepath: str) -> ExtractionResult:
    """
    Main entry point. Takes any file path, auto-detects type,
    runs appropriate pipeline, returns structured ExtractionResult.
    """
    doc_type, source_type = classify_document(filepath)
    filename = Path(filepath).name

    print(f"[TaxMind] Processing: {filename} | Type: {doc_type}")

    # ── Structured formats — no OCR needed ──
    if doc_type == "xlsx":
        return parse_xlsx_bank_statement(filepath)

    if doc_type == "json":
        return parse_gstr_json(filepath)

    if doc_type == "xml":
        return parse_tally_xml(filepath)

    # ── Image-based — OCR pipeline ──
    if doc_type == "image":
        text, conf = extract_from_image_file(filepath)
    elif doc_type == "scanned_pdf":
        text, conf = extract_from_scanned_pdf(filepath)
    elif doc_type == "digital_pdf":
        text, conf = extract_from_digital_pdf(filepath)
    else:
        result = ExtractionResult(filename=filename, doc_type="unknown", source_type="unknown")
        result.errors.append(f"Unsupported file format: {Path(filepath).suffix}")
        return result

    return extract_fields_from_text(text, conf, filename, doc_type)
