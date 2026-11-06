import csv
import io
from datetime import date
from backend import sample as sample_module


def test_fresh_demo_quote_dates_follow_creation_date(client, monkeypatch):
    class FutureDate(date):
        @classmethod
        def today(cls):
            return cls(2031, 2, 1)

    monkeypatch.setattr(sample_module, 'date', FutureDate)
    response = client.post('/api/sample-project')
    assert response.status_code == 200
    project = response.json()
    base = f'/api/projects/{project["id"]}/documents/'
    sources = {doc['name']: client.get(base + doc['id'] + '/file').content
               for doc in project['documents']}
    rows = list(csv.DictReader(io.StringIO(sources['01-components.csv'].decode())))
    assert all(row['price_valid_from'] == '2031-02-01' and
               row['price_valid_until'] == '2031-04-02' for row in rows)
    assert b'2031-02-01 to 2031-04-02' in sources['03-BOT104-R6-current-spec.txt']
    assert b'2031-02-01 to 2031-04-02' in sources['05-candidate-and-commercial-assumptions.txt']
    # Historical synthetic actuals are not silently rewritten as a new commercial period.
    assert b'2026-11-01 through 2026-11-04' in sources['08-synthetic-actual-benefit-evidence.txt']
