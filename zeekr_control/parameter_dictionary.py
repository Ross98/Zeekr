"""Static terminology only: no owner readings, enum decoding or manual reviews."""
import json
from pathlib import Path

FIELDS = json.loads(Path(__file__).with_name('parameter_dictionary.json').read_text(encoding='utf-8'))['fields']


def definition(path):
    entry = FIELDS.get(path)
    if not entry or entry['private']:
        return None
    return entry


def reference(entry):
    return {key: entry[key] for key in ('unit', 'kind', 'basis', 'note', 'sources', 'applicability', 'applicability_scope')}
