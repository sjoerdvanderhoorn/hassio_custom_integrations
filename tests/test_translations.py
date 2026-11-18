"""Native catalogues match the English schema and the requested 66-language set."""
from pathlib import Path
import json,re
import pytest
ROOT=Path(__file__).resolve().parents[1]/'custom_components/custom_integrations'
CODES="af ar bg bn ca cs cy da de de-CH el en es et eu fa fi fr ga gl gu he hi hr hu hy id is it ja ka kn ko kw lb lt lv ml mn mr ms nb ne nl pa pl pt pt-BR ro ru sk sl sr sr-Latn sv sw ta te th tr uk ur vi zh-CN zh-HK zh-TW".split()
def flatten(value,prefix=''):
 if isinstance(value,dict):
  return {k:v for name,item in value.items() for k,v in flatten(item,prefix+'.'+name).items()}
 assert isinstance(value,str) and value.strip()
 return {prefix:value}
def test_native_language_set_and_english_source():
 assert {p.stem for p in (ROOT/'translations').glob('*.json')}==set(CODES)
 assert json.loads((ROOT/'strings.json').read_text(encoding='utf-8'))==json.loads((ROOT/'translations/en.json').read_text(encoding='utf-8'))
@pytest.mark.parametrize('code',CODES)
def test_complete_native_catalogue(code):
 source=flatten(json.loads((ROOT/'strings.json').read_text(encoding='utf-8')))
 target=flatten(json.loads((ROOT/'translations'/f'{code}.json').read_text(encoding='utf-8')))
 assert target.keys()==source.keys()
 for key,text in target.items():
  assert re.findall(r'\{[^{}]+\}',text)==re.findall(r'\{[^{}]+\}',source[key])
  assert '\ufffd' not in text and 'TODO' not in text
 if code!='en':
  for key in ['.config.step.user.description','.options.step.init.description','.config.error.missing_key','.config.error.missing_model']:
   assert target[key]!=source[key],(code,key)
