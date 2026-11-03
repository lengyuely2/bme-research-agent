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
        raise SafetyError('The Spark sheet contains multiple measurement blocks. Save one block as a separate copy.')
    start=headers[0];header=rows[start]
    wells=[(i,name.strip()) for i,name in enumerate(header) if re.fullmatch(r'[A-H](?:[1-9]|1[0-2])',name.strip())]
    if not wells or len({name for _,name in wells})!=len(wells):
        raise SafetyError('Missing or duplicate Spark well IDs; conversion refused.')
    records=[]
    for source_row,row in enumerate(rows[start+1:],start+2):
        if not row[0].strip():break
        try:
            cycle=float(row[0]);seconds=float(row[1])
        except (ValueError,IndexError):break
        if not math.isfinite(seconds) or seconds<0 or not cycle.is_integer() or cycle<1:
            raise SafetyError('Invalid Spark cycle number or actual time.')
        records.append((source_row,int(cycle),seconds,row))
    if len(records)<3 or len({r[1] for r in records})!=len(records) or any(a[2]>=b[2] for a,b in zip(records,records[1:])):
        raise SafetyError('Spark requires at least 3 unique cycles with strictly increasing actual times.')
    expected=[row[4] for row in rows[:start] if len(row)>4 and row[0].strip()=='Kinetic cycles']
    if expected and (len(expected)!=1 or not expected[0].isdigit() or int(expected[0])!=len(records)):
        raise SafetyError('Actual Spark cycle count differs from the configured count. No silent truncation; verify the source.')
    active=[(i,name) for i,name in wells if any(r[3][i].strip() for r in records)]
    if not active or len(active)*len(records)>10000:
        raise SafetyError('Spark conversion is limited to 10,000 well/time records. No data were truncated.')
    from openpyxl.utils import get_column_letter
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow(['time_min','signal_au','plate_column','well','plate_row','cycle','source_cell'])
    for index,well in active:
        for row_no,cycle,seconds,row in records:
            writer.writerow([format(seconds/60,'.15g'),row[index],int(well[1:]),well,well[0],cycle,f'{get_column_letter(index+1)}{row_no}'])
    intervals=[b[2]-a[2] for a,b in zip(records,records[1:])]
    notes=[f'Spark kinetics wide table converted read-only: header row {start+1} rows; {len(records)} cycles; {len(active)} measured wells; {len(records)*len(active)} records.',
           f'Actual instrument Time [s] / 60; adjacent intervals {min(intervals):.3f}–{max(intervals):.3f} seconds. The configured target interval was not used.',
           'plate_column is the physical plate column and well is the well ID. Wells within a column are candidate replicates, not a confirmed experimental layout or biological independence. Concentrations are not inferred from signals. source_cell preserves the original Excel coordinate.']
    if any('Unable to meet' in str(v) for row in rows for v in row):
        notes.append('The instrument reported that the target kinetics interval could not be met. Analyze using actual times.')
    return output.getvalue(),notes
