import hashlib,json
import pytest
from pydantic import ValidationError
from backend.models import Component
from backend.documents import process_document

def tiny(client):
    pid=client.post('/api/projects',json={'name':'Synthetic kit consolidation','synthetic':True}).json()['id'];base=f'/api/projects/{pid}'
    did=client.post(base+'/documents',files={'file':('kit.txt',b'SYNTHETIC kit specifications and cost allocation. Component code A, PET 250 ml, N24, current synthetic quote.')}).json()['id']
    process_document(did);assert client.post(base+'/documents/'+did+'/review',json={'fields':{},'note':'Reviewed generated test evidence only.'}).status_code==200
    for code,price in [('A',5),('B',6),('C',4)]:
        r=client.post(base+'/components',json={'code':code,'name':code,'material':'PET','capacity_ml':250,'neck':'N24','weight_g':18,'price':price,'currency':'INR','revision':'R1','evidence_id':did,'state':'candidate' if code=='C' else 'approved','price_valid_from':'2020-01-01','price_valid_until':'2099-12-31'})
        assert r.status_code==200,r.text
    comps={x['code']:x for x in client.get(base+'/catalog').json()['components']}
    assert client.post(base+'/products',json={'sku':'KIT-01','name':'Two bottle kit','annual_units':100,'plant':'Synthetic plant','formula':'Synthetic formula','bom':[{'component_code':'A','quantity':1},{'component_code':'B','quantity':2}]}).status_code==200
    ids=[]
    for code,units,cost in [('A',100,10),('B',200,20)]:
        ids.append(client.post(base+'/scenarios',json={'name':'Replace '+code,'baseline_id':comps[code]['id'],'candidate_id':comps['C']['id'],'annual_units':units,'extra_per_unit':0,'transition_cost':cost,'assumption_note':'Synthetic complete kit scope and generated quote.'}).json()['id'])
    body={'name':'Common bottle plan','description':'Two physical components use one standard candidate.','scenario_ids':ids,'shared_transition_cost':50,'cost_note':'Local line costs are separate; shared tooling counted once.','evidence_id':did}
    return base,body,comps

def test_rollup_deduplicates_skus_not_distinct_components(client):
    base,body,_=tiny(client)
    r=client.post(base+'/programmes',json=body);assert r.status_code==200,r.text
    plan=client.get(base+'/programmes/'+r.json()['id']).json()
    assert plan['unique_skus']==1 and plan['finished_unit_forecast']==100
    assert plan['annual_component_demand_by_uom']=={'piece':300}
    assert plan['financials']['gross_annual']==500
    assert plan['financials']['transition']==80 and plan['financials']['first_year_net']==420
    assert plan['common_components'][0]['baseline_count']==2
    assert plan['status']=='awaiting_qualification'

def test_alternative_scenarios_cannot_double_count_baseline(client):
    base,body,comps=tiny(client)
    sid=client.post(base+'/scenarios',json={'name':'Alternative A','baseline_id':comps['A']['id'],'candidate_id':comps['C']['id'],'annual_units':100,'extra_per_unit':0,'transition_cost':0,'assumption_note':'Synthetic alternative to the same physical baseline.'}).json()['id']
    assert client.post(base+'/programmes',json={**body,'scenario_ids':[body['scenario_ids'][0],sid]}).status_code==409
    assert client.post(base+'/programmes',json={**body,'scenario_ids':[sid,sid]}).status_code==422

def test_member_revision_cannot_bypass_rollup_validation(client):
    base,body,comps=tiny(client);gid=client.post(base+'/programmes',json=body).json()['id']
    r=client.put(base+'/scenarios/'+body['scenario_ids'][1],json={'name':'Now alternative A','baseline_id':comps['A']['id'],'candidate_id':comps['C']['id'],'annual_units':100,'extra_per_unit':0,'transition_cost':0,'assumption_note':'Synthetic revision makes the two alternatives mutually exclusive.'});assert r.status_code==200
    plan=client.get(base+'/programmes/'+gid).json()
    assert plan['status']=='blocked' and plan['financials'] is None
    assert client.get(base+'/programmes').status_code==200

def test_bom_demand_mismatch_and_unreviewed_cost_source_block_plan(client):
    base,body,comps=tiny(client);gid=client.post(base+'/programmes',json=body).json()['id']
    client.put(base+'/scenarios/'+body['scenario_ids'][1],json={'name':'Wrong demand B','baseline_id':comps['B']['id'],'candidate_id':comps['C']['id'],'annual_units':999,'extra_per_unit':0,'transition_cost':20,'assumption_note':'Synthetic negative test: demand must match linked BOM.'})
    assert client.get(base+'/programmes/'+gid).json()['status']=='blocked'
    client.post(base+'/documents/'+body['evidence_id']+'/reopen',json={'note':'Reopen synthetic cost source for review.'})
    assert not client.get(base+'/programmes/'+gid).json()['cost_source_reviewed']

def test_legacy_bottle_fingerprint_is_preserved(client,scenario):
    ev=client.get(f'/api/projects/{scenario["pid"]}/scenarios/{scenario["sid"]}').json()['evaluation']
    scope={'baseline':dict(ev['baseline']),'candidate':dict(ev['candidate']),'inputs':ev['assumptions'],'products':ev['affected_products']}
    for key in ('baseline','candidate'):
        for field in ('component_type','uom','attributes'):scope[key].pop(field,None)
    for product in scope['products']:
        product.pop('archived',None);product.pop('version',None)
    assert ev['fingerprint']==hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()

def test_noncontainer_schema_requires_real_compatibility_attributes():
    common={'code':'BOX','name':'Synthetic box','material':'KRAFT','weight_g':100,'price':10,'revision':'R1','evidence_id':'e','price_valid_from':'2026-01-01','price_valid_until':'2027-12-31','component_type':'carton'}
    with pytest.raises(ValidationError):Component(**common)
    box=Component(**common,attributes={'length_mm':300,'width_mm':200,'height_mm':150,'board_grade':'B','strength_ect':32})
    assert box.capacity_ml==0 and box.neck=='N/A'
    with pytest.raises(ValidationError):Component(**{**common,'component_type':'bottle'})

def test_closure_safety_attributes_block_false_common_part_match(client):
    base,body,comps=tiny(client)
    for code,safety in [('A',True),('C',False)]:
        row={k:v for k,v in comps[code].items() if k not in ('id','project_id','version')}
        row.update(component_type='closure',capacity_ml=0,neck='28-410',material='PP',attributes={'diameter_mm':28,'liner':'PE','mechanism':'threaded','child_resistant':safety,'contact_class':'oral'})
        assert client.post(base+'/components',json=row).status_code==200
    ev=client.get(base+'/scenarios/'+body['scenario_ids'][0]).json()['evaluation']
    assert not ev['eligible']
    assert any(c['attribute']=='spec_child_resistant' and not c['passed'] for c in ev['checks'])
    assert not any(o['baseline_id']==comps['A']['id'] and o['candidate_id']==comps['C']['id'] for o in client.get(base+'/opportunities').json())

def test_rollup_refuses_mixed_currency_totals(client):
    base,body,comps=tiny(client)
    row={k:v for k,v in comps['B'].items() if k not in ('id','project_id','version')};row['currency']='USD'
    assert client.post(base+'/components',json=row).status_code==200
    assert client.post(base+'/programmes',json=body).status_code==422

def test_fractional_transport_packaging_forecast_is_not_truncated(client):
    base,body,comps=tiny(client)
    product=client.get(base+'/catalog').json()['products'][0]
    client.put(base+'/products/'+str(product['id']),json={'sku':'KIT-01','name':'Kit with allocated shipper','annual_units':100,'plant':'Synthetic plant','formula':'Synthetic formula','version':product['version'],'bom':[{'component_code':'A','quantity':1},{'component_code':'B','quantity':1/12}]})
    r=client.put(base+'/scenarios/'+body['scenario_ids'][1],json={'name':'Allocated shipper B','baseline_id':comps['B']['id'],'candidate_id':comps['C']['id'],'annual_units':100/12,'extra_per_unit':0,'transition_cost':20,'assumption_note':'Consumption forecast, not an integer procurement order.'});assert r.status_code==200,r.text
    gid=client.post(base+'/programmes',json=body).json()['id'];plan=client.get(base+'/programmes/'+gid).json()
    assert plan['status']=='awaiting_qualification'
    assert all(m['demand_matches_bom'] for m in plan['members'])
    assert plan['members'][1]['financials']['annual_units']==pytest.approx(100/12)
    assert plan['financials']['first_year_net']==36.67

def test_rollup_reconciles_scenario_rounding_to_the_cent(client):
    base,body,comps=tiny(client)
    row={k:v for k,v in comps['B'].items() if k not in ('id','project_id','version')};row['price']=17
    client.post(base+'/components',json=row)
    product=client.get(base+'/catalog').json()['products'][0]
    client.put(base+'/products/'+str(product['id']),json={'sku':'KIT-01','name':'Kit with allocated shipper','annual_units':100,'plant':'Synthetic plant','formula':'Synthetic formula','version':product['version'],'bom':[{'component_code':'A','quantity':1},{'component_code':'B','quantity':1/12}]})
    client.put(base+'/scenarios/'+body['scenario_ids'][1],json={'name':'Allocated shipper B','baseline_id':comps['B']['id'],'candidate_id':comps['C']['id'],'annual_units':100/12,'extra_per_unit':.5,'transition_cost':20,'assumption_note':'Consumption forecast with per-member currency rounding.'})
    gid=client.post(base+'/programmes',json=body).json()['id'];f=client.get(base+'/programmes/'+gid).json()['financials']
    assert f['first_year_net']==124.17 and f['rounding_adjustment']==.01
