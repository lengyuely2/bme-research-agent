"""Strict, read-only Spark kinetic-export normalization; no inferred concentrations."""
import csv
import io
import math
import re
from .safety import SafetyError


def spark_table(rows):
    signature=any(any('SparkControl' in str(v) for v in row) for row in rows[:30])
    headers=[i for i,row in enumerate(rows) if len(row)>3 and row[0].strip()=='Cycle Nr.' and row[1].strip()=='Time [s]']
    if not signature or not headers:
        return None
    if len(headers)!=1:
        raise SafetyError('Spark 工作表含多个读数段，请单独选择一个测量段另存副本。')
    start=headers[0];header=rows[start]
    wells=[(i,name.strip()) for i,name in enumerate(header) if re.fullmatch(r'[A-H](?:[1-9]|1[0-2])',name.strip())]
    if not wells or len({name for _,name in wells})!=len(wells):
        raise SafetyError('Spark 孔号缺失或重复，不能安全转换。')
    records=[]
    for source_row,row in enumerate(rows[start+1:],start+2):
        if not row[0].strip():break
        try:
            cycle=float(row[0]);seconds=float(row[1])
        except (ValueError,IndexError):break
        if not math.isfinite(seconds) or seconds<0 or not cycle.is_integer() or cycle<1:
            raise SafetyError('Spark 周期号或实际时间无效。')
        records.append((source_row,int(cycle),seconds,row))
    if len(records)<3 or len({r[1] for r in records})!=len(records) or any(a[2]>=b[2] for a,b in zip(records,records[1:])):
        raise SafetyError('Spark 需要至少 3 个周期，且周期不重复、实际时间严格递增。')
    expected=[row[4] for row in rows[:start] if len(row)>4 and row[0].strip()=='Kinetic cycles']
    if expected and (len(expected)!=1 or not expected[0].isdigit() or int(expected[0])!=len(records)):
        raise SafetyError('Spark 实际读数周期数与设置不符，不能静默截断；请核对原表。')
    active=[(i,name) for i,name in wells if any(r[3][i].strip() for r in records)]
    if not active or len(active)*len(records)>10000:
        raise SafetyError('Spark 转换后最多 10,000 条孔/时间记录；未截断数据。')
    from openpyxl.utils import get_column_letter
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow(['time_min','signal_au','plate_column','well','plate_row','cycle','source_cell'])
    for index,well in active:
        for row_no,cycle,seconds,row in records:
            writer.writerow([format(seconds/60,'.15g'),row[index],int(well[1:]),well,well[0],cycle,f'{get_column_letter(index+1)}{row_no}'])
    intervals=[b[2]-a[2] for a,b in zip(records,records[1:])]
    notes=[f'Spark 动力学宽表已只读转换：表头第 {start+1} 行，{len(records)} 周期，{len(active)} 个有读数的孔，共 {len(records)*len(active)} 条记录。',
           f'使用仪器实际 Time [s] / 60；相邻间隔 {min(intervals):.3f}–{max(intervals):.3f} 秒，未使用设置中的期望间隔。',
           'plate_column 为物理列、well 为孔号；同列各孔作为候选复孔，不代表已确认实验布局或生物学独立性。没有从信号反推浓度。source_cell 保留原 Excel 坐标。']
    if any('Unable to meet' in str(v) for row in rows for v in row):
        notes.append('原始仪器报告提示无法达到设定的动力学间隔；请按实际时间分析。')
    return output.getvalue(),notes
