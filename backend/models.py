from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import math

class Model(BaseModel):
    model_config=ConfigDict(extra='forbid', allow_inf_nan=False)

class Credentials(Model):
    email: str = Field(min_length=3,max_length=200)
    password: str = Field(min_length=1,max_length=256)
    @field_validator('email')
    @classmethod
    def email_valid(cls,v):
        v=v.strip().lower()
        if '@' not in v or any(x.isspace() for x in v): raise ValueError('Enter an email address')
        return v

class Setup(Credentials):
    name: str = Field(min_length=2,max_length=100)
    token: str = Field(min_length=16,max_length=200)
    password: str = Field(min_length=12,max_length=256)

class NewUser(Credentials):
    name: str = Field(min_length=2,max_length=100)
    password: str = Field(min_length=12,max_length=256)

class Project(Model):
    name: str = Field(min_length=2,max_length=150)
    synthetic: bool = False
    @field_validator('name')
    @classmethod
    def clean_name(cls,v):
        if len(v.strip())<2:raise ValueError('Enter a project name')
        return v.strip()

class ProjectRename(Model):
    name: str = Field(min_length=2,max_length=150)

class Archive(Model):
    archived: bool
    note: str = Field(min_length=5,max_length=1000)

class SampleCreate(Model):
    name: str = Field(default='ClearCare • synthetic case study',min_length=2,max_length=150)
    create_new: bool = False
    request_key: str | None = Field(default=None,min_length=16,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')

class Member(Model):
    user_id: int
    role: Literal['viewer','editor','reviewer']

class FieldReview(Model):
    fields: dict[str,str] = Field(default_factory=dict)
    note: str = Field(min_length=5,max_length=1000)

class Component(Model):
    code: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=200)
    supplier: str = Field(default='',max_length=200)
    material: str = Field(min_length=1,max_length=50)
    component_type: Literal['bottle','closure','dispensing','label_stock','decoration','carton','pouch','tube','film','pallet','insert'] = 'bottle'
    uom: Literal['piece','m2','kg','metre'] = 'piece'
    attributes: dict[str,str|int|float|bool] = Field(default_factory=dict,max_length=30)
    capacity_ml: float = Field(default=0,ge=0,le=1000000)
    neck: str = Field(default='N/A',min_length=1,max_length=100)
    weight_g: float = Field(gt=0,le=1000000)
    price: float = Field(ge=0,le=10000000)
    currency: Literal['INR','USD','EUR','GBP','NGN'] = 'INR'
    revision: str = Field(min_length=1,max_length=100)
    price_valid_from: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    price_valid_until: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    evidence_id: str
    state: Literal['approved','candidate'] = 'candidate'

    @model_validator(mode='after')
    def type_specification(self):
        required={
            'closure':{'diameter_mm','liner','mechanism','child_resistant','contact_class'},
            'dispensing':{'dose_ml','seal_material','mechanism','contact_class'},
            'label_stock':{'width_mm','thickness_um','adhesive','print_process'},
            'decoration':{'artwork_id','regulatory_text_version'},
            'carton':{'length_mm','width_mm','height_mm','board_grade','strength_ect'},
            'pouch':{'width_mm','height_mm','barrier_class','seal_process'},
            'film':{'width_mm','thickness_um','application','barrier_class'},
            'pallet':{'length_mm','width_mm','load_kg','treatment'},
            'insert':{'length_mm','width_mm','contact_class'}}
        if self.component_type in ('bottle','tube') and self.capacity_ml<=0:
            raise ValueError('Bottles and tubes need a positive capacity_ml')
        if self.component_type in ('bottle','tube','closure','dispensing') and self.neck.upper()=='N/A':
            raise ValueError('This component type needs an explicit neck/interface')
        missing=required.get(self.component_type,set())-set(self.attributes)
        if missing:raise ValueError('Missing compatibility attributes: '+', '.join(sorted(missing)))
        for key,value in self.attributes.items():
            if len(key)>80 or len(str(value))>300 or not str(value).strip():raise ValueError('Use short, nonempty compatibility attributes')
            if isinstance(value,float) and not math.isfinite(value):raise ValueError('Compatibility attributes must be finite')
        return self

    @field_validator('price_valid_from','price_valid_until')
    @classmethod
    def valid_date(cls,v):
        from datetime import date
        date.fromisoformat(v)
        return v

class Product(Model):
    sku: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=200)
    annual_units: int = Field(ge=0,le=10000000000)
    plant: str = Field(min_length=1,max_length=200)
    formula: str = Field(min_length=1,max_length=200)
    bom: list[dict] = Field(default_factory=list,max_length=100)

    @field_validator('bom')
    @classmethod
    def valid_bom(cls,lines):
        seen=set();result=[]
        for line in lines:
            if set(line)-{'component_code','quantity'}:raise ValueError('BOM lines support component_code and quantity')
            code=line.get('component_code');quantity=line.get('quantity',1)
            if not isinstance(code,str) or not code.strip() or code in seen:raise ValueError('Every BOM component must be present once, with a component code')
            if isinstance(quantity,bool):raise ValueError('BOM quantity must be a positive finite number')
            quantity=float(quantity)
            if not math.isfinite(quantity) or quantity<=0:raise ValueError('BOM quantity must be a positive finite number')
            seen.add(code);result.append({'component_code':code,'quantity':quantity})
        return result

class ProductUpdate(Product):
    version: int = Field(ge=1)

class Scenario(Model):
    name: str = Field(min_length=2,max_length=200)
    baseline_id: int
    candidate_id: int
    annual_units: float = Field(gt=0,le=10000000000)
    extra_per_unit: float = Field(ge=0,le=10000000)
    transition_cost: float = Field(ge=0,le=100000000000)
    assumption_note: str = Field(min_length=5,max_length=2000)

class Qualification(Model):
    key: Literal['fit_seal','line_trial','formula_compatibility']
    passed: bool
    evidence_id: str
    note: str = Field(min_length=10,max_length=2000)

class Note(Model):
    note: str = Field(min_length=10,max_length=2000)

class Implementation(Note):
    evidence_id: str
    reference: str = Field(min_length=2,max_length=200)

class Question(Model):
    question: str = Field(min_length=3,max_length=2000)

class Connector(Model):
    name: str = Field(min_length=2,max_length=150)
    kind: Literal['folder','http_json','webhook']
    enabled: bool = False
    interval_seconds: int = Field(default=300,ge=60,le=86400)
    config: dict = Field(default_factory=dict)

class Delivery(Model):
    connector_id: str

class Programme(Model):
    name: str = Field(min_length=2,max_length=200)
    description: str = Field(min_length=10,max_length=4000)
    scenario_ids: list[str] = Field(min_length=1,max_length=100)
    shared_transition_cost: float = Field(default=0,ge=0,le=100000000000)
    cost_note: str = Field(min_length=10,max_length=2000)
    evidence_id: str
