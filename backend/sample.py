"""Synthetic fixtures pass through the same upload, extraction and review pipeline."""
import csv
import io
import time
from datetime import date, timedelta
from .db import audit
from .documents import ingest

def csv_bytes(rows):
    stream=io.StringIO()
    writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode()

def create_sample(c,actor,name='ClearCare • synthetic case study'):
    valid_from=date.today().isoformat()
    valid_until=(date.today()+timedelta(days=60)).isoformat()
    pid=c.execute('INSERT INTO projects(name,synthetic,sample_template,created) VALUES(?,?,?,?)',(name,1,'clearcare',time.time())).lastrowid
    c.execute('INSERT INTO members VALUES(?,?,?)',(pid,actor,'reviewer'))
    components=[
        {'code':'BOT-104','name':'ClearCare PET bottle 250 ml','supplier':'Himalaya Packaging (fictional)','material':'PET','capacity_ml':250,'neck':'N24-A','weight_g':18,'price':5.20,'currency':'INR','revision':'R6','state':'approved'},
        {'code':'BOT-209','name':'Lightweight candidate bottle','supplier':'Valley Polymers (fictional)','material':'PET','capacity_ml':250,'neck':'N24-A','weight_g':16,'price':4.90,'currency':'INR','revision':'C2','state':'candidate'},
        {'code':'BOT-331','name':'Different neck bottle','supplier':'Valley Polymers (fictional)','material':'PET','capacity_ml':250,'neck':'N28-B','weight_g':17,'price':4.75,'currency':'INR','revision':'C1','state':'candidate'}]
    products=[]
    for row in components:
        row['price_valid_from']=valid_from
        row['price_valid_until']=valid_until
    for n in range(1,21):
        products.append({'sku':f'SH-250-{n:03}','name':f'ClearCare shampoo variant {n:02}',
            'annual_units':2000000 if n==1 else 3000000 if n in (2,3) else 100000+n*10000,
            'plant':'Plant A' if n<=10 else 'Plant B','formula':'Formula Alpha' if n<=3 else f'Formula {n:02}',
            'component_code':'BOT-104' if n<=3 else 'BOT-331','quantity':1})
    files=[('01-components.csv',csv_bytes(components)),('02-products.csv',csv_bytes(products)),
        ('03-BOT104-R6-current-spec.txt',b'SYNTHETIC TRAINING DATA - not a real supplier specification\nComponent code: BOT-104\nRevision: R6\nSupplier: Himalaya Packaging (fictional)\nMaterial: PET\nCapacity: 250 ml\nNeck finish: N24-A\nWeight: 18 g\nUnit price: INR 5.20\nCurrency: INR\nPrice basis: per bottle, valid 2026-11-01 to 2026-12-31, Plant A; tax excluded.\nThis current specification supersedes revision R4.\n'),
        ('04-BOT104-R4-historical.txt',b'SYNTHETIC HISTORICAL REFERENCE - superseded, do not treat as current\nComponent code: BOT-104\nRevision: R4\nWeight: 19 g\nMaterial: PET\nCapacity: 250 ml\nNeck finish: N24-A\nSupplier: Himalaya Packaging (fictional)\nSuperseded by revision R6; current weight is 18 g.\n'),
        ('05-candidate-and-commercial-assumptions.txt',b'SYNTHETIC SCENARIO ASSUMPTIONS\nComponent code: BOT-209\nRevision: C2\nSupplier: Valley Polymers (fictional)\nMaterial: PET\nCapacity: 250 ml\nNeck finish: N24-A\nWeight: 16 g\nUnit price: INR 4.90\nCurrency: INR\nCandidate is not qualified on the basis of this document.\nScope: SH-250-001, SH-250-002 and SH-250-003 at Plant A with Formula Alpha.\nForecast: 8,000,000 bottles annually. Extra logistics INR 0.02 per bottle; one-time transition INR 400,000.\nPrices valid 2026-11-01 to 2026-12-31; tax excluded; same delivery basis.\n'),
        ('06-synthetic-trial-evidence.txt',b'SYNTHETIC DEMONSTRATION TEST REPORT - no real engineering testing took place\nScope: BOT-104 R6 replacement by BOT-209 C2, SH-250-001/002/003, Plant A, Formula Alpha.\nFictional results for workflow demonstration: fit and seal passed, Plant A line trial passed, formula compatibility passed.\nReal deployment must replace this with actual test evidence reviewed by qualified customer personnel.\n'),
        ('07-synthetic-implementation-receipt.txt',b'SYNTHETIC IMPLEMENTATION RECEIPT - demonstration only\nFictional change CC-2026-001 implemented at Plant A for SH-250-001/002/003 replacing BOT-104 R6 with BOT-209 C2.\nThis is not an SAP transaction, and no real production change or realised savings is asserted.\n'),
        ('08-synthetic-actual-benefit-evidence.txt',b'SYNTHETIC ACTUALS FOR WORKFLOW DEMONSTRATION ONLY\nPeriod: 2026-11-01 through 2026-11-04\nScope: BOT-104 R6 to BOT-209 C2, SH-250-001/002/003, Plant A, Formula Alpha.\nCurrency: INR\nActual component units: 10000\nVerified counterfactual baseline unit price: 5.20\nActual paid unit price: 4.90\nTotal extra operating cost for period: 200\nTransition cost charged in this period: 0\nFictional period net benefit: 2800.\nThese are generated test figures, not actual transactions or realised commercial savings.\n')]
    docs=[]
    for name,content in files:
        if name.startswith(('03-','05-')):
            content=content.replace(b'2026-11-01 to 2026-12-31',f'{valid_from} to {valid_until}'.encode())
        docs.append({**ingest(c,pid,name,content,actor),'name':name})
    audit(c,pid,actor,'sample.created',pid,{'synthetic':True,'documents':len(docs)})
    return {'id':pid,'documents':docs,'next':'Review documents, import components from 01-components.csv, then import products from 02-products.csv. All records are synthetic.'}
