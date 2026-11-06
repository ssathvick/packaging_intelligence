import pytest,asyncio,json
from backend.llm import validate_answer
from backend import llm

def test_known_source_ids_and_prose_references_are_accepted():
    validate_answer({'answer':'Synthetic values differ (Evidence IDs: 13, 75 and 80).','citations':['13','75','80']},{'13','75','80'})

@pytest.mark.parametrize('text',['Evidence ID 1 says it fits.','Source 999 supports this.','Evidence IDs: 13, 1 and 75 support this.'])
def test_valid_array_cannot_mask_invented_inline_citations(text):
    with pytest.raises(ValueError,match='inline'):
        validate_answer({'answer':text,'citations':['13']},{'13','75','80'})

def test_unknown_citation_array_is_rejected():
    with pytest.raises(ValueError,match='unknown source'):
        validate_answer({'answer':'Synthetic source attributes.','citations':['999']},{'13'})

class Remote:
    def __init__(self,results):self.results=iter(results);self.calls=0
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def post(self,*args,**kwargs):
        self.calls+=1;result=next(self.results)
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'message':{'content':json.dumps(result)}}
        return Response()

def test_one_correction_can_repair_an_unknown_inline_id(monkeypatch):
    remote=Remote([{'answer':'Evidence ID 1 says yes.','citations':['13']},{'answer':'The synthetic field is false.','citations':['13']}])
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kwargs:remote)
    result=asyncio.run(llm.answer('Question?', [{'id':13,'text':'SYNTHETIC field: false.'}]))
    assert remote.calls==2 and result['citation_repair_attempted']

def test_correction_is_bounded_and_never_returns_an_invalid_reference(monkeypatch):
    invalid={'answer':'Source 999 says yes.','citations':['13']};remote=Remote([invalid,invalid])
    monkeypatch.setattr(llm.httpx,'AsyncClient',lambda **kwargs:remote)
    with pytest.raises(ValueError,match='after one correction'):
        asyncio.run(llm.answer('Question?', [{'id':13,'text':'SYNTHETIC field: false.'}]))
    assert remote.calls==2
