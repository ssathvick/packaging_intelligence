import hashlib
import json
import time
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException

QUALIFICATIONS=('fit_seal','line_trial','formula_compatibility')

def decoded_component(row):
    result=dict(row)
    result['attributes']=json.loads(result['attributes']) if isinstance(result.get('attributes'),str) else result.get('attributes',{})
    return result

def fingerprint_component(comp):
    result=dict(comp)
    # Preserve existing bottle fingerprints when migration only adds defaults.
    if result.get('component_type','bottle')=='bottle' and result.get('uom','piece')=='piece' and not result.get('attributes'):
        for key in ('component_type','uom','attributes'):result.pop(key,None)
    return result

def opportunities(c,project):
    """Rank cost-screening opportunities; never infer engineering qualification."""
    from datetime import date
    today=date.today()
    reviewed={r['id'] for r in c.execute("SELECT id FROM documents WHERE project_id=? AND status='approved'",(project,))}
    demand={r['component_id']:dict(r) for r in c.execute('''SELECT b.component_id,SUM(p.annual_units*b.quantity) units,COUNT(DISTINCT p.id) skus
        FROM bom b JOIN products p ON p.id=b.product_id WHERE p.project_id=? AND p.archived=0 GROUP BY b.component_id''',(project,))}
    groups={}
    for row in c.execute('SELECT * FROM components WHERE project_id=?',(project,)):
        comp=decoded_component(row)
        try: valid=date.fromisoformat(comp['price_valid_from'])<=today<=date.fromisoformat(comp['price_valid_until'])
        except ValueError: valid=False
        if comp['evidence_id'] not in reviewed or not valid: continue
        key=(comp['component_type'],comp['uom'],comp['material'].casefold(),comp['capacity_ml'],comp['neck'].casefold(),comp['currency'],json.dumps(comp['attributes'],sort_keys=True))
        groups.setdefault(key,[]).append(comp)
    import heapq
    import itertools
    heap=[];counter=itertools.count()
    for group in groups.values():
        group.sort(key=lambda comp:comp['price'])
        for base in group:
            scope=demand.get(base['id'])
            if base['state']!='approved' or not scope or scope['units']<=0: continue
            # Only the cheapest 100 alternatives for a baseline can enter a global top 100.
            for candidate in group[:101]:
                if candidate['id']==base['id'] or candidate['price']>=base['price']: continue
                gross=(Decimal(str(base['price']))-Decimal(str(candidate['price'])))*Decimal(str(scope['units']))
                row={'baseline_id':base['id'],'baseline_code':base['code'],'candidate_id':candidate['id'],'candidate_code':candidate['code'],
                    'annual_units':scope['units'],'uom':base['uom'],'affected_skus':scope['skus'],'currency':base['currency'],'gross_annual_potential':money(gross),
                    'material_tonnes':float((Decimal(str(base['weight_g']))-Decimal(str(candidate['weight_g'])))*Decimal(str(scope['units']))/Decimal('1000000')),
                    'status':'unqualified','basis':'Attribute and current-price screening only. Extra costs, transition costs and engineering qualification not included.'}
                entry=(gross,next(counter),row)
                if len(heap)<100:heapq.heappush(heap,entry)
                else:heapq.heappushpop(heap,entry)
    results=[entry[2] for entry in heap]
    results.sort(key=lambda x:x['gross_annual_potential'],reverse=True)
    return results[:100]

def money(v): return float(Decimal(str(v)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))

def evidence(c, project, did):
    row=c.execute("SELECT * FROM documents WHERE id=? AND project_id=? AND status='approved'",(did,project)).fetchone()
    if not row: raise HTTPException(422,'A reviewed, approved document in this project is required')
    return dict(row)

def component(c, project, cid):
    row=c.execute('SELECT * FROM components WHERE project_id=? AND id=?',(project,cid)).fetchone()
    if not row: raise HTTPException(404,'Component not found')
    return decoded_component(row)

def evaluate(c, s):
    base=component(c,s['project_id'],s['baseline_id'])
    candidate=component(c,s['project_id'],s['candidate_id'])
    inputs=json.loads(s['inputs'])
    checks=[]
    for field in ('component_type','uom','material','capacity_ml','neck','currency'):
        a,b=base[field],candidate[field]
        checks.append({'attribute':field,'baseline':a,'candidate':b,'passed':str(a).casefold()==str(b).casefold()})
    for key in sorted(set(base['attributes'])|set(candidate['attributes'])):
        a,b=base['attributes'].get(key),candidate['attributes'].get(key)
        checks.append({'attribute':'spec_'+key,'baseline':a,'candidate':b,'passed':a is not None and b is not None and a==b})
    checks.append({'attribute':'different_component','baseline':base['code'],'candidate':candidate['code'],'passed':base['id']!=candidate['id']})
    checks.append({'attribute':'approved_baseline','baseline':base['state'],'candidate':candidate['state'],'passed':base['state']=='approved'})
    for label,comp in [('baseline',base),('candidate',candidate)]:
        source=c.execute('SELECT status FROM documents WHERE id=? AND project_id=?',(comp['evidence_id'],s['project_id'])).fetchone()
        checks.append({'attribute':label+'_reviewed_source','baseline':comp['evidence_id'],'candidate':source['status'] if source else 'missing','passed':bool(source and source['status']=='approved')})
        from datetime import date
        try:
            valid=date.fromisoformat(comp['price_valid_from'])<=date.today()<=date.fromisoformat(comp['price_valid_until'])
        except (ValueError,KeyError): valid=False
        checks.append({'attribute':label+'_price_validity','baseline':comp.get('price_valid_from',''),'candidate':comp.get('price_valid_until',''),'passed':valid})
    units=Decimal(str(inputs['annual_units']))
    gross=(Decimal(str(base['price']))-Decimal(str(candidate['price'])))*units
    logistics=Decimal(str(inputs['extra_per_unit']))*units
    transition=Decimal(str(inputs['transition_cost']))
    mass=(Decimal(str(base['weight_g']))-Decimal(str(candidate['weight_g'])))*units/Decimal('1000000')
    products=[dict(r) for r in c.execute('''SELECT p.*,b.quantity FROM products p JOIN bom b ON b.product_id=p.id WHERE b.component_id=? AND p.project_id=? AND p.archived=0 ORDER BY p.sku''',(base['id'],s['project_id']))]
    checks.append({'attribute':'linked_sku_scope','baseline':len(products),'candidate':'at least one linked SKU required','passed':bool(products)})
    qualified=json.loads(s['qualifications'])
    scope_products=[]
    for product in products:
        product=dict(product);product.pop('archived',None)
        if product.get('version')==1:product.pop('version',None)
        scope_products.append(product)
    scope={'baseline':fingerprint_component(base),'candidate':fingerprint_component(candidate),'inputs':inputs,'products':scope_products}
    fingerprint=hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()
    valid_qual={}
    for key in QUALIFICATIONS:
        q=qualified.get(key)
        valid=False
        if q and q.get('passed') and q.get('fingerprint')==fingerprint:
            source=c.execute("SELECT 1 FROM documents WHERE id=? AND project_id=? AND status='approved'",(q.get('evidence_id'),s['project_id'])).fetchone()
            valid=bool(source)
        valid_qual[key]={'valid':valid,'record':q}
    eligible=all(x['passed'] for x in checks)
    all_qualified=all(q['valid'] for q in valid_qual.values())
    current_approval=bool(s['approved_fingerprint']==fingerprint and eligible and all_qualified)
    return {'baseline':base,'candidate':candidate,'checks':checks,'eligible':eligible,'qualification_complete':all_qualified,
            'qualifications':valid_qual,'fingerprint':fingerprint,'approval_current':current_approval,
            'can_approve':eligible and all_qualified and s['status'] in ('draft','qualified','approved'),
            'financials':{'currency':base['currency'],'uom':base['uom'],'annual_units':float(units),'gross_annual':money(gross),'annual_extra':money(logistics),
                          'transition':money(transition),'first_year_net':money(gross-logistics-transition),
                          'recurring_annual_net':money(gross-logistics),'material_tonnes':float(mass)},
            'affected_products':products,'annual_component_demand':sum(p['annual_units']*p['quantity'] for p in products),
            'assumptions':inputs,'limitations':['Attribute compatibility is screening only; qualification requires evidence for this SKU, plant and formula scope.',
                'Financial results are estimates from entered prices, forecast and assumptions; not realised savings.','Material reduction is mass only, not a verified carbon or environmental claim.']}

def scenario_row(c, project, sid):
    row=c.execute('SELECT * FROM scenarios WHERE id=? AND project_id=?',(sid,project)).fetchone()
    if not row: raise HTTPException(404,'Scenario not found')
    return dict(row)

def invalidate(c, project, reason, document_id=None):
    # Conservative project-level invalidation prevents stale approvals after catalog or evidence changes.
    if document_id:
        ids=[]
        for s in c.execute("SELECT * FROM scenarios WHERE project_id=? AND status!='implemented'",(project,)):
            comp_ids=[s['baseline_id'],s['candidate_id']]
            linked=c.execute('SELECT 1 FROM components WHERE id IN (?,?) AND evidence_id=?',(*comp_ids,document_id)).fetchone()
            qualifications=json.loads(s['qualifications'])
            if linked or any(q.get('evidence_id')==document_id for q in qualifications.values()): ids.append(s['id'])
        for sid in ids:
            c.execute("UPDATE scenarios SET status='draft',approved_by=NULL,approved_at=NULL,approved_fingerprint=NULL,qualifications='{}',version=version+1 WHERE id=?",(sid,))
    else:
        c.execute("UPDATE scenarios SET status='draft',approved_by=NULL,approved_at=NULL,approved_fingerprint=NULL,qualifications='{}',version=version+1 WHERE project_id=? AND status NOT IN ('implemented')",(project,))
