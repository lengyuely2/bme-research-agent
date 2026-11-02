import io
import json
import math
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from bioagent.analysis import Dataset
from bioagent.desktop_service import DesktopService
from bioagent.safety import SafetyError
from bioagent.workflow import detect_spikes, default_plan


def spark_bytes(*,duplicate=False,badtime=False,empty_cycle=False):
    w=Workbook();s=w.active;s.title='Result sheet'
    s.append(['Application: SparkControl',None,None,None,'V4.1'])
    s.append(['Kinetic cycles',None,None,None,12])
    s.append(['Cycle Nr.','Time [s]','Temp. [°C]','A1','A1' if duplicate else 'B1','A2','H12'])
    for i in range(12):
        if empty_cycle and i==5:s.append([None]*7);continue
        s.append([i+1,0 if badtime and i==5 else 16.4*i,37,100+i,101+i,'OVER' if i==4 else 120+i,None])
    s.append([]);s.append(['Warning','Unable to meet given kinetic interval time'])
    # Instrument exports include unused plate positions out to 99 columns.
    s.cell(3,99).value='unused position'
    raw=io.BytesIO();w.save(raw);w.close();return raw.getvalue()


def test_spark_unpivots_only_active_wells_and_preserves_original_cells(tmp_path):
    raw=spark_bytes();data=Dataset.from_bytes(tmp_path,'spark.xlsx',raw)
    assert len(data.rows)==36 and len(data.headers)==7
    assert data.rows[0]==('0','100','1','A1','A','1','D4')
    assert data.rows[12][3]=='B1' and data.rows[24][3]=='A2'
    assert float(data.rows[1][0])==pytest.approx(16.4/60)
    assert data.rows[28][1]=='OVER'
    assert any('实际' in n for n in data.warnings)
    plan=default_plan(data);assert plan['group']=='plate_column' and plan['replicate']=='well'


@pytest.mark.parametrize('options',[{'duplicate':True},{'badtime':True},{'empty_cycle':True}])
def test_malformed_instrument_data_refused_instead_of_silently_repaired(tmp_path,options):
    with pytest.raises(SafetyError):Dataset.from_bytes(tmp_path,'spark.xlsx',spark_bytes(**options))


def test_wide_non_instrument_sheet_not_treated_as_spark(tmp_path):
    w=Workbook();s=w.active;s.append([f'column_{i}' for i in range(70)]);s.append(list(range(70)))
    raw=io.BytesIO();w.save(raw)
    with pytest.raises(SafetyError):Dataset.from_bytes(tmp_path,'wide.xlsx',raw.getvalue())


def impulse_data(tmp_path):
    import random
    rng=random.Random(24);rows=['time,signal,condition,well,source_cell']
    # A genuine slow rise followed by decline plus ordinary measurement variation.
    for i in range(100):
        y=1000+100*math.sin(i/100*math.pi)+rng.uniform(-.9,.9)
        if i==50:y+=30
        rows.append(f'{i},{y},A,A1,D{i+2}')
    return Dataset.from_bytes(tmp_path,'impulse.csv','\n'.join(rows).encode())


def impulse_plan():return dict(kind='time',x='time',y='signal',group='condition',replicate='well',error='SD')


def test_isolated_impulse_detected_without_removing_real_decline(tmp_path):
    data=impulse_data(tmp_path);result=detect_spikes(data,impulse_plan())
    assert result['records']==[51] and result['candidates'][0]['source_cell']=='D52'
    assert len(data.rows)==100 and data.rows[51][1]!=data.rows[50][1]
    assert all(c['x']<99 for c in result['candidates'])


@pytest.mark.parametrize('value',['nan','inf','2','11','__import__("os")'])
def test_spike_threshold_validated(tmp_path,value):
    with pytest.raises(SafetyError):detect_spikes(impulse_data(tmp_path),{**impulse_plan(),'spike_threshold':value})


def test_duplicate_time_points_skip_series_instead_of_guessing(tmp_path):
    data=impulse_data(tmp_path)
    from dataclasses import replace
    data=replace(data,rows=(*data.rows,data.rows[0]))
    result=detect_spikes(data,impulse_plan())
    assert result['skipped_series']==1 and result['records']==[]


def test_broker_exports_before_after_with_original_cell_and_frozen_values(tmp_path):
    data=impulse_data(tmp_path);source=tmp_path/'source';source.mkdir()
    from dataclasses import replace
    data=replace(data,root=source)
    service=DesktopService();service.dataset=data;service.output=tmp_path/'out'
    check=service.dispatch('workflow_spikes',impulse_plan());assert check['records']==[51]
    result=service.dispatch('workflow_review',{**impulse_plan(),'exclude_rows':'51','exclude_reason':check['rule']})
    generated=service.dispatch('workflow_render',{'token':result['token']})
    assert generated['used']==99 and generated['before']['used']==100
    assert [c.used for c in service.charts]==[100,99]
    saved=service.dispatch('workflow_export',{'run_id':generated['run_id']})
    with ZipFile(saved['path']) as z:
        assert 'before_exclusion.svg' in z.namelist()
        audit=json.loads(z.read('analysis.json'))
        assert audit['decisions'][50]['source_cell']=='D52'
        assert audit['decisions'][50]['excluded'] is True
        assert audit['decisions'][80]['excluded'] is False
