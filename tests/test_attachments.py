import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest
from openai import OpenAI
from openpyxl import Workbook
from PIL import Image

from bioagent.attachments import Attachment
from bioagent.agent import Packet, ResearchAgent, citation_issues
from bioagent.desktop_service import DesktopService
from bioagent.safety import SafetyError

SAMPLES = Path(__file__).resolve().parents[1]/'samples'


@pytest.fixture
def broker(tmp_path):
    result=DesktopService();result.output=tmp_path.parent/(tmp_path.name+'_reports')
    result.api_key,result.models='offline-placeholder',('mock-model',)
    return result


def attach(broker, paths):
    result=broker.dispatch('attach_files',{'paths':[str(path) for path in paths]})
    assert not result['warnings'],result['warnings']
    return [item['id'] for item in result['items']]


def workbook_bytes():
    workbook=Workbook();sheet=workbook.active;sheet.title='Calibration'
    sheet.append(['concentration','signal']);sheet.append([0,0.01]);sheet.append([1,0.2])
    second=workbook.create_sheet('Stability');second.append(['time','signal']);second.append([0,1]);second.append([1,0.9])
    hidden=workbook.create_sheet('Hidden');hidden.sheet_state='hidden';hidden.append(['PRIVATE_HIDDEN'])
    output=io.BytesIO();workbook.save(output);workbook.close();return output.getvalue()


def test_pdf_snapshot_keeps_pages_and_original_is_unchanged(broker,tmp_path):
    path=tmp_path/'paper.pdf';original=(SAMPLES/'paper_demo.pdf').read_bytes();path.write_bytes(original)
    identifier=attach(broker,[path])[0]
    assert path.read_bytes()==original
    path.write_bytes(b'changed externally')
    item=broker.attachment(identifier)
    assert item.raw==original and item.pages==2
    preview=broker.dispatch('attachment_preview',{'id':identifier,'page':2})
    assert preview['image'].startswith('data:image/png;base64,')
    assert 'LIMITATIONS' in preview['text']
    with pytest.raises(SafetyError):broker.dispatch('attachment_preview',{'id':identifier,'page':999})


def test_pdf_is_sent_as_actual_sdk_file_input_without_exposing_local_path(broker):
    ids=attach(broker,[SAMPLES/'paper_demo.pdf'])
    packet=broker.make_packet({'question':'精读论文','attachment_ids':ids})
    assert str(SAMPLES) not in packet.serialized()
    assert 'base64' not in packet.serialized()
    def handler(request):
        body=json.loads(request.content)
        parts=body['input'][0]['content']
        binary=next(part for part in parts if part['type']=='input_file')
        assert base64.b64decode(binary['file_data'].split(',',1)[1])==(SAMPLES/'paper_demo.pdf').read_bytes()
        assert body['store'] is False
        return httpx.Response(200,json={'id':'offline','object':'response','created_at':1,'model':'mock-model',
            'status':'completed','output':[{'type':'message','id':'msg','role':'assistant','status':'completed',
              'content':[{'type':'output_text','text':'Synthetic only [S501-P002]','annotations':[]}]}]})
    with OpenAI(api_key='offline-placeholder',http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        result=ResearchAgent(client).run(packet,'mock-model')
    assert not result.citation_issues
    assert citation_issues('[S501-P999]',packet)


def test_spreadsheet_selects_only_visible_sheet_and_never_sends_raw_rows(broker,tmp_path):
    path=tmp_path/'data.xlsx';raw=workbook_bytes();path.write_bytes(raw)
    ids=attach(broker,[path]);item=broker.attachment(ids[0])
    assert item.sheets==('Calibration','Stability') and item.dataset.rows[1][1]=='0.2'
    packet=broker.make_packet({'question':'分析','attachment_ids':ids})
    assert 'PRIVATE_HIDDEN' not in json.dumps(packet.content(),ensure_ascii=False)
    prepared=broker.op_prepare({'question':'分析','model':'mock-model','attachment_ids':ids})
    broker.dispatch('attachment_sheet',{'id':ids[0],'sheet':'Stability'})
    assert broker.attachment(ids[0]).sheet=='Stability'
    with pytest.raises(SafetyError):broker.op_approve({'token':prepared['token']})
    with pytest.raises(SafetyError):broker.dispatch('attachment_sheet',{'id':ids[0],'sheet':'Hidden'})
    assert path.read_bytes()==raw


def test_table_attachment_only_transmits_summary_not_private_identifiers(broker,tmp_path):
    path=tmp_path/'data.csv';path.write_text('subject,signal\nPRIVATE_A,1\nPRIVATE_B,2\n',encoding='utf-8')
    ids=attach(broker,[path]);packet=broker.make_packet({'question':'分析','attachment_ids':ids})
    text=packet.serialized()+json.dumps(packet.content(),ensure_ascii=False)
    assert 'PRIVATE_A' not in text and 'PRIVATE_B' not in text
    assert packet.dataset is not None and len(packet.dataset.rows)==2


def test_images_are_real_input_images_with_metadata_removed(broker,tmp_path):
    path=tmp_path/'figure.png';image=Image.new('RGB',(40,20),'red');image.save(path)
    ids=attach(broker,[path]);packet=broker.make_packet({'question':'解释图片','attachment_ids':ids})
    part=next(part for part in packet.content() if part['type']=='input_image')
    assert part['image_url'].startswith('data:image/png;base64,')
    assert 'base64' not in packet.serialized()
    assert not citation_issues('[S501-C0001]',packet)


def test_free_chat_cannot_silently_discard_selected_files(broker):
    ids=attach(broker,[SAMPLES/'paper_demo.pdf'])
    with pytest.raises(SafetyError):broker.make_packet({'question':'q','mode':'chat','attachment_ids':ids})
    with pytest.raises(SafetyError):broker.make_packet({'question':'q','attachment_ids':['../../file.pdf']})
    with pytest.raises(SafetyError):broker.make_packet({'question':'q','attachment_ids':ids*2})


def test_removed_attachment_is_only_removed_from_memory(broker,tmp_path):
    path=tmp_path/'note.txt';path.write_text('original',encoding='utf-8')
    ids=attach(broker,[path]);prepared=broker.op_prepare({'question':'q','model':'mock-model','attachment_ids':ids})
    broker.dispatch('remove_attachment',{'id':ids[0]})
    assert path.read_text(encoding='utf-8')=='original'
    with pytest.raises(SafetyError):broker.op_approve({'token':prepared['token']})


def test_output_cannot_overlap_attachment_parent(broker,tmp_path):
    path=tmp_path/'note.txt';path.write_text('safe',encoding='utf-8')
    broker.output=tmp_path/'new-output'
    result=broker.dispatch('attach_files',{'paths':[str(path)]})
    assert not result['items'] and result['warnings']


def test_report_citations_use_the_frozen_pdf_even_after_attachment_removed(broker):
    ids=attach(broker,[SAMPLES/'paper_demo.pdf'])
    packet=broker.make_packet({'question':'read','attachment_ids':ids})
    broker.report_packets['report']=packet
    broker.dispatch('remove_attachment',{'id':ids[0]})
    data=broker.dispatch('view_source',{'report_id':'report','citation':'S501-P002'})
    assert data['page']==2 and 'LIMITATIONS' in data['text']
    with pytest.raises(SafetyError):broker.dispatch('view_source',{'report_id':'report','citation':'S502-P001'})


def test_formula_cells_without_cached_values_are_not_invented(tmp_path):
    workbook=Workbook();sheet=workbook.active;sheet.append(['x','formula']);sheet.append([1,'=A2*2'])
    output=io.BytesIO();workbook.save(output);workbook.close()
    item=Attachment.parse(tmp_path,'formula.xlsx',output.getvalue(),'id','S501')
    assert item.dataset.rows[0][1]=='' and any('未重算' in note for note in item.notes)


def test_xlsx_parser_rejects_bad_archives_and_oversized_row_ranges(tmp_path):
    with pytest.raises(SafetyError):Attachment.parse(tmp_path,'bad.xlsx',b'invalid','id','S501')
    workbook=Workbook();sheet=workbook.active;sheet['A1']='x';sheet['A10002']=3
    output=io.BytesIO();workbook.save(output);workbook.close()
    with pytest.raises(SafetyError):Attachment.parse(tmp_path,'large.xlsx',output.getvalue(),'id','S501')
