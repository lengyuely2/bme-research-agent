"""Build a tiny synthetic PDF fixture. No scientific claims or third-party paper content."""
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject

ROOT = Path(__file__).resolve().parents[1]
writer = PdfWriter()
font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})

def page(lines, graph=False):
    current=writer.add_blank_page(width=612,height=792)
    current[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    commands=['BT /F1 17 Tf 48 740 Td']
    for index,line in enumerate(lines):
        if index: commands.append('0 -24 Td /F1 11 Tf')
        safe=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        commands.append(f'({safe}) Tj')
    commands.append('ET')
    if graph:
        commands.extend(['0.45 0.49 0.70 RG 1.5 w 85 320 m 85 500 l S',
            '0.1 0.1 0.1 RG 85 320 m 510 320 l S', '85 320 m 85 500 l S',
            '0.45 0.49 0.70 RG 2 w 90 324 m 140 339 l 190 362 l 290 399 l 490 479 l S',
            'BT /F1 11 Tf 90 535 Td (Figure 1. Synthetic calibration means - not experimental evidence.) Tj ET'])
        for x,label in [(90,'0'),(140,'1'),(190,'2'),(290,'4'),(490,'8')]:
            commands.append(f'BT /F1 10 Tf {x-3} 301 Td ({label}) Tj ET')
        for y,label in [(320,'0'),(370,'0.5'),(420,'1.0'),(470,'1.5')]:
            commands.append(f'BT /F1 10 Tf 58 {y-3} Td ({label}) Tj ET')
        commands.extend(['BT /F1 10 Tf 240 275 Td (Concentration [nM]) Tj ET',
                         'BT /F1 10 Tf 90 510 Td (Signal [arbitrary units]) Tj ET'])
    stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
    current[NameObject('/Contents')]=writer._add_object(stream)

page(['SYNTHETIC BIOSENSOR STUDY - SOFTWARE DEMO','This is a generated test document, not a published paper.',
 'No patient samples, real measurements, DOI, or clinical claims are included.',
 'Purpose: demonstrate a biosensor paper-reading workflow.',
 'Recognition element: a hypothetical affinity probe on a sensing surface.',
 'Transduction: simulated fluorescence intensity proportional to concentration.',
 'Methods (all invented for software testing): PBS buffer, room temperature,',
 '15 minute incubation. Concentrations: 0, 1, 2, 4, 8 nM.',
 'Three synthetic replicate values at each concentration; see the CSV fixture.',
 'Control: a simulated blank. Matrix selectivity and stability were not tested.',
 'These conditions are not a validated experimental protocol.',
 'Physical PDF page 1 of 2.'])
page(['RESULTS AND LIMITATIONS - SYNTHETIC ONLY','Mean signals: 0.04, 0.20, 0.42, 0.79, 1.59 arbitrary units.',
 'Figure 1 illustrates the five synthetic means.',
 'Detection limit and clinical sensitivity were not measured or reported.',
 'There is no real sample validation, specificity study, or stability study.',
 'The document tests page citations and figure reading only.'],True)
writer.add_metadata({'/Title':'Synthetic biosensor software demo','/Author':'BME Workbench test fixture'})
with (ROOT/'samples'/'paper_demo.pdf').open('wb') as output: writer.write(output)
print(ROOT/'samples'/'paper_demo.pdf')
