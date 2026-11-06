"""Planning roll-ups: distinct physical baseline components, shared costs counted once."""
import json,math
from decimal import Decimal
from fastapi import HTTPException
from .engine import evaluate,evidence,money,scenario_row

def validate_members(c,pid,ids):
    if len(set(ids))!=len(ids):raise HTTPException(422,'Each scenario can appear only once')
    rows=[scenario_row(c,pid,sid) for sid in ids]
    if len({s['baseline_id'] for s in rows})!=len(rows):
        raise HTTPException(409,'Alternative scenarios for the same baseline cannot be added together; choose one replacement')
    currencies={evaluate(c,s)['financials']['currency'] for s in rows}
    if len(currencies)>1:raise HTTPException(422,'Programme totals require one currency; no exchange rate is inferred')
    return rows

def rollup(c,row):
    plan=dict(row);ids=json.loads(plan['scenario_ids']);members=[];products={};conflicts=[];groups={};by_uom={}
    totals={k:Decimal('0') for k in ('gross_annual','annual_extra','transition','first_year_net','recurring_annual_net','material_tonnes')}
    try:rows=validate_members(c,plan['project_id'],ids)
    except HTTPException as ex:
        return {**plan,'scenario_ids':ids,'status':'blocked','error':ex.detail,'members':[],'common_components':[],
            'unique_skus':0,'affected_products':[],'financials':None,'cost_source_reviewed':False}
    for s in rows:
        current=evaluate(c,s)
        frozen=c.execute('SELECT snapshot FROM approval_snapshots WHERE scenario_id=? ORDER BY id DESC LIMIT 1',(s['id'],)).fetchone()
        ev=json.loads(frozen['snapshot']) if s['status']=='implemented' and frozen else current
        f=ev['financials'];unit=f.get('uom','piece')
        for key in totals:totals[key]+=Decimal(str(f[key]))
        by_uom[unit]=by_uom.get(unit,0)+f['annual_units']
        for p in ev['affected_products']:
            old=products.get(p['sku'])
            if old and any(old[k]!=p[k] for k in ('annual_units','plant','formula')):conflicts.append(p['sku'])
            products[p['sku']]=p
        group=groups.setdefault(ev['candidate']['code'],{'candidate':ev['candidate']['code'],'baselines':[],'skus':set()})
        group['baselines'].append(ev['baseline']['code']);group['skus'].update(p['sku'] for p in ev['affected_products'])
        members.append({'id':s['id'],'name':s['name'],'status':s['status'],'baseline':ev['baseline']['code'],'candidate':ev['candidate']['code'],
            'eligible':ev['eligible'],'qualified':ev['qualification_complete'],'approval_current':bool(ev['approval_current']),
            'demand_matches_bom':math.isclose(f['annual_units'],ev['annual_component_demand'],rel_tol=1e-8,abs_tol=.01),
            'affected_skus':[p['sku'] for p in ev['affected_products']],'financials':f})
    source=c.execute('SELECT status FROM documents WHERE id=? AND project_id=?',(plan['evidence_id'],plan['project_id'])).fetchone()
    reviewed=bool(source and source['status']=='approved')
    blocked=not reviewed or bool(conflicts) or any(not m['eligible'] or not m['demand_matches_bom'] for m in members)
    qualified=all(m['qualified'] for m in members);approved=all(m['approval_current'] for m in members)
    implemented=all(m['status']=='implemented' for m in members)
    status='blocked' if blocked else 'implemented' if implemented else 'approved_planning' if approved else 'awaiting_approval' if qualified else 'awaiting_qualification'
    shared=Decimal(str(plan['shared_transition_cost']));transition=totals['transition']+shared
    return {**plan,'scenario_ids':ids,'members':members,'status':status,'cost_source_reviewed':reviewed,'scope_conflicts':sorted(set(conflicts)),
        'all_members_qualified':qualified,'all_members_approved':approved,'affected_products':sorted(products.values(),key=lambda p:p['sku']),
        'unique_skus':len(products),'finished_unit_forecast':sum(p['annual_units'] for p in products.values()),'annual_component_demand_by_uom':by_uom,
        'common_components':[{'candidate':g['candidate'],'baseline_count':len(g['baselines']),'baselines':g['baselines'],'affected_skus':sorted(g['skus'])} for g in groups.values()],
        'financials':{'currency':members[0]['financials']['currency'],'gross_annual':money(totals['gross_annual']),'annual_extra':money(totals['annual_extra']),
            'local_transition':money(totals['transition']),'shared_transition':money(shared),'transition':money(transition),
            'first_year_net':money(totals['first_year_net']-shared),'recurring_annual_net':money(totals['recurring_annual_net']),
            'rounding_adjustment':money((totals['first_year_net']-shared)-(totals['gross_annual']-totals['annual_extra']-transition)),
            'material_tonnes':float(totals['material_tonnes'])},
        'limitations':['Planning roll-up only; it is not a programme approval or an ERP implementation.',
            'Different component replacements on the same SKU are additive; each physical baseline is counted once. Alternative plans must not be summed.',
            'Shared costs are counted once in this plan. Do not sum family plans and their containing portfolio.',
            'Combined packaging changes still need joint line, transport, artwork and product-compatibility validation.']}
