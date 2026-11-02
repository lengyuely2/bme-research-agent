import base64
import csv
import io
import json
import math
import threading
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from openai import OpenAI

from bioagent.analysis import Dataset
from bioagent.billing import UsageLedger
from bioagent.desktop_service import DesktopService
from bioagent.safety import SafetyError
from bioagent.workflow import review, render, default_plan, profile, ai_suggest, export_zip, parse_exclusions

SAMPLES=Path(__file__).resolve().parents[1]/'samples'


def dataset(tmp_path, text):
    return Dataset.from_bytes(tmp_path,'synthetic.csv',text.encode())


def plan(**values):
    return dict(kind='group',x='condition',y='signal',group='',replicate='replicate',error='SD',**values)


def test_known_group_mean_sample_sd_and_sem(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,1\nA,2,2\nA,3,3\nB,9,1\n')
    result=review(data,plan())
    a,b=result.summary
    assert (a['n'],a['mean'],a['sd'])==(3,2,1)
    assert a['sem']==pytest.approx(1/math.sqrt(3))
    assert b['n']==1 and b['sd'] is None and b['sem'] is None
    assert result.public()['used']==4 and result.public()['excluded']==0
    assert any('只有 1' in s for s in result.warnings)


def test_technical_repeats_do_not_inflate_independent_n(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,R1\nA,3,R1\nA,6,R2\n')
    result=review(data,plan())
    assert result.summary[0]['n']==2
    assert result.summary[0]['mean']==4
    assert result.summary[0]['sd']==pytest.approx(math.sqrt(8))
    assert [x['technical_n'] for x in result.summary[0]['observations']]==[2,1]
    assert len(result.points)==3


def test_time_groups_sorted_and_replicates_collapsed_at_each_time(tmp_path):
    data=dataset(tmp_path,'time,signal,condition,replicate\n10,4,A,1\n0,1,A,1\n10,8,A,2\n0,3,A,2\n10,12,B,1\n')
    result=review(data,dict(kind='time',x='time',y='signal',group='condition',replicate='replicate',error='SEM'))
    assert [(s['group'],s['x'],s['mean']) for s in result.summary]==[('A',0,2),('A',10,6),('B',10,12)]
    assert result.summary[1]['sem']==2
    image=render(result)
    assert image.chart.png.startswith(b'\x89PNG') and b'<svg' in image.svg
    assert b'Mean' in image.svg and b'No significance' in image.svg


def test_missing_invalid_ranges_manual_reason_and_frozen_review(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,1\nA,,2\nA,nan,3\nA,9,4\nA,3,5\n')
    options=plan(y_max='5',exclude_rows='5',exclude_reason='instrument failure')
    result=review(data,options);options['y_max']='100'
    assert result.public()['used']==1 and result.public()['excluded']==4
    assert result.plan['y_max']==5
    assert '缺失' in result.decisions[1]['reasons'][0]
    assert result.decisions[3]['reasons']==['超出已选信号范围']
    assert result.decisions[4]['reasons']==['手动排除：instrument failure']
    assert len(data.rows)==5


def test_duplicates_and_outlier_candidates_remain_in_plot(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,1\nA,1,1\nA,2,2\nA,3,3\nA,4,4\nA,100,5\n')
    result=review(data,plan())
    assert len(result.points)==6
    assert '完全重复' in result.decisions[1]['flags'][0]
    assert any('IQR' in flag for flag in result.decisions[-1]['flags'])
    assert all(not d['excluded'] for d in result.decisions)


@pytest.mark.parametrize('changes',[{'exclude_rows':'1'},{'exclude_rows':'999','exclude_reason':'test'},
    {'exclude_rows':'1; delete','exclude_reason':'test'}, {'y_min':'nan'}, {'y_min':'9','y_max':'1'},
    {'x_min':'0'}, {'replicate':'condition'}, {'y':'not_a_column'}, {'error':'p<0.05'}, {'kind':'exec'}])
def test_invalid_filters_and_column_roles_rejected(tmp_path,changes):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,1\nA,2,2\n')
    options=plan();options.update(changes)
    with pytest.raises(SafetyError):review(data,options)


def test_no_replicate_is_labeled_as_records_not_independent_samples(tmp_path):
    data=dataset(tmp_path,'condition,signal\nA,1\nA,2\n')
    options=plan();options['replicate']=''
    result=review(data,options)
    assert any('不能据此认定' in w for w in result.warnings)
    assert b'independence unverified' in render(result).svg


def test_all_excluded_rejected_and_exclusion_ranges_bounded(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\nA,1,1\n')
    with pytest.raises(SafetyError):review(data,plan(y_min='2'))
    assert parse_exclusions('1, 3-5，7',8)=={1,3,4,5,7}
    with pytest.raises(SafetyError):parse_exclusions('1-99999999999',8)


def test_ai_actual_sdk_schema_and_privacy_without_network(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate,subject\nSECRET_CONDITION,1,PRIVATE_REPEAT,PRIVATE_SUBJECT\n')
    ledger=UsageLedger()
    def handler(request):
        payload=json.loads(request.content)
        serialized=json.dumps(payload)
        for secret in ('SECRET_CONDITION','PRIVATE_REPEAT','PRIVATE_SUBJECT',str(tmp_path),'synthetic.csv'):
            assert secret not in serialized
        assert payload['store'] is False and payload['text']['format']['strict'] is True
        assert payload['text']['format']['type']=='json_schema'
        assert 'tools' not in payload
        response={**plan(), 'summary':'请核对独立重复；未查看原始数据。'}
        return httpx.Response(200,json={'id':'offline','object':'response','created_at':1,'model':'mock-model','status':'completed',
            'usage':{'input_tokens':11,'output_tokens':22,'total_tokens':33},'output':[{'type':'message','id':'msg','role':'assistant',
            'status':'completed','content':[{'type':'output_text','text':json.dumps(response),'annotations':[]}]}]})
    with OpenAI(api_key='offline-placeholder',http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        result=ai_suggest(client,'mock-model',data,'compare conditions',ledger,threading.Event())
    assert result['kind']=='group' and ledger.snapshot()['input_tokens']==11


def test_export_archive_audit_matches_calculations_and_escapes_csv_formulas(tmp_path):
    data=dataset(tmp_path,'condition,signal,replicate\n=1+1,1,1\n=1+1,3,2\n=1+1,8,3\n')
    result=render(review(data,plan(exclude_rows='3',exclude_reason='instrument failure')))
    with ZipFile(io.BytesIO(export_zip(result))) as z:
        audit=json.loads(z.read('analysis.json'))
        assert audit['source_sha256']==data.sha256 and audit['kept_records']==2
        assert audit['decisions'][2]['excluded'] is True
        rows=list(csv.reader(io.StringIO(z.read('processed_points.csv').decode('utf-8-sig'))))
        assert len(rows)==3 and rows[1][1]=="'=1+1"
        assert audit['summary'][0]['x']=='=1+1'
        assert set(z.namelist())=={'figure.png','figure.svg','analysis.json','row_decisions.csv','processed_points.csv','summary.csv','README.txt'}


def test_service_tokens_invalidate_on_reload_export_uses_original_snapshot(tmp_path):
    source=tmp_path/'source';source.mkdir();path=source/'data.csv'
    original=b'condition,signal,replicate\nA,1,1\nA,3,2\n';path.write_bytes(original)
    service=DesktopService();service.output=tmp_path/'output'
    service.dispatch('load_data',{'path':str(path)})
    preview=service.dispatch('workflow_review',plan())
    run=service.dispatch('workflow_render',{'token':preview['token']})
    assert base64.b64decode(run['image'].split(',')[1]).startswith(b'\x89PNG')
    path.write_bytes(b'condition,signal,replicate\nA,99,1\n')
    service.dispatch('load_data',{'path':str(path)})
    with pytest.raises(SafetyError):service.dispatch('workflow_render',{'token':preview['token']})
    exported=service.dispatch('workflow_export',{'run_id':run['run_id']})
    with ZipFile(exported['path']) as z:
        audit=json.loads(z.read('analysis.json'));assert audit['summary'][0]['mean']==2
    assert path.read_bytes()!=original and '99' in path.read_text()
    second=service.dispatch('workflow_export',{'run_id':run['run_id']});assert second['path']!=exported['path']
    with pytest.raises(SafetyError):service.dispatch('set_output',{'path':str(source)})
    assert len(list(source.iterdir()))==1


def test_demo_plans_and_data_are_plottable_and_local(tmp_path):
    service=DesktopService();service.output=tmp_path/'output'
    for kind in ('time','group'):
        data=service.dispatch('demo_workflow',{'kind':kind})
        prof=service.dispatch('workflow_profile',{})
        assert prof['plan']['kind']==kind
        checked=service.dispatch('workflow_review',prof['plan'])
        generated=service.dispatch('workflow_render',{'token':checked['token']})
        assert generated['used']==data['rows'] and generated['excluded']==0
    assert service.billing.snapshot()['requests']==0
