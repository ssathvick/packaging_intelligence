"""Minimal generated PDF fixtures; no image-processing dependency in the runtime."""
import re
import subprocess
import zlib
from pathlib import Path

def write_pdf(path,objects):
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,body in enumerate(objects,1):
        offsets.append(len(out));out.extend(f'{i} 0 obj\n'.encode()+body+b'\nendobj\n')
    xref=len(out);out.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:out.extend(f'{offset:010d} 00000 n \n'.encode())
    out.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode());path.write_bytes(out)

def text_pdf(path,text):
    escaped=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream=f'BT /F1 22 Tf 35 130 Td ({escaped}) Tj ET'.encode()
    write_pdf(path,[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream'])

def scanned_pdf(path):
    text=path.parent/'scan-original.pdf';text_pdf(text,'Component code: SCAN-104 Weight: 18 g')
    stem=path.parent/'scan-render'
    subprocess.run(['pdftoppm','-singlefile','-scale-to','2200',str(text),str(stem)],check=True,capture_output=True,timeout=30)
    ppm=Path(str(stem)+'.ppm').read_bytes();header=re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s',ppm)
    assert header
    width,height=map(int,header.groups());pixels=zlib.compress(ppm[header.end():])
    stream=b'q 800 0 0 200 0 0 cm /Im1 Do Q'
    write_pdf(path,[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 200] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>',
        f'<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(pixels)} >>\nstream\n'.encode()+pixels+b'\nendstream',
        f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream'])
