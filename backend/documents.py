import csv
import hashlib
import io
import json
import re
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from fastapi import HTTPException
from .db import ROOT, connect, audit

ALLOWED={'.pdf','.txt','.csv','.json','.docx','.xlsx'}
MAX_UPLOAD=20*1024*1024

def validate_file(name, content):
    suffix=Path(name).suffix.lower()
    if suffix not in ALLOWED: raise HTTPException(422,'Supported files: PDF, TXT, CSV, JSON, DOCX, XLSX')
    if not content or len(content)>MAX_UPLOAD: raise HTTPException(413,'File must be between 1 byte and 20 MB')
    if suffix in {'.docx','.xlsx'}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if len(z.infolist())>5000 or sum(i.file_size for i in z.infolist())>100*1024*1024:
                    raise HTTPException(413,'Expanded Office document is too large')
                if any('vbaproject' in i.filename.lower() for i in z.infolist()):
                    raise HTTPException(422,'Macro-enabled documents are not accepted')
        except zipfile.BadZipFile:
            raise HTTPException(422,'Invalid Office document')
    if suffix=='.pdf' and not content.startswith(b'%PDF-'): raise HTTPException(422,'Invalid PDF header')
    return suffix

def ingest(c, project, name, content, actor=None):
    suffix=validate_file(name,content)
    sha=hashlib.sha256(content).hexdigest()
    existing=c.execute('SELECT id FROM documents WHERE project_id=? AND sha256=?',(project,sha)).fetchone()
    if existing: return {'id':existing['id'],'duplicate':True}
    did=uuid.uuid4().hex
    path=ROOT/'uploads'/(did+suffix)
    path.write_bytes(content)
    path.chmod(0o600)
    c.execute('INSERT INTO documents(id,project_id,name,sha256,size,status,created,created_by) VALUES(?,?,?,?,?,?,?,?)',(did,project,Path(name).name[:240],sha,len(content),'queued',time.time(),actor))
    c.execute('INSERT INTO jobs(id,project_id,kind,target,status,created) VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,project,'document',did,'queued',time.time()))
    audit(c,project,actor,'document.uploaded',did,{'name':Path(name).name,'sha256':sha})
    return {'id':did,'duplicate':False}

def file_path(doc):
    return ROOT/'uploads'/(doc['id']+Path(doc['name']).suffix.lower())

def extract(path):
    suffix=path.suffix.lower()
    pages=[]
    if suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if reader.is_encrypted: raise ValueError('Encrypted PDF: upload an unlocked copy')
        if len(reader.pages)>50: raise ValueError('PDF limit is 50 pages; split the document')
        for n,page in enumerate(reader.pages,1):
            text=page.extract_text() or ''
            if len(text.strip())<35:
                with tempfile.TemporaryDirectory() as tmp:
                    stem=Path(tmp)/'page'
                    subprocess.run(['pdftoppm','-f',str(n),'-l',str(n),'-singlefile','-scale-to','2200','-png',str(path),str(stem)],check=True,capture_output=True,timeout=45)
                    result=subprocess.run(['tesseract',str(stem)+'.png','stdout','-l','eng'],check=True,capture_output=True,text=True,timeout=60)
                    text=result.stdout
            pages.append((n,text))
    elif suffix=='.docx':
        from docx import Document
        doc=Document(path)
        text='\n'.join([p.text for p in doc.paragraphs]+[' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows])
        pages=[(1,text)]
    elif suffix=='.xlsx':
        from openpyxl import load_workbook
        book=load_workbook(path,read_only=True,data_only=True)
        try:
            total=0
            for n,sheet in enumerate(book.worksheets,1):
                lines=[f'Worksheet: {sheet.title}']
                for row in sheet.iter_rows(values_only=True):
                    total+=1
                    if total>20000: raise ValueError('Spreadsheet limit is 20,000 rows')
                    lines.append(' | '.join(str(x or '') for x in row[:100]))
                pages.append((n,'\n'.join(lines)))
        finally: book.close()
    else:
        text=path.read_text(encoding='utf-8-sig',errors='replace')
        if suffix=='.json': text=json.dumps(json.loads(text),indent=2,ensure_ascii=False)
        pages=[(1,text)]
    if sum(len(t) for _,t in pages)>2_000_000: raise ValueError('Extracted text exceeds 2 million characters')
    if not any(t.strip() for _,t in pages): raise ValueError('No readable text found; check scan quality or language (English OCR)')
    return pages

PATTERNS={
    'component_code': (r'(?:component\s*code|material\s*code|bottle\s*code)\s*[:=]\s*([\w.-]+)',''),
    'weight_g': (r'(?:weight|mass)(?:\s*\(g\))?\s*[:=]\s*([\d.]+)\s*(?:g\b|grams?\b)?','g'),
    'capacity_ml': (r'(?:capacity|volume)(?:\s*\(ml\))?\s*[:=]\s*([\d.]+)\s*(?:ml\b)?','ml'),
    'material': (r'(?:resin|material)\s*[:=]\s*(PET|HDPE|LDPE|PP|PVC|GLASS|PAPER|ALUMINIUM)\b',''),
    'neck': (r'(?:neck|neck\s*finish)\s*[:=]\s*([\w.-]+)',''),
    'revision': (r'revision\s*[:=]\s*([\w.-]+)',''),
    'supplier': (r'supplier\s*[:=]\s*([^\n|]{1,150})',''),
    'price': (r'(?:unit\s*price|price)\s*[:=]\s*(?:INR|USD|EUR|GBP|NGN|₹|\$)?\s*([\d.]+)','per component'),
    'currency': (r'currency\s*[:=]\s*(INR|USD|EUR|GBP|NGN)\b','')}

def process_document(did):
    with connect(write=True) as c:
        doc=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not doc: return
        c.execute("UPDATE documents SET status='processing',error=NULL WHERE id=?",(did,))
    pages=extract(file_path(doc))
    with connect(write=True) as c:
        c.execute('DELETE FROM chunks WHERE document_id=?',(did,))
        c.execute('DELETE FROM fields WHERE document_id=?',(did,))
        for page,text in pages:
            # Keep page and overlapping excerpts; identifiers remain tied to the source file hash.
            for start in range(0,len(text),1800):
                chunk=text[start:start+2000].strip()
                if chunk: c.execute('INSERT INTO chunks(document_id,page,text) VALUES(?,?,?)',(did,page,chunk))
            for name,(pattern,unit) in PATTERNS.items():
                for match in list(re.finditer(pattern,text,re.I))[:20]:
                    value=match.group(1).strip()
                    c.execute('INSERT INTO fields(document_id,name,proposed,value,unit,page) VALUES(?,?,?,?,?,?)',(did,name,value,value,unit,page))
        c.execute("UPDATE documents SET status='review',error=NULL WHERE id=?",(did,))
        audit(c,doc['project_id'],None,'document.extracted',did,{'pages':len(pages),'method':'text+English-OCR fallback'})

def search(c, project, query, approved=True, limit=10):
    terms=re.findall(r'[\w-]{2,}',query)[:16]
    if not terms: return []
    expression=' OR '.join('"'+x.replace('"','')+'"' for x in terms)
    rows=c.execute('''SELECT ch.id,ch.document_id,ch.page,ch.text,d.name,d.status,d.sha256,bm25(chunk_search) score
        FROM chunk_search JOIN chunks ch ON ch.id=chunk_search.rowid JOIN documents d ON d.id=ch.document_id
        WHERE chunk_search MATCH ? AND d.project_id=? AND (?=0 OR d.status='approved') ORDER BY score LIMIT ?''',(expression,project,int(approved),limit)).fetchall()
    return [dict(r) for r in rows]
