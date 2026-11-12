"""Local-first invoice reconciliation API with deterministic Decimal calculations."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import JSON, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA = Path(os.getenv("INVOICE_DISCREPANCY_DETECTOR_DATA", "./data")); DATA.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DATA / 'invoice-discrepancy-detector.db'}", connect_args={"check_same_thread": False})
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, unique=True, index=True)
    path: Mapped[str] = mapped_column(String)
class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice: Mapped[dict] = mapped_column(JSON)
    po: Mapped[dict] = mapped_column(JSON)
    receipt: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    review: Mapped[str] = mapped_column(String, default="open")
    notes: Mapped[list] = mapped_column(JSON, default=list)
class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON)
Base.metadata.create_all(engine)
app = FastAPI(title="Invoice Discrepancy Detector", description="Investigate invoice discrepancies with traceable evidence")

class Line(BaseModel):
    sku: str | None = None
    description: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
class Record(BaseModel):
    number: str | None = None
    po_number: str | None = None
    supplier: str | None = None
    currency: str = "USD"
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    lines: list[Line] = Field(default_factory=list)
class Request(BaseModel):
    invoice: Record
    po: Record
    receipt: Record | None = None
    price_tolerance: Decimal = Decimal("0.01")
    quantity_tolerance: Decimal = Decimal(0)

def reconcile(req: Request) -> dict[str, Any]:
    inv, po, receipt = req.invoice, req.po, req.receipt
    issues: list[dict[str, Any]] = []; matches=[]
    if inv.currency != po.currency:
        issues.append({"type":"currency_mismatch","message":f"Invoice currency {inv.currency} differs from PO currency {po.currency}"})
    if inv.po_number and po.number and inv.po_number.strip().casefold() != po.number.strip().casefold():
        issues.append({"type":"po_reference_mismatch","message":"Invoice PO reference does not match this purchase order"})
    for il in inv.lines:
        candidates=[pl for pl in po.lines if (il.sku and pl.sku and il.sku.casefold()==pl.sku.casefold()) or (il.description and il.description.casefold()==pl.description.casefold())]
        if not candidates:
            issues.append({"type":"unmatched_line","message":f"No PO line found for {il.description or il.sku or 'invoice line'}"}); continue
        pl=candidates[0]; matches.append({"invoice_line":il.model_dump(mode="json"),"po_line":pl.model_dump(mode="json")})
        qty=il.quantity or Decimal(1)
        if il.unit_price is not None and pl.unit_price is not None and abs(il.unit_price-pl.unit_price)>req.price_tolerance:
            delta=(il.unit_price-pl.unit_price)*qty
            issues.append({"type":"price_mismatch","message":f"Invoice price differs from PO by {inv.currency} {delta}","calculation":f"{qty} × ({il.unit_price} − {pl.unit_price}) = {delta}","evidence":{"invoice_line":il.model_dump(mode="json"),"po_line":pl.model_dump(mode="json")}})
        if il.quantity is not None and pl.quantity is not None and il.quantity-pl.quantity>req.quantity_tolerance:
            issues.append({"type":"quantity_mismatch","message":f"Invoiced quantity {il.quantity} exceeds ordered quantity {pl.quantity}"})
        if receipt:
            received=sum((x.quantity or Decimal(0) for x in receipt.lines if (il.sku and x.sku and il.sku.casefold()==x.sku.casefold()) or x.description.casefold()==il.description.casefold()),Decimal(0))
            if il.quantity is not None and il.quantity-received>req.quantity_tolerance:
                issues.append({"type":"receipt_quantity_mismatch","message":f"Invoice quantity {il.quantity} exceeds received quantity {received}"})
    if receipt is None: issues.append({"type":"receipt_missing","message":"Receipt record is missing"})
    if inv.total is not None and inv.subtotal is not None and inv.tax is not None and abs(inv.total-inv.subtotal-inv.tax)>req.price_tolerance:
        issues.append({"type":"total_mismatch","message":f"Invoice total {inv.total} does not equal subtotal plus tax ({inv.subtotal+inv.tax})"})
    return {"status":"exception" if issues else "matched","currency":inv.currency,"exceptions":issues,"matches":matches,"explanation":"; ".join(x["message"] for x in issues) if issues else "Invoice matches the supplied PO and receipt.","policy":{"price_tolerance":str(req.price_tolerance),"quantity_tolerance":str(req.quantity_tolerance)}}

@app.get("/api/health")
def health(): return {"status":"ok","database":"sqlite","ai_enabled":False}
@app.post("/api/documents")
async def upload(file: Annotated[UploadFile, File(...)], kind: str="unknown"):
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf",".png",".jpg",".jpeg",".csv",".json"}: raise HTTPException(415,"Use PDF, PNG, JPEG, CSV or JSON")
    data=await file.read(25*1024*1024+1)
    if len(data)>25*1024*1024: raise HTTPException(413,"Maximum upload size is 25 MiB")
    sha=hashlib.sha256(data).hexdigest()
    with Session() as db:
        old=db.scalar(select(Document).where(Document.sha256==sha))
        if old: return {"id":old.id,"sha256":sha,"duplicate":True}
        ident=str(uuid.uuid4()); dest=DATA/"uploads"/f"{ident}{suffix}"; dest.parent.mkdir(exist_ok=True); dest.write_bytes(data)
        doc=Document(id=ident,kind=kind,filename=Path(file.filename or "upload").name,sha256=sha,path=str(dest)); db.add(doc)
        extracted=extract_file(dest, suffix)
        db.commit()
    return {"id":ident,"sha256":sha,"kind":kind,"status":"stored","extraction":extracted}

def extract_file(path: Path, suffix: str) -> dict:
    """Best-effort local text extraction. Never presents guessed fields as facts."""
    try:
        if suffix == ".json":
            value=json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, (dict,list)): return {"status":"needs_review","error":"JSON root must be an object or array"}
            return {"status":"structured_import","data":value,"provenance":{"method":"json","source":path.name}}
        if suffix == ".csv":
            with path.open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
            return {"status":"structured_import","data":rows,"provenance":{"method":"csv","source":path.name,"rows":len(rows)}}
        if suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                if len(pdf.pages)>100: return {"status":"needs_review","error":"PDF exceeds 100-page processing limit"}
                pages=[p.extract_text() or "" for p in pdf.pages]
            return {"status":"text_extracted" if any(pages) else "ocr_required","pages":[{"page":i+1,"text":t} for i,t in enumerate(pages)],"provenance":{"method":"pdfplumber","coordinates":"page text only; no source boxes"}}
    except Exception as exc:  # noqa: BLE001
        return {"status":"needs_review","error":str(exc)[:300]}
    return {"status":"image_ocr_unavailable","message":"Image OCR is not configured; attach structured data or install an OCR adapter."}
@app.get("/api/documents")
def documents():
    with Session() as db: return [{"id":d.id,"kind":d.kind,"filename":d.filename,"sha256":d.sha256} for d in db.scalars(select(Document))]
@app.get("/api/documents/{ident}/file")
def document_file(ident:str):
    with Session() as db: d=db.get(Document,ident)
    if not d: raise HTTPException(404,"Document not found")
    return FileResponse(d.path,filename=d.filename)
@app.post("/api/reconcile")
def run(req:Request):
    result=reconcile(req); ident=str(uuid.uuid4())
    with Session() as db:
        db.add(Case(id=ident,invoice=req.invoice.model_dump(mode="json"),po=req.po.model_dump(mode="json"),receipt=req.receipt.model_dump(mode="json") if req.receipt else {},result=result))
        db.add(Audit(id=str(uuid.uuid4()),case_id=ident,action="reconciliation_created",detail={"status":result["status"]})); db.commit()
    return {"id":ident,**result}
@app.get("/api/cases")
def cases():
    with Session() as db: return [{"id":c.id,"result":c.result,"review":c.review,"invoice":c.invoice} for c in db.scalars(select(Case))]
@app.get("/api/cases/{ident}")
def case(ident:str):
    with Session() as db: c=db.get(Case,ident)
    if not c: raise HTTPException(404,"Case not found")
    return {"id":c.id,"invoice":c.invoice,"po":c.po,"receipt":c.receipt,"result":c.result,"review":c.review,"notes":c.notes}
@app.patch("/api/cases/{ident}/review")
def review(ident:str,payload:dict):
    status=payload.get("status")
    if status not in {"open","approved","rejected","resolved","clarification_requested"}: raise HTTPException(422,"Invalid review status")
    with Session() as db:
        c=db.get(Case,ident)
        if not c: raise HTTPException(404,"Case not found")
        c.review=status
        if payload.get("note"): c.notes=[*c.notes,{"note":str(payload["note"]),"status":status}]
        db.add(Audit(id=str(uuid.uuid4()),case_id=ident,action="review_updated",detail={"status":status,"note":payload.get("note")}))
        db.commit()
    return {"id":ident,"review":status,"notes":c.notes}
@app.get("/api/cases/{ident}/export.json")
def export_json(ident:str): return case(ident)
@app.get("/api/cases/export.csv")
def export_csv():
    with Session() as db: rows=list(db.scalars(select(Case)))
    out=io.StringIO(newline=""); writer=csv.writer(out)
    writer.writerow(["case_id","invoice_number","supplier","status","review","exception_types","explanation"])
    for c in rows:
        vals=[c.id,c.invoice.get("number") or "",c.invoice.get("supplier") or "",c.result.get("status"),c.review,";".join(x.get("type","") for x in c.result.get("exceptions",[])),c.result.get("explanation","")]
        # Prefix spreadsheet formula-leading cells to prevent formula injection.
        writer.writerow([("'"+v if isinstance(v,str) and v.startswith(("=","+","-","@","\t","\r")) else v) for v in vals])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=invoice-discrepancy-detector.csv"})
@app.get("/api/cases/{ident}/audit")
def audit(ident:str):
    with Session() as db: return [{"action":a.action,"detail":a.detail} for a in db.scalars(select(Audit).where(Audit.case_id==ident))]
